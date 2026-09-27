"""workbench 壳骨架冒烟测试：插件协议注册、前缀分发、未知工具 404。

示例插件 hello 内联于本测试文件（仅用于验证协议，不进生产导航）。
"""

import json
import sys
import threading
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from workbench import Registry, make_handler  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent


def _hello_plugin():
    """最小示例插件：一个页面 + 一个 ping API，验证 manifest 与分发协议。"""

    def _send(h, code, body, ctype="application/json; charset=utf-8"):
        data = body.encode("utf-8") if isinstance(body, str) else json.dumps(body).encode("utf-8")
        h.send_response(code)
        h.send_header("Content-Type", ctype)
        h.send_header("Content-Length", str(len(data)))
        h.end_headers()
        h.wfile.write(data)

    def handle_get(h, path):
        if path in ("/", "/index.html"):
            _send(h, 200, "<html><body>示例插件</body></html>", "text/html; charset=utf-8")
            return True
        if path.split("?")[0] == "/api/ping":
            _send(h, 200, {"pong": True})
            return True
        return False

    def handle_post(h, path):
        return False

    return {
        "id": "hello",
        "name": "示例工具",
        "icon": "🧪",
        "static_dir": None,
        "seed_demo": None,
        "actions": [],
        "handle_get": handle_get,
        "handle_post": handle_post,
    }


@pytest.fixture(scope="module")
def base_url():
    reg = Registry()
    reg.register(_hello_plugin())
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(reg))
    t = threading.Thread(target=httpd.serve_forever, daemon=True)
    t.start()
    yield f"http://127.0.0.1:{httpd.server_address[1]}"
    httpd.shutdown()


def _get(url):
    with urllib.request.urlopen(url, timeout=30) as r:
        return r.status, r.read()


def _post(url, obj):
    req = urllib.request.Request(url, data=json.dumps(obj).encode(),
                                 headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read())


def test_shell_state_lists_tools(base_url):
    status, body = _get(base_url + "/api/state")
    data = json.loads(body)
    assert status == 200
    tools = {t["id"]: t for t in data["tools"]}
    assert set(tools) == {"hello"}
    assert tools["hello"]["name"] == "示例工具" and tools["hello"]["icon"] == "🧪"


def test_shell_root_page(base_url):
    status, html = _get(base_url + "/")
    assert status == 200 and "测算工作台" in html.decode()


def test_tool_page_and_api_dispatch(base_url):
    status, html = _get(base_url + "/t/hello/")
    assert status == 200 and "示例插件" in html.decode()
    status, body = _get(base_url + "/t/hello/api/ping")
    assert status == 200 and json.loads(body) == {"pong": True}


def test_query_string_preserved(base_url):
    """前缀剥离后必须保留 query string（工具的 ?reload=1 依赖）。"""
    status, body = _get(base_url + "/t/hello/api/ping?x=1")
    assert status == 200 and json.loads(body) == {"pong": True}


def test_unknown_tool_404(base_url):
    with pytest.raises(urllib.error.HTTPError) as ei:
        _get(base_url + "/t/nope/")
    assert ei.value.code == 404


def test_unknown_route_in_tool_404(base_url):
    with pytest.raises(urllib.error.HTTPError) as ei:
        _get(base_url + "/t/hello/api/nope")
    assert ei.value.code == 404


# ---------- 切片 2：coupon 插件化 ----------


@pytest.fixture(scope="module")
def coupon_shell_url(tmp_path_factory):
    from coupon_tool import plugin as coupon_plugin

    tmp = tmp_path_factory.mktemp("shell_coupon")
    reg = Registry()
    reg.register(coupon_plugin.build_tool(tmp))
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(reg))
    t = threading.Thread(target=httpd.serve_forever, daemon=True)
    t.start()
    yield f"http://127.0.0.1:{httpd.server_address[1]}"
    httpd.shutdown()


