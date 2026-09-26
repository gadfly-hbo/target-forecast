# -*- coding: utf-8 -*-
"""敏感性与压力情景（提案 §6.2）：变体显式给定，输出 ΔΠ / 预算 / 排序变化 / 最敏感参数。

不内置 ±20%——参数变化范围由用户指定或来自可说明估计。
"""
from __future__ import annotations

import copy
from dataclasses import dataclass

from .spec import ScenarioSpec, load_spec
from .compare import compare
from .engine import simulate


@dataclass
class SensitivityResult:
    baseline: dict
    scenarios: list
    single_factor: list
    sensitive_params: list


def _set_path(data: dict, path: str, value):
    keys = path.split(".")
    node = data
    for k in keys[:-1]:
        node = node[k]
    node[keys[-1]] = value


def _variant_spec(spec: ScenarioSpec, changes: dict) -> ScenarioSpec:
    data = copy.deepcopy(spec.to_dict())
    for path, value in changes.items():
        _set_path(data, path, value)
    return load_spec(data)


def single_factor_variants(spec: ScenarioSpec, plan: dict) -> dict:
    """把 {参数路径: [取值列表]} 展开为单因素命名变体（每参数每取值一个情景）。"""
    variants: dict[str, dict] = {}
    for param, values in plan.items():
        for i, value in enumerate(values, start=1):
            variants[f"{param}#{i}"] = {param: value}
    return variants


def stress_test(spec: ScenarioSpec, variants: dict) -> SensitivityResult:
    """对显式变体逐情景重跑 compare；变体不修改原 spec。"""
    if not variants:
        raise ValueError("无情景变体：敏感性范围必须由用户显式指定（不内置 ±20%）")

    base = compare(spec)
    base_order = [r["label"] for r in base.ranking]
    selected = base.ranking[0]["label"] if base.ranking else None
    baseline = {
        "selected_label": selected,
        "top_label": base.ranking[0]["label"] if base.ranking else None,
        "delta_pi_cents": {r["label"]: r["metrics"]["incremental_contribution_cents"]
                           for r in base.rows if r["metrics"]},
        "conclusion": base.conclusion,
    }

    scenarios = []
    for name, changes in variants.items():
        spec_v = _variant_spec(spec, changes)
        budget_v = spec_v.constraints.merchant_coupon_budget_cents
        cmp_v = compare(spec_v)
        order = [r["label"] for r in cmp_v.ranking]
        rows = []
        for r in cmp_v.rows:
            if r["metrics"] is None:
                continue
            rows.append({
                "label": r["label"],
                "delta_pi_cents": r["metrics"]["incremental_contribution_cents"],
                "merchant_subsidy_cents": r["metrics"]["merchant_subsidy_cents"],
                "budget_exceeded": (budget_v is not None
                                    and r["metrics"]["merchant_subsidy_cents"] > budget_v),
                "feasible": r["feasible"],
                "conversion_rate": r["metrics"]["conversion_rate"],
            })
        selected_row = next((r for r in rows if r["label"] == selected), None)
        scenarios.append({
            "name": name,
            "changes": changes,
            "rows": rows,
            "ranking_changed": order != base_order,
            "top_label": order[0] if order else None,
            "selected_still_feasible": bool(selected_row and selected_row["feasible"]),
        })

    # 单因素敏感度：同一参数的取值之间 ΔΠ（所选候选）极差
    by_param: dict[str, list[float]] = {}
    for sc in scenarios:
        param = sc["name"].rsplit("#", 1)[0]
        row = next((r for r in sc["rows"] if r["label"] == selected), None) if selected else None
        if row:
            by_param.setdefault(param, []).append(row["delta_pi_cents"])
    if selected and selected in baseline["delta_pi_cents"]:
        for param, vals in list(by_param.items()):
            vals.append(baseline["delta_pi_cents"][selected])
    single_factor = [
        {"param": param, "delta_pi_values_cents": vals,
         "delta_pi_spread_cents": max(vals) - min(vals)}
        for param, vals in by_param.items()
    ]
    sensitive_params = sorted(single_factor, key=lambda p: -p["delta_pi_spread_cents"])

    return SensitivityResult(baseline=baseline, scenarios=scenarios,
                             single_factor=single_factor,
                             sensitive_params=sensitive_params)
