# -*- coding: utf-8 -*-
"""httpkit 收敛前的 characterization 测试：钉住 4 个 server 的现状可观察行为。

红队盲区清单（.flow/red-team.md）转正：响应头、404 体形状、缺失静态文件状态码、
demo 全流程 allow_nan=False 可序列化、serve 子进程冒烟、import 分层守卫。

约定：标注 CURRENT 的断言记录漂移现状，在对应切换任务完成后按
prd.md 的 deliberate-change 清单翻转（每条翻转都必须在提交说明中引用清单编号）。
"""
import ast
import json
import socket
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from coupon_tool import server as coupon_server  # noqa: E402
from roi_tool import server as roi_server  # noqa: E402
from target_forecast import server as fc_server  # noqa: E402
from workbench import Registry, make_handler as shell_make_handler  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent

# 壳响应已统一带 no-store（deliberate-change #1，原壳 _send 缺该头）
SHELL_CACHE_CONTROL_CURRENT = "no-store"


def _serve(httpd):
    t = threading.Thread(target=httpd.serve_forever, daemon=True)
    t.start()
    return f"http://127.0.0.1:{httpd.server_address[1]}"


@pytest.fixture(scope="module")
def coupon_url(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("coupon_char")
    app = coupon_server.Workbench(data_dir=str(tmp / "data"), out_dir=str(tmp / "out"),
                                  templates_dir=str(tmp / "tpl"))
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), coupon_server.make_handler(app))
    yield _serve(httpd)
    httpd.shutdown()


@pytest.fixture(scope="module")
def roi_url(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("roi_char")
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), roi_server.make_handler(roi_server.App(tmp)))
    yield _serve(httpd)
    httpd.shutdown()


@pytest.fixture(scope="module")
def fc_state():
    cfg = fc_server.load_cfg(ROOT)
    state = fc_server.WorkbenchState(ROOT, cfg["caliber"])
    state.load()
    return state, cfg


@pytest.fixture(scope="module")
def fc_url(fc_state):
    state, cfg = fc_state
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), fc_server.make_handler(state, cfg))
    yield _serve(httpd)
    httpd.shutdown()


@pytest.fixture(scope="module")
def shell_url():
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), shell_make_handler(Registry()))
    yield _serve(httpd)
    httpd.shutdown()


def _raw_get(url):
    """返回 (status, headers, body)；404 也正常返回不抛。"""
    try:
        with urllib.request.urlopen(url, timeout=30) as r:
            return r.status, r.headers, r.read()
    except urllib.error.HTTPError as e:
        return e.code, e.headers, e.read()


def _raw_post(url, obj):
    req = urllib.request.Request(url, data=json.dumps(obj).encode(),
                                 headers={"Content-Type": "application/json"}, method="POST")
    return _raw_get_req(req)


def _raw_get_req(req):
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return r.status, r.headers, r.read()
    except urllib.error.HTTPError as e:
        return e.code, e.headers, e.read()


# 1. 响应头现状：三个工具有 no-store，壳没有
def test_cache_control_header_current_state(coupon_url, roi_url, fc_url, shell_url):
    for base in (coupon_url, roi_url, fc_url):
        _, headers, _ = _raw_get(base + "/api/state")
        assert headers.get("Cache-Control") == "no-store"
    _, headers, _ = _raw_get(shell_url + "/api/state")
    assert headers.get("Cache-Control") == SHELL_CACHE_CONTROL_CURRENT


# 2. 独立 handler 404 体形状：forecast 已统一为 JSON（deliberate-change #2），四端一致
def test_404_body_shape_current_state(coupon_url, roi_url, fc_url, shell_url):
    for base in (fc_url, coupon_url, roi_url, shell_url):
        status, _, body = _raw_get(base + "/nope")
        assert status == 404 and json.loads(body) == {"error": "not found"}


# 3. 缺失静态文件：统一 static() 后 404（deliberate-change #3，原 forecast 为 500）
def test_forecast_missing_static_404(fc_state, monkeypatch, tmp_path):
    monkeypatch.setattr(fc_server, "STATIC_DIR", tmp_path)  # 空目录
    state, cfg = fc_state
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), fc_server.make_handler(state, cfg))
    base = _serve(httpd)
    try:
        status, _, body = _raw_get(base + "/style.css")
        assert status == 404 and json.loads(body) == {"error": "not found"}
    finally:
        httpd.shutdown()


# 4. demo 全流程响应可被 allow_nan=False 序列化（统一 NaN 策略不引入新异常）
def test_demo_responses_serialize_with_allow_nan_false(coupon_url, roi_url, fc_url):
    _, _, demo = _raw_post(coupon_url + "/api/demo", {})
    demo = json.loads(demo)
    _, _, cmp_body = _raw_post(coupon_url + "/api/compare", {"scenario": demo["scenario"]})
    _, _, roi_body = _raw_post(roi_url + "/api/calc", {})
    _, _, fc_body = _raw_post(fc_url + "/api/calc", {"scenarios": {}})
    for body in (cmp_body, roi_body, fc_body):
        json.dumps(json.loads(body), ensure_ascii=False, allow_nan=False)  # 不抛即通过


# 5. coupon 独立入口子进程冒烟（真 socket；cwd=tmp 保证 hermetic）
def test_coupon_standalone_serve_subprocess(tmp_path):
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()
    proc = subprocess.Popen(
        [sys.executable, "-m", "coupon_tool", "serve", "--port", str(port),
         "--data-dir", str(tmp_path / "data")],
        cwd=tmp_path, env={"PATH": "/usr/bin:/bin", "PYTHONPATH": str(ROOT)},
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        deadline = time.time() + 10
        while time.time() < deadline:
            try:
                status, _, body = _raw_get(f"http://127.0.0.1:{port}/api/state")
                if status == 200:
                    assert json.loads(body)["engine_version"]
                    return
            except (urllib.error.URLError, ConnectionError, OSError):
                time.sleep(0.2)
        pytest.fail("coupon 独立 serve 10s 内未就绪")
    finally:
        proc.terminate()
        proc.wait(timeout=10)


# 6. import 分层守卫：三个工具 server 不得 import workbench.*
@pytest.mark.parametrize("mod_path", ["coupon_tool/server.py", "roi_tool/server.py",
                                      "target_forecast/server.py"])
def test_tool_servers_do_not_import_workbench(mod_path):
    tree = ast.parse((ROOT / mod_path).read_text(encoding="utf-8"))
    roots = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            roots.update(a.name.split(".")[0] for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            roots.add(node.module.split(".")[0])
    assert "workbench" not in roots, f"{mod_path} 反向依赖壳包：{roots & {'workbench'}}"