def test_coupon_shell_manifest_and_state(coupon_shell_url):
    status, body = _get(coupon_shell_url + "/api/state")
    tools = {t["id"]: t for t in json.loads(body)["tools"]}
    assert status == 200 and tools["coupon"]["name"] == "优惠券测算"

    status, body = _get(coupon_shell_url + "/t/coupon/api/state")
    state = json.loads(body)
    assert status == 200 and state["engine_version"]
    assert "本机运行" in state["boundary"]


def test_coupon_shell_end_to_end(coupon_shell_url):
    """壳内前缀下走通 demo → compare 业务闭环。"""
    status, demo = _post(coupon_shell_url + "/t/coupon/api/demo", {})
    assert status == 200 and demo["scenario_id"] == "coupon-demo-001"
    status, res = _post(coupon_shell_url + "/t/coupon/api/compare",
                        {"scenario": demo["scenario"]})
    assert status == 200 and res["rows"] and res["ranking"]


def test_coupon_static_no_root_absolute_api():
    """不变量：工具前端静态文件不得含根绝对 /api 引用（可移植性）。"""
    import re

    static = (ROOT / "coupon_tool" / "static").glob("*.js")
    for js in static:
        text = js.read_text(encoding="utf-8")
        assert not re.search(r"""["']/api""", text), f"{js.name} 含根绝对 API 路径"


# ---------- 切片 3：forecast 插件化 ----------


@pytest.fixture(scope="module")
def forecast_shell_url():
    from target_forecast import plugin as forecast_plugin

    reg = Registry()
    reg.register(forecast_plugin.build_tool(ROOT))
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(reg))
    t = threading.Thread(target=httpd.serve_forever, daemon=True)
    t.start()
    yield f"http://127.0.0.1:{httpd.server_address[1]}"
    httpd.shutdown()


def test_forecast_shell_manifest_and_state(forecast_shell_url):
    status, body = _get(forecast_shell_url + "/api/state")
    tools = {t["id"]: t for t in json.loads(body)["tools"]}
    assert status == 200 and tools["forecast"]["name"] == "目标测算"

    status, body = _get(forecast_shell_url + "/t/forecast/api/state")
    state = json.loads(body)
    assert status == 200
    assert set(state["platforms"]) == {"天猫", "抖音", "京东", "私域"}
    assert state["platforms"]["天猫"]["mode"] == "A"


def test_forecast_shell_calc(forecast_shell_url):
    """壳内前缀下走通 calc 业务闭环（断言与独立 server 冒烟一致）。"""
    status, res = _post(forecast_shell_url + "/t/forecast/api/calc", {"scenarios": {}})
    assert status == 200
    assert set(res["platforms"]) == {"天猫", "抖音", "京东", "私域"}
    assert res["platforms"]["私域"]["main_view"] == "场"
    assert len(res["consolidated"]) == 3 * 12


def test_forecast_static_no_root_absolute_api():
    import re

    for js in (ROOT / "target_forecast" / "static").glob("*.js"):
        text = js.read_text(encoding="utf-8")
        assert not re.search(r"""["']/api""", text), f"{js.name} 含根绝对 API 路径"


# ---------- 切片 4：壳导航前端 ----------


def test_shell_page_has_nav_and_frame(base_url):
    status, html = _get(base_url + "/")
    text = html.decode()
    assert status == 200
    assert 'id="nav"' in text and 'id="frame"' in text
    assert "测算工作台" in text and "本机" in text
    assert 'href="style.css"' in text and 'src="app.js"' in text


def test_shell_static_assets(base_url):
    status, css = _get(base_url + "/style.css")
    assert status == 200 and "#f7f6f3" in css.decode()  # Xanthil 底 token
    status, js = _get(base_url + "/app.js")
    assert status == 200 and "tool" in js.decode()


def test_default_registry_builds_all_tools():
    """默认注册表装配两个真实插件（启动脚本路径）。"""
    from workbench import build_default_registry

    reg = build_default_registry(ROOT)
    assert set(reg.ids()) == {"forecast", "coupon"}
    names = {t["name"] for t in reg.manifest()}
    assert names == {"目标测算", "优惠券测算"}
