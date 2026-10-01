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


# ---------- 切片 3：forecast 导出下载 ----------


def test_forecast_export_report(forecast_shell_url):
    status, body = _get(forecast_shell_url + "/t/forecast/api/export/report")
    assert status == 200
    assert body[:2] == b"PK"  # xlsx 魔数
    assert len(body) > 1000


def test_forecast_export_metrics(forecast_shell_url):
    """中文平台名必须 percent-encode（前端 encodeURIComponent，GRILL G5）。"""
    status, body = _get(forecast_shell_url + "/t/forecast/api/export/metrics/%E5%A4%A9%E7%8C%AB")
    assert status == 200
    text = body.decode("utf-8-sig")
    assert "month" in text.splitlines()[0]


def test_forecast_export_missing_404(forecast_shell_url):
    with pytest.raises(urllib.error.HTTPError) as ei:
        _get(forecast_shell_url + "/t/forecast/api/export/metrics/%E4%B8%8D%E5%AD%98%E5%9C%A8")
    assert ei.value.code == 404
    assert "main.py run" in ei.value.read().decode()


def test_forecast_export_path_traversal_blocked(forecast_shell_url):
    """%2F 编码绕斜杠过滤的路径穿越必须 404（review round 1）。"""
    for payload in ("..%2F..%2Fconfig", "%2Fetc%2Fpasswd", "..%5C..%5Cconfig"):
        with pytest.raises(urllib.error.HTTPError) as ei:
            _get(forecast_shell_url + f"/t/forecast/api/export/metrics/{payload}")
        assert ei.value.code == 404, payload


def test_forecast_export_ui_entry():
    """review round 1/2 blocker：导出端点必须有可达的前端入口（US5/G5）。

    对应性校验：index.html 里每个 data-pane 页签都必须在 app.js 的
    切换逻辑中出现（round 2 抓到的假证据：只断言字符串存在，漏了切换漏接）。
    """
    import re

    html = (ROOT / "target_forecast" / "static" / "index.html").read_text(encoding="utf-8")
    js = (ROOT / "target_forecast" / "static" / "app.js").read_text(encoding="utf-8")
    panes = re.findall(r'data-pane="([^"]+)"', html)
    assert len(panes) >= 3 and "exports-pane" in panes
    for pane in panes:
        assert f'"{pane}"' in js, f"页签 {pane} 未接入切换逻辑"
    assert "api/export/report" in js and "encodeURIComponent" in js


# ---------- 切片 4：壳导航前端 ----------


def test_shell_page_has_nav_and_frame(base_url):
    status, html = _get(base_url + "/")
    text = html.decode()
    assert status == 200
    assert 'id="nav"' in text and 'id="frame"' in text
    assert "测算工作台" in text and "本机" in text
    assert 'href="style.css"' in text and 'src="app.js"' in text


def test_shell_root_page_tolerates_query(base_url):
    """深链 /?tool=xxx 必须 200——P0  shipped 的 bug（精确匹配 "/"），P2 e2e 暴露。"""
    status, html = _get(base_url + "/?tool=roi")
    assert status == 200 and "测算工作台" in html.decode()


def test_shell_static_assets(base_url):
    status, css = _get(base_url + "/style.css")
    assert status == 200 and "#f7f6f3" in css.decode()  # Xanthil 底 token
    status, js = _get(base_url + "/app.js")
    assert status == 200 and "tool" in js.decode()


def test_shell_statusbar(base_url):
    """状态栏（PRD D5）：产品名+版本、当前工具位、演示数据标记位、本机声明。"""
    _, html = _get(base_url + "/")
    text = html.decode()
    assert 'id="statusbar"' in text
    assert 'id="sb-tool"' in text and 'id="sb-demo"' in text
    assert "本机" in text
    _, js = _get(base_url + "/app.js")
    assert "demo_used" in js.decode()  # 数据源标记来自工具现有 /api/state（D5）


def test_shell_statusbar_xanthil_tokens(base_url):
    _, css = _get(base_url + "/style.css")
    text = css.decode()
    assert ".statusbar" in text and "#f4f3ef" in text  # surface-2 底（2026-09-28 橘accent 契约）


def test_shell_brand_and_boundary_badge(base_url):
    """2026-09-28 契约：品牌栏（JuanerAI+slogan+产品名）+ 边界徽 + 品牌图可访问。"""
    _, html = _get(base_url + "/")
    text = html.decode()
    assert "JuanerAI" in text and "持续做出更好的决策" in text
    assert "brand-mark" in text and "boundary-badge" in text
    status, _ = _get(base_url + "/assets/juanerai-logo-slogan.png")
    assert status == 200


def test_shell_assistant_panel(base_url):
    """P3 切片 4：助手面板结构 + 确认门 + 503 降级渲染逻辑可达。"""
    _, html = _get(base_url + "/")
    text = html.decode()
    assert 'id="assistant"' in text and 'id="as-msgs"' in text and 'id="as-input"' in text
    assert "assistant-toggle" in text
    _, js = _get(base_url + "/app.js")
    jst = js.decode()
    assert "api/assistant/chat" in jst          # chat 端点（相对路径）
    assert "pending_confirmation" in jst        # 确认门渲染
    assert "setup_hint" in jst                  # 503 降级指引
    assert "confirm" in jst                     # 两步确认回发


