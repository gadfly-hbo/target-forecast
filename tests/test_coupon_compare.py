# -*- coding: utf-8 -*-
"""S2 验收：候选比较、约束过滤、四类结论、邻近方案、盈亏平衡（提案 §五、§6.1、M09-M12/M18/M19）。"""
import pytest

from coupon_tool import build_synthetic_spec, compare, load_spec, simulate
from coupon_tool.compare import generate_candidates


def _spec_with_budget(budget_cents):
    data = build_synthetic_spec().to_dict()
    data["constraints"]["merchant_coupon_budget_cents"] = budget_cents
    return load_spec(data)


def test_ranking_profit_mode_matches_golden_order():
    res = compare(build_synthetic_spec())
    ranked = [r["label"] for r in res.ranking]
    assert ranked[0] == "满159减10"          # 黄金 ΔΠ 最高
    assert "无券" in ranked                   # 无券参与排序（ΔΠ=0）


def test_budget_filters_without_truncating_costs():  # M18 + 提案 7.2 预算示例
    res = compare(_spec_with_budget(1_000_000))       # 10,000 元
    by_label = {r["label"]: r for r in res.rows}
    big = by_label["满159减10"]
    small = by_label["满159减5"]
    assert not big["feasible"]
    assert any(v["constraint"] == "merchant_coupon_budget" for v in big["violations"])
    assert big["metrics"]["merchant_subsidy_cents"] == pytest.approx(2_313_657, abs=2)  # 未截断
    assert big["metrics"]["incremental_contribution_cents"] == pytest.approx(876_987, abs=2)
    assert small["feasible"]
    assert res.ranking[0]["label"] == "满159减5"       # 预算改变选择
    # 被过滤候选不消失且带原因
    assert any(nb["label"] == "满159减10" and nb["filtered_reason"]
               for nb in small["neighbors"])


def test_m19_all_coupons_infeasible_returns_no_coupon_conclusion():
    res = compare(_spec_with_budget(100_000))          # 预算紧到所有券都超
    assert res.conclusion["type"] == "no_feasible_coupon"
    assert not any(r["feasible"] and r["candidate"]["enabled"] for r in res.rows)
    assert any(not r["candidate"]["enabled"] for r in res.rows)   # 无券仍展示


def test_no_feasible_at_all_when_no_coupon_also_fails_target():
    data = build_synthetic_spec().to_dict()
    data["constraints"]["min_conversion_rate"] = 0.09   # 无任何候选可达
    res = compare(load_spec(data))
    assert res.conclusion["type"] == "no_feasible_coupon"
    assert "无可行解" in res.conclusion["message"]       # 无券也不满足业务目标


def test_m09_lower_addon_margin_never_raises_topup_contribution():
    hi = build_synthetic_spec()
    data = hi.to_dict()
    data["cost"]["margin_addon_rate"] = 0.10
    lo = load_spec(data)
    r_hi = simulate(hi, {"enabled": True, "threshold_cents": 15900, "face_value_cents": 500})
    r_lo = simulate(lo, {"enabled": True, "threshold_cents": 15900, "face_value_cents": 500})
    assert r_lo.decomposition["topup"] < r_hi.decomposition["topup"]
    assert r_lo.metrics["incremental_contribution_cents"] < r_hi.metrics["incremental_contribution_cents"]


def test_m10_no_natural_hit_still_computes_topup():
    res = simulate(build_synthetic_spec(),
                   {"enabled": True, "threshold_cents": 20000, "face_value_cents": 500})
    assert res.metrics["natural_redemptions"] == 0
    assert res.metrics["topup_redemptions"] > 0          # 未退化为无券
    assert res.metrics["incremental_contribution_cents"] != 0


def test_m12_roi_not_applicable_when_no_merchant_subsidy():
    res = compare(build_synthetic_spec())
    by_label = {r["label"]: r for r in res.rows}
    assert by_label["无券"]["metrics"]["roi"] is None
    data = build_synthetic_spec().to_dict()
    data["cost"]["merchant_share_rho"] = 0.0
    for row in compare(load_spec(data)).rows:
        assert row["metrics"]["roi"] is None             # 不除零、不伪造无限收益


def test_conversion_priority_respects_profit_floor():
    data = build_synthetic_spec().to_dict()
    data["objective"] = "conversion"
    res = compare(load_spec(data))
    assert res.ranking[0]["label"] == "满159减10"          # 可行集中转化最高
    assert res.ranking[0]["metrics"]["incremental_contribution_cents"] >= 0


