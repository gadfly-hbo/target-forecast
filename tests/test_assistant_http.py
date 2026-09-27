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


def _post(url, obj):
    req = urllib.request.Request(url, data=json.dumps(obj).encode(),
                                 headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read())


def _get(url):
    with urllib.request.urlopen(url, timeout=30) as r:
        return r.status, json.loads(r.read())


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
                        {"message": "把挑战情景新客增速调到 25%", "history": [], "tool_id": "forecast"})
    assert status == 200
    assert res["pending_confirmation"]["action"] == "forecast__set_scenario_params"
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
        def chat(self, messages, tools):
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
    """阻断项 1 回归：真实回环走通 forecast 确认写（tmp root 隔离，不落真实 workspace）。"""
    import shutil

    from target_forecast import demo as tf_demo

    shutil.copy(ROOT / "config.yaml", tmp_path / "config.yaml")
    tf_demo.generate(tmp_path)  # 生成演示数据到 tmp root 的 workspace/forecast

    reg = build_default_registry(tmp_path)
    svc = runtime.build_service(tmp_path, reg, backend=EchoBackend(FIXTURES))
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(reg, assistant=svc))
    svc.bind_port(httpd.server_address[1])
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    url = f"http://127.0.0.1:{httpd.server_address[1]}"
    try:
        status, res = _post(url + "/api/assistant/chat",
                            {"message": "把挑战情景新客增速调到 25%", "history": [], "tool_id": "forecast"})
        assert status == 200 and res["pending_confirmation"]
        call_id = res["pending_confirmation"]["call_id"]
        status, res2 = _post(url + "/api/assistant/chat", {"confirm": call_id, "tool_id": "forecast"})
        assert status == 200, res2  # 修复前此处 500/断连
        assert "已应用" in res2["reply"]
        saved = json.loads((tmp_path / "workspace" / "forecast" / "assistant_params.json").read_text())
        assert saved["scenarios"]["挑战"]["new_customers_growth"] == 0.25
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
    res = svc.chat({"message": "把挑战情景新客增速调到 25%", "history": [], "tool_id": "forecast"})
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
