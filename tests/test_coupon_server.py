# -*- coding: utf-8 -*-
"""S7 验收：工作台 API 冒烟——静态页、状态、演示场景、比较、敏感性、封存导出、决策（13.2 路径）。"""
import json
import threading
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer

import pytest

from coupon_tool import server as coupon_server


@pytest.fixture(scope="module")
def base_url(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("coupon_wb")
    app = coupon_server.Workbench(data_dir=str(tmp / "data"), out_dir=str(tmp / "out"),
                                  templates_dir=str(tmp / "tpl"))
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), coupon_server.make_handler(app))
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


def test_static_pages(base_url):
    status, html = _get(base_url + "/")
    assert status == 200 and "优惠券测算工作台" in html.decode()
    assert "数据与基准" in html.decode() and "历史与复盘" in html.decode()
    status, css = _get(base_url + "/style.css")
    assert status == 200 and "Xanthil" in css.decode()
    status, js = _get(base_url + "/app.js")
    assert status == 200 and "runComparison" not in js.decode()  # 旧名不再存在
    assert "api/compare" in js.decode()


def test_state_and_demo(base_url):
    status, body = _get(base_url + "/api/state")
    state = json.loads(body)
    assert state["engine_version"]
    assert "本机运行" in state["boundary"]
    status, demo = _post(base_url + "/api/demo", {})
    assert status == 200 and demo["scenario_id"] == "coupon-demo-001"
    assert demo["validation"]["errors"] == []
    # 场景可读回
    status, body = _get(base_url + "/api/scenario/coupon-demo-001")
    assert status == 200 and json.loads(body)["baseline"]["visitors"] == 100000


def test_compare_rejects_invalid_and_matches_golden(base_url):
    bad = {"scenario_id": "x", "baseline": {"visitors": 10, "conversion_rate": 0.5,
                                            "baskets": []}}
    status, out = _post(base_url + "/api/compare", {"scenario": bad})
    assert status == 422 and "error" in out          # 不合法输入被拒，不静默出结果
    _, demo = _post(base_url + "/api/demo", {})
    status, cmp_ = _post(base_url + "/api/compare", {"scenario": demo["scenario"]})
    assert status == 200
    assert cmp_["ranking"][0] == "满159减10"          # 与黄金一致
    row = next(r for r in cmp_["rows"] if r["label"] == "满159减10")
    assert abs(row["metrics"]["incremental_contribution_cents"] - 876_987) <= 100
    assert cmp_["conclusion"]["type"] == "needs_validation"
    assert row["ledger"]                              # 账本随行


def test_stress_requires_variants(base_url):
    _, demo = _post(base_url + "/api/demo", {})
    status, out = _post(base_url + "/api/stress", {"scenario": demo["scenario"], "variants": {}})
    assert status == 422
    status, out = _post(base_url + "/api/stress",
                        {"scenario": demo["scenario"],
                         "variants": {"低响应": {"behavior.conversion.k": 0.45}}})
    assert status == 200 and out["scenarios"][0]["name"] == "低响应"


def test_run_records_decision_and_exports(base_url, tmp_path):
    _, demo = _post(base_url + "/api/demo", {})
    decision = {"choice": "满159减10", "reason": "验证黄金场景", "confirmed_by": "tester"}
    status, out = _post(base_url + "/api/run",
                        {"scenario": demo["scenario"], "with_stress": True,
                         "variants": {"低响应": {"behavior.conversion.k": 0.45}},
                         "decision": decision})
    assert status == 200 and out["run_id"].startswith("run-")
    rid = out["run_id"]
    status, body = _get(base_url + f"/api/export/{rid}/markdown")
    assert status == 200 and "满159减10" in body.decode() and rid in body.decode()
    status, body = _get(base_url + f"/api/export/{rid}/csv_candidates")
    assert status == 200 and "增量贡献分" in body.decode("utf-8-sig")
    status, body = _get(base_url + f"/api/export/{rid}/json")
    assert status == 200 and json.loads(body)["decision"]["choice"] == "满159减10"
    # 运行清单可见
    status, body = _get(base_url + "/api/runs")
    assert rid in [r["run_id"] for r in json.loads(body)]


def test_templates_endpoint(base_url):
    status, body = _get(base_url + "/api/templates")
    out = json.loads(body)
    assert status == 200 and len(out["files"]) == 2


def test_review_endpoint_closes_loop(base_url):
    _, demo = _post(base_url + "/api/demo", {})
    decision = {"choice": "满159减10", "reason": "复盘路径测试", "confirmed_by": "tester"}
    _, out = _post(base_url + "/api/run", {"scenario": demo["scenario"], "with_stress": False,
                                           "decision": decision})
    rid = out["run_id"]
    status, res = _post(base_url + "/api/review", {
        "run_id": rid,
        "actuals": {"orders": 8400, "gmv_pre_cents": 13_200_000, "gmv_paid_cents": 11_000_000,
                    "merchant_subsidy_cents": 2_280_000, "redemptions": 5300,
                    "window": "2026-10-01~07", "refund_handling": "net"},
        "notes": {"加购/流失假设偏差": "凑单弱于预期"},
        "params_patch": {"behavior.conversion.k": 1.2},
        "confirmed_by": "运营A",
    })
    assert status == 200
    rv = res["review"]
    assert rv["diffs"] and rv["causal_claim"] is False
    new_id = rv["parameter_new_version"]["scenario_id"]
    status, body = _get(base_url + "/api/scenario/" + new_id)
    assert status == 200 and json.loads(body)["behavior"]["conversion"]["k"] == 1.2
    # 缺字段被拒
    status, res2 = _post(base_url + "/api/review", {"run_id": rid, "actuals": {}, "notes": {}})
    assert status == 422
