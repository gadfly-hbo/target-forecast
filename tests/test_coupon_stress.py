# -*- coding: utf-8 -*-
"""S3 验收：敏感性与压力情景（提案 §6.2、§7.3 黄金压力表、变体不修改原 spec）。"""
import copy

import pytest

from coupon_tool import build_synthetic_spec, compare, load_spec, stress_test
from coupon_tool.stress import single_factor_variants

TOL = 1  # ±1 分（PRD Testing Decisions）

VARIANTS = {
    "低响应": {"behavior.conversion.k": 0.45},
    "高响应": {"behavior.conversion.k": 1.35},
    "低凑单高流失": {"behavior.q_curve.q_cap": 0.4, "behavior.churn": 0.05},
    "极低响应": {"behavior.conversion.k": 0.25},
}

STRESS_GOLDEN = {  # 提案 7.3：(情景, 券) -> ΔΠ 元
    ("低响应", "满159减5"): 1551.11, ("低响应", "满159减10"): 234.02,
    ("高响应", "满159减5"): 11219.04, ("高响应", "满159减10"): 17305.72,
    ("低凑单高流失", "满159减5"): -1976.14, ("低凑单高流失", "满159减10"): 1651.50,
}


def test_stress_golden_table_reproduced():
    res = stress_test(build_synthetic_spec(), VARIANTS)
    for sc in res.scenarios:
        for row in sc["rows"]:
            key = (sc["name"], row["label"])
            if key in STRESS_GOLDEN:
                assert abs(row["delta_pi_cents"] - STRESS_GOLDEN[key] * 100) <= TOL, key


def test_stress_reports_ranking_change_and_selected_feasibility():
    res = stress_test(build_synthetic_spec(), VARIANTS)
    low = next(sc for sc in res.scenarios if sc["name"] == "低响应")
    assert low["ranking_changed"] is True          # 小面额反超大面额
    assert low["top_label"] == "满159减5"
    extreme = next(sc for sc in res.scenarios if sc["name"] == "极低响应")
    assert extreme["selected_still_feasible"] is False  # 所选方案（满159减10）转为不满足底线


def test_stress_flags_budget_exceeded_per_scenario():
    data = build_synthetic_spec().to_dict()
    data["constraints"]["merchant_coupon_budget_cents"] = 1_000_000
    res = stress_test(load_spec(data), VARIANTS)
    for sc in res.scenarios:
        row = next(r for r in sc["rows"] if r["label"] == "满159减10")
        assert row["budget_exceeded"] is True       # 各情景下均超 10,000 元预算


def test_stress_does_not_mutate_original_spec():
    spec = build_synthetic_spec()
    before = copy.deepcopy(spec.to_dict())
    stress_test(spec, VARIANTS)
    assert spec.to_dict() == before


def test_stress_requires_explicit_variants():
    with pytest.raises(ValueError):
        stress_test(build_synthetic_spec(), {})


def test_single_factor_spread_and_sensitive_param_ranking():
    spec = build_synthetic_spec()
    plan = {
        "behavior.conversion.k": [0.45, 0.9, 1.35],
        "behavior.q_curve.q_cap": [0.4, 0.8],
        "cost.return_adj_cents": [0, 10],
    }
    res = stress_test(spec, single_factor_variants(spec, plan))
    spreads = {p["param"]: p["delta_pi_spread_cents"] for p in res.sensitive_params}
    assert spreads["behavior.conversion.k"] > 0
    assert spreads["behavior.q_curve.q_cap"] > 0
    assert spreads["cost.return_adj_cents"] > 0
    # 按影响幅度降序排列
    values = [p["delta_pi_spread_cents"] for p in res.sensitive_params]
    assert values == sorted(values, reverse=True)