def test_default_registry_builds_all_tools():
    """默认注册表装配全部插件（启动脚本路径）。

    K3 授权：P2 前本断言精确等于两工具集合；第三工具接入后更新为
    「forecast/coupon 必在、roi 在、总数≥3」的超集校验——本 flow 唯一
    被允许修改的存量断言，其余断言冻结（.flow/prd.md D5）。
    """
    from workbench import build_default_registry

    reg = build_default_registry(ROOT)
    ids = set(reg.ids())
    assert {"forecast", "coupon"} <= ids and "roi" in ids and len(ids) >= 3
    names = {t["name"] for t in reg.manifest()}
    assert {"目标测算", "优惠券测算"} <= names and "投放 ROI" in names


# ---------- P2 切片 2：roi 插件壳内冒烟 ----------


@pytest.fixture(scope="module")
def roi_shell_url(tmp_path_factory):
    from roi_tool import plugin as roi_plugin

    reg = Registry()
    reg.register(roi_plugin.build_tool(tmp_path_factory.mktemp("roi")))
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(reg))
    t = threading.Thread(target=httpd.serve_forever, daemon=True)
    t.start()
    yield f"http://127.0.0.1:{httpd.server_address[1]}"
    httpd.shutdown()


def test_roi_shell_pages(roi_shell_url):
    status, html = _get(roi_shell_url + "/t/roi/")
    assert status == 200 and "投放 ROI 测算" in html.decode()
    status, css = _get(roi_shell_url + "/t/roi/style.css")
    assert status == 200 and "#f7f6f3" in css.decode()
    status, js = _get(roi_shell_url + "/t/roi/app.js")
    assert status == 200 and 'api("api/calc"' in js.decode()  # 相对路径 calc 调用点（经 api() 帮助函数）


def test_roi_shell_state(roi_shell_url):
    status, body = _get(roi_shell_url + "/t/roi/api/state")
    state = json.loads(body)
    assert status == 200
    assert state["engine_version"]
    assert state["synthetic"] is True and state["demo_used"] is True
    assert len(state["plans"]) == 4
    assert set(state["scenarios"]) == {"保守", "基准", "挑战"}
    # G4 契约：参数默认值由服务端下发（前端添加计划用），不硬编码在前端
    assert set(state["param_defaults"]) == {"spend_cny", "cpc_cny", "cvr", "aov_cny",
                                            "gross_margin", "refund_rate"}


def test_roi_shell_calc_end_to_end(roi_shell_url):
    _, state = _get(roi_shell_url + "/t/roi/api/state")
    plans = json.loads(state)["plans"]
    status, res = _post(roi_shell_url + "/t/roi/api/calc",
                        {"plans": plans, "scenarios": {"基准": {"cvr_growth": 0.0, "aov_growth": 0.0}}})
    assert status == 200
    base = res["scenarios"]["基准"]
    assert len(base["plans"]) == 4 and len(base["ranking"]) == 4
    assert base["totals"]["spend"] > 0


def test_roi_shell_calc_422(roi_shell_url):
    status, res = _post(roi_shell_url + "/t/roi/api/calc",
                        {"plans": [{"name": "坏计划", "spend_cny": 0, "cpc_cny": 1, "cvr": 0.05,
                                    "aov_cny": 100, "gross_margin": 0.4, "refund_rate": 0.1}],
                         "scenarios": {}})
    assert status == 422 and "spend_cny" in res["error"]


def test_roi_unknown_route_404(roi_shell_url):
    with pytest.raises(urllib.error.HTTPError) as ei:
        _get(roi_shell_url + "/t/roi/api/nope")
    assert ei.value.code == 404


def test_roi_static_no_root_absolute_api():
    import re

    for js in (ROOT / "roi_tool" / "static").glob("*.js"):
        text = js.read_text(encoding="utf-8")
        assert not re.search(r"""["']/api""", text), f"{js.name} 含根绝对 API 路径"


def test_shell_collapsible_sidebars(base_url):
    """左右侧栏可收起：左导航折叠为图标栏，助手面板为占位式可收合。"""
    _, html = _get(base_url + "/")
    text = html.decode()
    # 左侧折叠控件 + 图标栏形态 + 状态记忆
    assert 'id="sidebar-toggle"' in text
    assert 'id="sidebar"' in text and "sidebar-collapsed" not in text  # 初始展开，类由 JS 切换
    # 右侧助手为布局列（非 fixed 遮盖）+ 独立关闭按钮
    assert 'id="assistant-close"' in text
    # 空态引导（不再全空白）
    assert "as-empty" in text or "试试问我" in text
    _, js = _get(base_url + "/app.js")
    jst = js.decode()
    assert "localStorage" in jst and "sidebar-collapsed" in jst  # 折叠状态记忆
    assert "assistant-collapsed" in jst or "collapsed" in jst    # 助手收合状态
    _, css = _get(base_url + "/style.css")
    ctext = css.decode()
    assert "transition" in ctext and "width" in ctext            # 收合有过渡动画
    assert "position: fixed" not in ctext.split(".assistant")[1].split("}")[0] if ".assistant" in ctext else True


def test_shell_nav_icon_chips(base_url):
    """导航 emoji 图标统一收进徽章容器，不再裸浮彩色 emoji。"""
    _, css = _get(base_url + "/style.css")
    assert ".nav-icon" in css.decode()
    _, js = _get(base_url + "/app.js")
    assert "nav-icon" in js.decode()
