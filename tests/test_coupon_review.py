# -*- coding: utf-8 -*-
"""S8 验收：复盘闭环（提案 §9.2/9.3、门禁 D）——预测vs实际、偏差分类、参数新版本不覆盖。"""
import json

import pytest

from coupon_tool import compare
from coupon_tool.review import DEVIATION_CATEGORIES, create_review
from coupon_tool.storage import Store
from coupon_tool.synthetic import build_synthetic_spec


@pytest.fixture()
def store_run(tmp_path):
    store = Store(str(tmp_path / "data"))
    spec = build_synthetic_spec()
    store.save_spec(spec)
    run = store.record_run(spec, compare(spec))
    return store, run


def _actuals(**over):
    base = {"orders": 8400.0, "gmv_pre_cents": 13_200_000.0, "gmv_paid_cents": 11_000_000.0,
            "merchant_subsidy_cents": 2_280_000.0, "redemptions": 5300.0,
            "window": "2026-10-01~2026-10-07", "refund_handling": "net"}
    base.update(over)
    return base


def test_review_compares_predicted_vs_actual(store_run):
    store, run = store_run
    review = create_review(store, run["run_id"], _actuals(),
                           notes={"流量偏差": "UV 高 3%"}, confirmed_by="运营A")
    top = run["results"]["ranking_rows"][0]
    assert review["selected_label"] == top["label"]
    diffs = {d["metric"]: d for d in review["diffs"]}
    assert "orders" in diffs and "merchant_subsidy_cents" in diffs
    pred_orders = top["metrics"]["orders"]
    assert diffs["orders"]["predicted"] == pytest.approx(pred_orders)
    assert diffs["orders"]["actual"] == 8400.0
    assert review["caliber_checks"] == []          # 已声明退款口径
    # 未声明退款口径 → 口径核查提示（先核对口径再比较）
    r2 = create_review(store, run["run_id"], _actuals(refund_handling=None),
                       notes={}, confirmed_by="运营A")
    assert any("退款" in c for c in r2["caliber_checks"])
    assert review["deviation_notes"]["流量偏差"] == "UV 高 3%"
    assert review["confirmed_by"] == "运营A"
    assert review["causal_claim"] is False          # 描述性对比，非因果结论


def test_review_requires_complete_actuals(store_run):
    store, run = store_run
    bad = _actuals()
    bad.pop("orders")
    with pytest.raises(ValueError) as ei:
        create_review(store, run["run_id"], bad, notes={}, confirmed_by="x")
    assert "orders" in str(ei.value)
    bad2 = _actuals(orders=-5)
    with pytest.raises(ValueError):
        create_review(store, run["run_id"], bad2, notes={}, confirmed_by="x")


def test_parameter_new_version_without_overwrite(store_run):
    store, run = store_run
    original = json.load(open(f"{store.root}/scenarios/coupon-demo-001.json", encoding="utf-8"))
    review = create_review(store, run["run_id"], _actuals(),
                           notes={"加购/流失假设偏差": "凑单弱于预期"},
                           params_patch={"behavior.conversion.k": 1.2},
                           confirmed_by="运营A")
    new_id = review["parameter_new_version"]["scenario_id"]
    assert new_id != "coupon-demo-001"
    new_spec = store.load_spec(new_id)
    assert new_spec.behavior.conversion["k"] == 1.2
    after = json.load(open(f"{store.root}/scenarios/coupon-demo-001.json", encoding="utf-8"))
    assert after == original                          # 旧版本不变
    # 原运行场景未被改写
    assert store.load_run(run["run_id"])["scenario"]["behavior"]["conversion"]["k"] == 0.9


def test_review_record_persisted(store_run):
    store, run = store_run
    review = create_review(store, run["run_id"], _actuals(), notes={}, confirmed_by="A")
    saved = json.load(open(f"{store.root}/reviews/{run['run_id']}.json", encoding="utf-8"))
    assert saved["review_id"] == review["review_id"]
    assert set(DEVIATION_CATEGORIES) >= {"流量偏差", "未识别剩余差异"}


def test_review_uses_human_decision_not_ranking_first(store_run):
    """§8.3：人工选择不要求与排序第一一致——复盘预测基准应来自被确认的方案。"""
    store, run = store_run
    decision = {"choice": "满159减5", "reason": "预算考虑", "confirmed_by": "运营B"}
    store.save_decision(run["run_id"], decision)
    review = create_review(store, run["run_id"], _actuals(), notes={}, confirmed_by="运营B")
    assert review["selected_label"] == "满159减5"       # 不是排序第一的 满159减10
    assert review["chosen_source"] == "decision"
    sel_row = next(r for r in run["results"]["rows"] if r["label"] == "满159减5")
    assert review["predicted"]["orders"] == pytest.approx(sel_row["metrics"]["orders"])


def test_review_explicit_label_overrides_decision(store_run):
    store, run = store_run
    store.save_decision(run["run_id"], {"choice": "满159减5"})
    review = create_review(store, run["run_id"], _actuals(), notes={},
                           confirmed_by="x", chosen_label="满139减5")
    assert review["selected_label"] == "满139减5"
    assert review["chosen_source"] == "explicit"


def test_review_decision_no_coupon_uses_baseline_row(store_run):
    store, run = store_run
    store.save_decision(run["run_id"], {"choice": "暂不发券"})
    review = create_review(store, run["run_id"], _actuals(), notes={}, confirmed_by="x")
    assert review["selected_label"] == "无券"


def test_review_no_coupon_decision_with_custom_label(store_run):
    """无券行按 enabled=False 识别：自定义标签（如“不发券”）下“暂不发券”仍取无券基准。"""
    import copy as _copy
    store, run = store_run
    data = _copy.deepcopy(run["scenario"])
    for cand in data["candidates"]:
        if not cand.get("enabled"):
            cand["label"] = "不发券"
    from coupon_tool import load_spec, compare as _compare
    spec2 = load_spec(data)
    run2 = store.record_run(spec2, _compare(spec2))
    store.save_decision(run2["run_id"], {"choice": "暂不发券"})
    review = create_review(store, run2["run_id"], _actuals(), notes={}, confirmed_by="x")
    assert review["selected_label"] == "不发券"
    assert review["predicted"]["merchant_subsidy_cents"] == 0
