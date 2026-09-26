# -*- coding: utf-8 -*-
"""提案第七节合成案例：可重跑的黄金场景（非真实经营数据，非行业默认参数）。"""
from __future__ import annotations

from .spec import load_spec, ScenarioSpec

# (label, threshold_cents, face_cents, conversion, merchant_subsidy元, total元, delta元)
GOLDEN_TABLE = [
    ("无券",      None, 0,   0.080000,      0.00, 264000.00,      0.00),
    ("满79减5",   7900,  500,  0.084318,  29896.68, 246773.38, -17226.62),
    ("满99减10",  9900,  1000, 0.086899,  59008.12, 232174.25, -31825.75),
    ("满109减5", 10900,  500,  0.082756,  23183.37, 253945.85, -10054.15),
    ("满129减5", 12900,  500,  0.081819,  14693.72, 263492.01,   -507.99),
    ("满139减5", 13900,  500,  0.081580,  13650.46, 264474.74,    474.74),
    ("满139减10",13900,  1000, 0.084280,  35401.84, 259872.55,  -4127.45),
    ("满139减20",13900,  2000, 0.089546,  89760.54, 232066.22, -31933.78),
    ("满159减5", 15900,  500,  0.080946,   7384.14, 270385.08,   6385.08),
    ("满159减10",15900,  1000, 0.083332,  23136.57, 272769.87,   8769.87),
]

STRESS_GOLDEN = {  # (variant, threshold, face) -> ΔΠ 元
    ("低响应", 15900, 500): 1551.11, ("低响应", 15900, 1000): 234.02,
    ("高响应", 15900, 500): 11219.04, ("高响应", 15900, 1000): 17305.72,
    ("低凑单高流失", 15900, 500): -1976.14, ("低凑单高流失", 15900, 1000): 1651.50,
}


def synthetic_spec_dict() -> dict:
    """提案 7.1 输入：N=100k、C₀=8%、五桶分布、全 30% 毛利、商家全额承担。"""
    return {
        "schema_version": "2.0",
        "scenario_id": "coupon-demo-001",
        "currency": "CNY",
        "observation_unit": "unique_visitor_first_paid_order",
        "window": {"type": "fixed_activity_window", "days": 7},
        "baseline": {
            "visitors": 100000,
            "conversion_rate": 0.08,
            "data_snapshot_id": "synthetic-baskets-v1",
            "baskets": [
                {"amount_cents": 6000, "weight": 0.20, "label": "A=60"},
                {"amount_cents": 9000, "weight": 0.20, "label": "A=90"},
                {"amount_cents": 11000, "weight": 0.30, "label": "A=110"},
                {"amount_cents": 14000, "weight": 0.20, "label": "A=140"},
                {"amount_cents": 19000, "weight": 0.10, "label": "A=190"},
            ],
        },
        "candidates": [
            {"enabled": False, "threshold_cents": None, "face_value_cents": 0, "label": "无券"},
            *[{"enabled": True, "threshold_cents": t, "face_value_cents": f, "label": lb}
              for lb, t, f, *_ in GOLDEN_TABLE if t is not None]
        ],
        "cost": {
            "margin_base_rate": 0.30,
            "margin_addon_rate": 0.30,
            "merchant_share_rho": 1.0,
            "fixed_fee_cents": 0.0,
            "fee_rate": 0.0,
            "fee_basis": "customer_paid",
            "return_adj_cents": 0.0,
            "fixed_activity_cost_cents": 0.0,
        },
        "behavior": {
            "reach_base": 1.0,
            "reach_new": 1.0,
            "redeem_natural": 0.80,
            "redeem_topup": 1.0,
            "churn": 0.02,
            "q_mode": "curve",
            "q_curve": {"q_cap": 0.8, "lam": 2.2, "d_ref": 0.1},
            "conversion": {"mode": "relative", "k": 0.9, "s_max": 0.5},
            "new_basket": [
                {"label": "新增成交", "weight": 1.0, "amount_cents": "at_threshold",
                 "margin_rate": 0.30, "redeem": 1},
            ],
        },
        "constraints": {
            "merchant_coupon_budget_cents": None,
            "min_incremental_contribution_cents": 0.0,
            "allow_controlled_loss": False,
        },
        "objective": "incremental_contribution",
        "evidence_status": "synthetic_assumptions",
        "parameter_sources": {
            "behavior.q_curve": {"source_type": "synthetic_demo", "note": "提案第七节演示参数"},
            "behavior.conversion": {"source_type": "synthetic_demo", "note": "提案第七节演示参数"},
        },
    }


def build_synthetic_spec() -> ScenarioSpec:
    return load_spec(synthetic_spec_dict())

