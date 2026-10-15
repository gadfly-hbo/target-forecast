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


from _http import get_json_or_error as _get_json, get_raw as _get, post as _post, post_raw as _post_raw


# ---------- 路由表化前的盲区 characterization（阶段3，行为冻结基线） ----------

def test_demo_ignores_malformed_body(base_url):
    # /api/demo 从不读 body：畸形 JSON 仍 200（预读 body 会把它变成 422）
    status, out = _post_raw(base_url + "/api/demo", b"not-json")
    assert status == 200 and out["scenario_id"] == "coupon-demo-001"


def test_import_buckets_route(base_url):
    rows = [{"bucket_min_cents": 6000, "bucket_max_cents": 8999, "avg_amount_cents": 7500,
             "orders": 200, "avg_margin_rate": 0.30},
            {"bucket_min_cents": 9000, "bucket_max_cents": 12999, "avg_amount_cents": 11000,
             "orders": 300, "avg_margin_rate": 0.30}]
    status, out = _post(base_url + "/api/import", {"mode": "buckets", "rows": rows})
    assert status == 200 and out["row_count"] == 2 and out["issues"] == []
    assert set(out["baskets"][0]) == {"amount_cents", "weight", "margin_rate", "label",
                                      "bucket_min_cents", "bucket_max_cents"}


def test_import_orders_route(base_url):
    rows = [{"order_id": "o1", "amount_cents": 9900, "margin_cents": 3000, "refunded": 0}]
    status, out = _post(base_url + "/api/import", {"mode": "orders", "rows": rows})
    assert status == 200 and out["row_count"] == 1


def test_decision_route_validation_and_save(base_url):
    status, out = _post(base_url + "/api/decision", {})
    assert status == 422 and out == {"error": "缺少 run_id"}
    status, out = _post(base_url + "/api/decision",
                        {"run_id": "run-char", "choice": "无券基准", "confirmed_by": "t"})
    assert status == 200 and out["saved"].endswith("run-char.json")


def test_review_list_route(base_url):
    status, out = _get_json(base_url + "/api/review/list")
    assert status == 200 and "reviewed_runs" in out


def test_scenario_not_found_error_body(base_url):
    # 命中 scenario 正则但场景不存在 → 404 且 error 为 store/SpecError 文案（非 "not found"）
    status, out = _get_json(base_url + "/api/scenario/nonexistent-xyz")
    assert status == 404 and out["error"] != "not found"


def test_export_invalid_kind_404(base_url):
    status, out = _get_json(base_url + "/api/export/some-run/bogus")
    assert status == 404 and out == {"error": "not found"}


def test_compare_engine_deep_specerror_no_prefix(base_url):
    # load_spec 过、compare 内部抛（均衡模式缺 scale）→ 外层 catch：422 且无"场景不合法"前缀
    _, demo = _post(base_url + "/api/demo", {})
    scenario = demo["scenario"]
    scenario["objective"] = "balanced"
    scenario["objective_params"] = {}
    status, out = _post(base_url + "/api/compare", {"scenario": scenario})
    assert status == 422
    assert not out["error"].startswith("场景不合法")
    assert "profit_scale" in out["error"]


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


def test_compare_nan_output_rejected_as_422(base_url):
    """阶段1 deliberate-change #5 的负向门禁：引擎产出 NaN/Inf 时由
    allow_nan=False 序列化失败 → 外层 ValueError → 422"请求不合法"，
    而非 200+非法 JSON 体。配方：金额乘积浮点溢出为 inf，ΔΠ=inf-inf=nan。"""
    _, demo = _post(base_url + "/api/demo", {})
    scenario = demo["scenario"]
    scenario["baseline"]["baskets"][0]["amount_cents"] = 2 * 10**306
    status, out = _post(base_url + "/api/compare", {"scenario": scenario})
    assert status == 422
    assert out["error"].startswith("请求不合法")
    assert "not JSON compliant" in out["error"]


