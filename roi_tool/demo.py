# -*- coding: utf-8 -*-
"""内置合成演示计划集（GRILL G1）：参数为合成假设，非行业真值、非经营建议。"""
from __future__ import annotations

from .engine import evaluate


def build_demo_plans() -> list[dict]:
    return [
        # ① 搜索型：高 CVR 稳赚
        {"name": "天猫直通车-搜索", "spend_cny": 30000, "cpc_cny": 2.5, "cvr": 0.06,
         "aov_cny": 260, "gross_margin": 0.45, "refund_rate": 0.12},
        # ② 信息流：量大利薄、情景敏感
        {"name": "抖音千川-信息流", "spend_cny": 80000, "cpc_cny": 1.2, "cvr": 0.022,
         "aov_cny": 180, "gross_margin": 0.35, "refund_rate": 0.25},
        # ③ 中规中矩：基准情景贴边（net≈0，保守亏挑战赚）
        {"name": "京东快车-站内", "spend_cny": 20000, "cpc_cny": 1.8, "cvr": 0.024,
         "aov_cny": 220, "gross_margin": 0.4, "refund_rate": 0.15},
        # ④ 高客单低 CVR：基准亏、挑战转正（结论随假设翻转）
        {"name": "小红书聚光-种草", "spend_cny": 15000, "cpc_cny": 2.0, "cvr": 0.009,
         "aov_cny": 450, "gross_margin": 0.5, "refund_rate": 0.08},
    ]


def default_scenarios() -> dict[str, dict]:
    return {"保守": {"cvr_growth": -0.2, "aov_growth": -0.2},
            "基准": {"cvr_growth": 0.0, "aov_growth": 0.0},
            "挑战": {"cvr_growth": 0.2, "aov_growth": 0.2}}


def demo_meta() -> dict:
    return {
        "synthetic": True,
        "demo_used": True,
        "note": "演示参数为合成假设，非行业真值、非经营建议。",
    }


def evaluate_demo() -> dict:
    return evaluate(build_demo_plans(), default_scenarios())
