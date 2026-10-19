"""P3 切片 3：壳端点 /api/assistant/chat HTTP 冒烟（Echo 后端 + 真注册表 + 内部回环）。"""

import json
import sys
import threading
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from workbench import build_default_registry, make_handler  # noqa: E402
from workbench.assistant import runtime  # noqa: E402
from workbench.assistant.backend import BackendUnavailable, EchoBackend  # noqa: E402
from workbench.assistant.fixtures import FIXTURES  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent


def _start(service):
    reg = build_default_registry(ROOT)
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(reg, assistant=service))
    service.bind_port(httpd.server_address[1])
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    return httpd, f"http://127.0.0.1:{httpd.server_address[1]}"


from _http import get_json as _get, post as _post


@pytest.fixture(scope="module")
def echo_server():
    reg = build_default_registry(ROOT)
    svc = runtime.build_service(ROOT, reg, backend=EchoBackend(FIXTURES))
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(reg, assistant=svc))
    svc.bind_port(httpd.server_address[1])
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{httpd.server_address[1]}"
    httpd.shutdown()


def test_chat_endpoint_end_to_end(echo_server):
    """解读类意图经 HTTP 全链路：LLM(回放) -> 工具执行(回环) -> 数字入回复。

    数字来自真实 roi 引擎（演示集实算），与 roi_tool 单测同源。
    """
    from roi_tool import demo
    expected = demo.evaluate_demo()["scenarios"]["基准"]["totals"]["net"]

    status, res = _post(echo_server + "/api/assistant/chat",
                        {"message": "基准情景净贡献是多少", "history": [], "tool_id": "roi"})
    assert status == 200
    assert f"{expected:.2f}" in res["reply"]
    assert res["pending_confirmation"] is None


def test_chat_write_confirmation_over_http(echo_server):
    status, res = _post(echo_server + "/api/assistant/chat",
                        {"message": "把计划1的 cvr 调计划到 5%", "history": [], "tool_id": "roi"})
    assert status == 200
    assert res["pending_confirmation"]["action"] == "roi__set_plan_params"
    # 确认后执行（tmp 隔离：用临时 root 避免写真实 workspace）
    # —— 本 fixture 用真实 ROOT 仅走到 pending 步，确认步在 service 单测覆盖副作用


def test_chat_bad_confirm_400(echo_server):
    status, res = _post(echo_server + "/api/assistant/chat", {"confirm": "no-such-id"})
    assert status == 400 and "confirm" in res["error"]


def test_backend_status(echo_server):
    status, res = _get(echo_server + "/api/assistant/status")
    assert status == 200 and res["backend"] == "EchoBackend"


def test_backend_unavailable_503():
    class DeadBackend:
        def chat(self, messages, tools, write_names=None):
            raise BackendUnavailable("no key configured")

    reg = build_default_registry(ROOT)
    svc = runtime.build_service(ROOT, reg, backend=DeadBackend())
    httpd, url = _start(svc)
    try:
        status, res = _post(url + "/api/assistant/chat", {"message": "你好", "history": [], "tool_id": "roi"})
        assert status == 503
        assert "assistant.env" in res["setup_hint"]
    finally:
        httpd.shutdown()


# ---------- review round 1 修复回归 ----------

def test_confirm_write_real_loopback(tmp_path):
    """阻断项 1 回归：真实回环走通 AI 提案（tmp root 隔离；G2 双轨——提案落盘、草稿不动）。"""
    import shutil

    from target_forecast.plans import service as plan_service

    shutil.copy(ROOT / "config.yaml", tmp_path / "config.yaml")
    draft = plan_service.create_plan(tmp_path, "测试提案链路")
    #  fixture ④ 的 plan_id 固定为 plan-1：这里改为先建方案再用真实 id 走 chat
    import copy

    import workbench.assistant.fixtures as fx
    fixtures = copy.deepcopy(fx.FIXTURES)  # 深拷贝：改 plan_id 不污染共享 fixtures
    for f in fixtures:
        for tc in f.get("tool_calls") or []:
            if tc["name"] == "forecast__propose_plan_changes":
                tc["args"]["plan_id"] = draft["plan_id"]

    reg = build_default_registry(tmp_path)
    svc = runtime.build_service(tmp_path, reg, backend=EchoBackend(fixtures))
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(reg, assistant=svc))
    svc.bind_port(httpd.server_address[1])
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    url = f"http://127.0.0.1:{httpd.server_address[1]}"
    try:
        status, res = _post(url + "/api/assistant/chat",
                            {"message": "给基准情景建议", "history": [], "tool_id": "forecast"})
        assert status == 200, res
        # 提案 dry-run：不走确认门，回复带差异摘要
        assert res["pending_confirmation"] is None
        assert "new_customers_growth" in res["reply"]
        # 提案已落盘、工作稿未变（G2：AI 不直写业务对象）
        proposals = plan_service.list_proposals(tmp_path, draft["plan_id"])
        assert len(proposals) == 1 and proposals[0]["status"] == "pending"
        assert proposals[0]["patches"][0]["new"] == 0.2
        assert plan_service.load_draft(tmp_path, draft["plan_id"])["revision"] == 1
    finally:
        httpd.shutdown()