# ---------- OverflowError 空洞矩阵（超 float 范围输入不得断连） ----------

def _scenario_with(base_url, mutate):
    _, demo = _post(base_url + "/api/demo", {})
    scenario = demo["scenario"]
    mutate(scenario)
    return scenario


def test_overflow_candidate_threshold_infeasible_row(base_url):
    """候选门槛溢出 → _validate_candidate SpecError → compare 的 per-candidate catch
    → 200 + coupon_legality 不可行行（与 F≥T 同语义；文案禁 float 除法，10**311 亦不炸）。"""
    for huge in (10**309, 10**311):
        sc = _scenario_with(base_url, lambda s: s.__setitem__(
            "candidates", [{"enabled": True, "threshold_cents": huge,
                            "face_value_cents": 500, "label": "溢出门槛"}]))
        status, out = _post(base_url + "/api/compare", {"scenario": sc})
        assert status == 200, out
        row = next(r for r in out["rows"] if r["label"] == "溢出门槛")
        assert row["metrics"] is None
        assert row["violations"][0]["constraint"] == "coupon_legality"
        assert "超出可计算范围" in row["violations"][0]["message"]


def test_overflow_basket_amount_422(base_url):
    sc = _scenario_with(base_url, lambda s: s["baseline"]["baskets"][0].__setitem__("amount_cents", 10**309))
    status, out = _post(base_url + "/api/compare", {"scenario": sc})
    assert status == 422 and "场景不合法" in out["error"] and "超出可计算范围" in out["error"]


def test_overflow_topup_422(base_url):
    sc = _scenario_with(base_url, lambda s: s["baseline"]["baskets"][1].__setitem__("topup_amount_cents", 10**309))
    status, out = _post(base_url + "/api/compare", {"scenario": sc})
    assert status == 422 and "场景不合法" in out["error"]


def test_overflow_new_basket_amount_422(base_url):
    sc = _scenario_with(base_url, lambda s: s["behavior"].__setitem__(
        "new_basket", [{"label": "n", "weight": 1.0, "amount_cents": 10**309, "margin_rate": 0.3, "redeem": 1}]))
    status, out = _post(base_url + "/api/compare", {"scenario": sc})
    assert status == 422 and out["error"].startswith("请求不合法")


def test_overflow_conversion_rate_422(base_url):
    sc = _scenario_with(base_url, lambda s: s["baseline"].__setitem__("conversion_rate", 10**309))
    status, out = _post(base_url + "/api/compare", {"scenario": sc})
    assert status == 422 and "场景不合法" in out["error"]  # load_spec 内 OverflowError → SpecError


def test_overflow_q_table_422(base_url):
    sc = _scenario_with(base_url, lambda s: s["behavior"].update(
        q_mode="table", q_table=[{"q": 10**309}]))
    status, out = _post(base_url + "/api/compare", {"scenario": sc})
    assert status == 422 and out["error"].startswith("请求不合法")  # route_post 兜底


def test_overflow_new_basket_weight_422(base_url):
    sc = _scenario_with(base_url, lambda s: s["behavior"].__setitem__(
        "new_basket", [{"label": "n", "weight": 10**309, "amount_cents": 15900, "margin_rate": 0.3, "redeem": 1}]))
    status, out = _post(base_url + "/api/compare", {"scenario": sc})
    assert status == 422 and out["error"].startswith("请求不合法")  # _check_new_basket 求和溢出→兜底


def test_overflow_import_row_422(base_url):
    rows = [{"bucket_min_cents": 10**309, "bucket_max_cents": 8999, "avg_amount_cents": 7500,
             "orders": 200, "avg_margin_rate": 0.30}]
    status, out = _post(base_url + "/api/import", {"mode": "buckets", "rows": rows})
    assert status == 422 and out["error"].startswith("请求不合法")  # ingest float 强转→兜底
