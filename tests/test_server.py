"""工作台服务冒烟测试：起随机端口，验证静态页与两个 JSON API。"""

import json
import sys
import threading
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from target_forecast import server  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture(scope="module")
def base_url():
    cfg = server.load_cfg(ROOT)
    state = server.WorkbenchState(ROOT, cfg["caliber"])
    state.load()
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), server.make_handler(state, cfg))
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
    with urllib.request.urlopen(req, timeout=60) as r:
        return r.status, json.loads(r.read())


def test_static_pages(base_url):
    status, html = _get(base_url + "/")
    assert status == 200 and "目标测算工作台" in html.decode()
    status, js = _get(base_url + "/app.js")
    assert status == 200 and "recalc" in js.decode()


def test_state_api(base_url):
    status, body = _get(base_url + "/api/state")
    data = json.loads(body)
    assert status == 200
    assert set(data["platforms"]) == {"天猫", "抖音", "京东", "私域"}
    assert data["platforms"]["天猫"]["mode"] == "A" and data["platforms"]["私域"]["mode"] == "B"
    assert data["platforms"]["天猫"]["months"] == 24


def test_calc_api_and_param_effect(base_url):
    _, default = _post(base_url + "/api/calc", {"scenarios": {}})
    assert set(default["platforms"]) == {"天猫", "抖音", "京东", "私域"}
    assert default["platforms"]["私域"]["main_view"] == "场"
    assert default["platforms"]["天猫"]["main_view"] == "人"
    assert len(default["consolidated"]) == 3 * 12  # 3情景 × 12月

    # 新客增速拉满 → 保守情景年化GMV应显著高于默认
    boosted = {"保守": {"new_customers_growth": 0.5}}
    _, boosted_res = _post(base_url + "/api/calc", {"scenarios": boosted})
    base_gmv = sum(r["GMV_主口径"] for r in default["consolidated"] if r["scenario"] == "保守")
    new_gmv = sum(r["GMV_主口径"] for r in boosted_res["consolidated"] if r["scenario"] == "保守")
    assert new_gmv > base_gmv * 1.05


def test_calc_api_rejects_garbage(base_url):
    status, body = _post(base_url + "/api/calc", {"scenarios": {"基准": {"new_customers_growth": "abc"}}})
    data = json.loads(body) if isinstance(body, (bytes,)) else body
    # 非法数值被夹回 0.0 而不是 500
    assert "error" not in data