def test_balanced_mode_pareto_front():
    data = build_synthetic_spec().to_dict()
    data["objective"] = "balanced"
    data["objective_params"] = {"w_profit": 0.5, "w_conversion": 0.5,
                                "profit_scale": 10_000_000, "conversion_scale": 0.01}
    res = compare(load_spec(data))
    pareto_labels = {r["label"] for r in res.pareto}
    # §5.2：可行方案的非支配集合——159减10 支配其余全部可行候选
    assert pareto_labels == {"满159减10"}


def test_balanced_mode_requires_explicit_scales():
    from coupon_tool.spec import SpecError
    data = build_synthetic_spec().to_dict()
    data["objective"] = "balanced"
    data["objective_params"] = {}
    with pytest.raises(SpecError, match="显式提供"):
        compare(load_spec(data))


def test_balanced_scales_stable_against_extreme_candidate():
    """尺度固定存入场景：增删极端候选不改变其余候选 Score（§5.2）。"""
    data = build_synthetic_spec().to_dict()
    data["objective"] = "balanced"
    data["objective_params"] = {"w_profit": 0.5, "w_conversion": 0.5,
                                "profit_scale": 10_000_000, "conversion_scale": 0.01}
    base = {r["label"]: r.get("score") for r in compare(load_spec(data)).ranking}
    data["candidates"].append({"enabled": True, "threshold_cents": 15900,
                               "face_value_cents": 3000, "label": "满159减30"})
    extended = {r["label"]: r.get("score") for r in compare(load_spec(data)).ranking}
    for label, score in base.items():
        if score is not None:
            assert extended[label] == pytest.approx(score)


def test_conclusion_needs_validation_for_synthetic_evidence():
    res = compare(build_synthetic_spec())
    assert res.conclusion["type"] == "needs_validation"    # 证据状态=合成假设
    assert res.conclusion["evidence_status"] == "synthetic_assumptions"


def test_invalid_candidates_reported_not_silent():
    data = build_synthetic_spec().to_dict()
    data["candidates"] = [
        {"enabled": False, "threshold_cents": None, "face_value_cents": 0, "label": "无券"},
        {"enabled": True, "threshold_cents": 500, "face_value_cents": 500, "label": "F=T"},
    ]
    res = compare(load_spec(data))
    bad = next(r for r in res.rows if r["label"] == "F=T")
    assert not bad["feasible"]
    assert any("0 < F < T" in v["message"] for v in bad["violations"])


def test_all_rows_invalid_yields_invalid_comparison():
    data = build_synthetic_spec().to_dict()
    data["candidates"] = [{"enabled": True, "threshold_cents": 500, "face_value_cents": 600}]
    res = compare(load_spec(data))
    assert res.conclusion["type"] == "invalid_comparison"


def test_breakeven_for_top_candidate():
    res = compare(build_synthetic_spec())
    be = next(r for r in res.rows if r["label"] == "满159减5")["breakeven"]
    # 手算（黄金值推导）：π̄_new=4270 分；Π_base_after=26,071,715.55 分
    # ΔC⁺_BE = (26,400,000 − 26,071,715.55) / (100,000×4270) ≈ 0.0007686
    assert be["pi_new_avg_cents"] == pytest.approx(4270, abs=1)
    assert be["d_c_plus_be"] == pytest.approx(0.000769, abs=2e-5)
    assert be["c_be"] == pytest.approx(0.079441, abs=2e-5)
    assert be["within_reachable_cap"] is True
    assert be["budget_ok_at_be"] is True                   # 该新增量的商家券补在预算内
    assert be["nonpositive_pi_new"] is False


def test_breakeven_budget_recheck_uses_resimulated_subsidy():
    res = compare(_spec_with_budget(1_000_000))
    be = res.ranking[0]["breakeven"]                       # 满159减5
    assert be["merchant_subsidy_at_be_cents"] < 1_000_000


def test_generate_candidates_quantile_anchored():
    data = build_synthetic_spec().to_dict()
    data["candidates"] = []
    spec = load_spec(data)
    cands = generate_candidates(spec)
    thresholds = sorted({c["threshold_cents"] for c in cands if c["enabled"]})
    assert 9000 in thresholds and 11000 in thresholds and 14000 in thresholds  # P40/P50/P75
    assert all(c["face_value_cents"] % 100 == 0 for c in cands if c["enabled"])  # 取整到元
    assert any(not c["enabled"] for c in cands)            # 无券候选始终在
    # 超出历史支持范围的门槛标注外推
    assert all(c.get("extrapolated") for c in cands
               if c["enabled"] and c["threshold_cents"] > 19000)


def test_neighbors_visible_for_selected():
    res = compare(build_synthetic_spec())
    row = next(r for r in res.rows if r["label"] == "满159减5")
    labels = [nb["label"] for nb in row["neighbors"]]
    assert "满159减10" in labels and "满139减5" in labels