def test_confirm_apply_proposal_real_loopback(tmp_path):
    """切片5 契约冒烟：stage→confirm→exec_write→draft 真实落盘（唯一写动作，确认门后执行）。"""
    import shutil

    from target_forecast.plans import service as plan_service

    shutil.copy(ROOT / "config.yaml", tmp_path / "config.yaml")
    draft = plan_service.create_plan(tmp_path, "采纳链路冒烟")
    pid = draft["plan_id"]
    proposal = plan_service.propose_change(tmp_path, pid, "基准",
                                           {"new_customers_growth": 0.22}, "获客加码",
                                           base_revision=1)

    reg = build_default_registry(tmp_path)
    svc = runtime.build_service(tmp_path, reg, backend=EchoBackend(FIXTURES))
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(reg, assistant=svc))
    svc.bind_port(httpd.server_address[1])
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    url = f"http://127.0.0.1:{httpd.server_address[1]}"
    try:
        # 写提案登记（sidecar /stage 同款入口）→ 确认 → 真实回环执行 apply
        staged = svc.stage("forecast__apply_proposal",
                           {"plan_id": pid, "proposal_id": proposal["proposal_id"]})
        assert "采纳提案" in staged["preview"]  # 确认门预览可见
        status, res = _post(url + "/api/assistant/chat",
                            {"confirm": staged["call_id"], "tool_id": "forecast"})
        assert status == 200, res
        assert "已采纳提案" in res["reply"] and "需重新确认" in res["reply"]
        # draft 真实落盘：修订 +1、假设确认失效（与工作区采纳按钮同一业务入口）
        d = plan_service.load_draft(tmp_path, pid)
        assert d["revision"] == 2
        assert d["scenarios"]["基准"]["params"]["new_customers_growth"] == 0.22
        assert plan_service.confirmation_status(d)["assumptions"]["confirmed"] is False
    finally:
        httpd.shutdown()


def test_sidecar_dir_resolution():
    """阻断项 2 回归：sidecar 目录解析到仓库内而非父目录。"""
    d = runtime._sidecar_dir(ROOT)
    assert d == ROOT / "assistant-sidecar"
    assert (d / "dist" / "server.js").is_file() or (d / "src" / "server.ts").is_file()


def test_roi_rejects_unknown_plan_name(roi_shell_url):
    """SUGGESTION 4 回归：幻觉计划名不得落盘。"""
    status, res = _post(roi_shell_url + "/t/roi/api/assistant_params",
                        {"plans": {"不存在的计划": {"cvr": 0.05}}})
    assert status == 422 and "计划" in res["error"]


def test_cancel_clears_pending():
    """SUGGESTION 6 回归：取消清理 pending，call_id 一次性语义不变。"""
    import pytest as _pytest

    from workbench.assistant.service import AssistantService
    reg = build_default_registry(ROOT)
    svc = AssistantService(reg, EchoBackend(FIXTURES), lambda *a, **k: {})
    res = svc.chat({"message": "把计划1的 cvr 调计划到 5%", "history": [], "tool_id": "roi"})
    call_id = res["pending_confirmation"]["call_id"]
    out = svc.chat({"cancel": call_id})
    assert out["reply"]
    with _pytest.raises(KeyError):
        svc.chat({"confirm": call_id})


def test_loopback_tool_error_maps_to_502():
    """SUGGESTION 5 回归：工具执行 HTTP 错误映射为结构化 502 而非断连。"""
    import urllib.error

    def boom(method, path, body=None):
        raise urllib.error.HTTPError(path, 500, "tool crashed", {}, None)

    reg = build_default_registry(ROOT)
    svc = runtime.build_service(ROOT, reg, backend=EchoBackend(FIXTURES))
    svc.http = boom
    code, body = runtime.handle_chat(svc, {"message": "基准情景净贡献是多少", "history": [], "tool_id": "roi"})
    assert code == 502 and "error" in body


@pytest.fixture(scope="module")
def roi_shell_url(tmp_path_factory):
    from roi_tool import plugin as roi_plugin

    from workbench import Registry

    reg = Registry()
    reg.register(roi_plugin.build_tool(tmp_path_factory.mktemp("roi_guard")))
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(reg))
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{httpd.server_address[1]}"
    httpd.shutdown()


def test_sidecar_backend_parses_orchestrated():
    """REVIEW B1 回归：PiSidecarBackend 必须解析 orchestrated 与透传字段
    （否则真实路径落回旧循环=双登记）。"""
    import threading
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
    from workbench.assistant.backend import PiSidecarBackend

    class H(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def do_POST(self):
            n = int(self.headers.get("Content-Length") or 0)
            body = json.loads(self.rfile.read(n))
            assert body["write_actions"] == ["roi__set_plan_params"]  # 私有协议透传
            payload = {"reply": "已登记，请确认", "orchestrated": True,
                       "tool_calls": [{"name": "roi__set_plan_params", "args": {"plan": "P"},
                                       "summary": "写提案已登记", "stage_pending": True,
                                       "call_id": "cid-9", "preview": "cvr → 0.05"}]}
            data = json.dumps(payload).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

    httpd = ThreadingHTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    try:
        backend = PiSidecarBackend(f"http://127.0.0.1:{httpd.server_address[1]}")
        result = backend.chat([{"role": "user", "content": "hi"}], [{"type": "function", "function": {"name": "f"}}],
                              write_names={"roi__set_plan_params"})
        assert result.orchestrated is True
        tc = result.tool_calls[0]
        assert tc["stage_pending"] is True and tc["call_id"] == "cid-9" and tc["summary"] == "写提案已登记"
    finally:
        httpd.shutdown()
