# -*- coding: utf-8 -*-
"""L3 决策层：候选生成、约束过滤、模式排序、四类结论、邻近方案与盈亏平衡（提案 §五、§6.1）。

预算是预估与过滤约束：超限候选标不可行并保留原始数值，绝不截断成本后保留收益。
"""
from __future__ import annotations

from dataclasses import dataclass

from .spec import ScenarioSpec, SpecError, validate_spec, load_spec
from .engine import simulate

QUANTILES = (0.40, 0.50, 0.60, 0.70, 0.75)
FT_GRID = (0.03, 0.05, 0.08, 0.12, 0.15)


@dataclass
class ComparisonResult:
    rows: list
    ranking: list
    pareto: list
    conclusion: dict
    objective: str


def _round_yuan_cents(ratio_cents: float) -> int:
    return int(ratio_cents / 100.0 + 0.5) * 100  # 取整到元，四舍五入


def _weighted_quantile_amounts(spec: ScenarioSpec) -> list[int]:
    baskets = sorted(spec.baseline.baskets, key=lambda b: b.amount_cents)
    out, cum = [], 0.0
    for q in QUANTILES:
        acc = 0.0
        for bk in baskets:
            acc += bk.weight
            if acc >= q - 1e-12:
                out.append(bk.amount_cents)
                break
        else:
            out.append(baskets[-1].amount_cents)
    return out


def generate_candidates(spec: ScenarioSpec) -> list[dict]:
    """分位数锚定 + F/T 档位生成候选，与人工候选合并去重，始终包含无券候选。"""
    manual = list(spec.candidates)
    generated: list[dict] = []
    if spec.baseline.baskets:
        max_amount = max(b.amount_cents for b in spec.baseline.baskets)
        for t in sorted(set(_weighted_quantile_amounts(spec))):
            for ratio in FT_GRID:
                f = _round_yuan_cents(t * ratio)
                if 0 < f < t:
                    generated.append({
                        "enabled": True, "threshold_cents": t, "face_value_cents": f,
                        "label": f"满{t // 100}减{f // 100}",
                        "extrapolated": t > max_amount,
                        "origin": "quantile",
                    })
    merged: dict[tuple, dict] = {}
    for cand in generated:
        key = (cand["threshold_cents"], cand["face_value_cents"])
        merged.setdefault(key, cand)
    for cand in manual:
        if not cand.get("enabled", True):
            merged[("none", 0)] = dict(cand)
            continue
        key = (cand["threshold_cents"], cand["face_value_cents"])
        if key in merged:
            kept = dict(cand)
            kept["extrapolated"] = merged[key].get("extrapolated", False)
            kept.setdefault("origin", "manual")
            merged[key] = kept
        else:
            entry = dict(cand)
            entry.setdefault("label", f"满{cand['threshold_cents'] // 100}减{cand['face_value_cents'] // 100}")
            entry["extrapolated"] = (cand["threshold_cents"]
                                     > max((b.amount_cents for b in spec.baseline.baskets), default=0))
            entry.setdefault("origin", "manual")
            merged[key] = entry
    if ("none", 0) not in merged:
        merged[("none", 0)] = {"enabled": False, "threshold_cents": None,
                               "face_value_cents": 0, "label": "无券", "origin": "baseline"}
    rows = list(merged.values())
    enabled = sorted([r for r in rows if r.get("enabled")],
                     key=lambda r: (r["threshold_cents"], r["face_value_cents"]))
    disabled = [r for r in rows if not r.get("enabled")]
    return disabled + enabled


def _check_constraints(spec: ScenarioSpec, cand: dict, metrics: dict) -> tuple[list, bool]:
    cons = spec.constraints
    violations = []
    controlled_loss = False
    if not cand.get("enabled"):
        floor = 0.0
    else:
        floor = cons.min_incremental_contribution_cents
        if cons.allow_controlled_loss:
            floor = -(cons.max_loss_cents or 0.0)
    delta_pi = metrics["incremental_contribution_cents"]
    if delta_pi < floor - 1e-6:
        violations.append({
            "constraint": "incremental_contribution",
            "message": f"增量贡献 {delta_pi / 100:.2f} 元低于底线 {floor / 100:.2f} 元",
        })
    elif cand.get("enabled") and delta_pi < 0:
        controlled_loss = True  # 受控亏损被启用且在额度内：保留醒目标记
    if (cons.merchant_coupon_budget_cents is not None
            and metrics["merchant_subsidy_cents"] > cons.merchant_coupon_budget_cents + 1e-6):
        violations.append({
            "constraint": "merchant_coupon_budget",
            "message": (f"商家券补 {metrics['merchant_subsidy_cents'] / 100:.2f} 元 "
                        f"超预算 {cons.merchant_coupon_budget_cents / 100:.2f} 元（预估过滤，非投放限额）"),
        })
    if cons.min_conversion_rate is not None and metrics["conversion_rate"] < cons.min_conversion_rate:
        violations.append({
            "constraint": "min_conversion_rate",
            "message": f"转化率 {metrics['conversion_rate']:.4%} 低于目标 {cons.min_conversion_rate:.4%}",
        })
    if cons.min_delta_c is not None and metrics["delta_c"] < cons.min_delta_c:
        violations.append({
            "constraint": "min_delta_c",
            "message": f"净转化变化 {metrics['delta_c']:.4%} 低于目标 {cons.min_delta_c:.4%}",
        })
    if (cons.min_gmv_pre_cents is not None
            and metrics["gmv_pre_cents"] < cons.min_gmv_pre_cents):
        violations.append({
            "constraint": "min_gmv_pre",
            "message": f"券前 GMV {metrics['gmv_pre_cents'] / 100:.2f} 元低于目标 "
                       f"{cons.min_gmv_pre_cents / 100:.2f} 元",
        })
    if (cons.min_avg_contribution_cents is not None and metrics["avg_contribution_cents"] is not None
            and metrics["avg_contribution_cents"] < cons.min_avg_contribution_cents):
        violations.append({
            "constraint": "min_avg_contribution",
            "message": f"单均贡献 {metrics['avg_contribution_cents'] / 100:.2f} 元低于底线 "
                       f"{cons.min_avg_contribution_cents / 100:.2f} 元",
        })
    if (cons.max_ft_ratio is not None and cand.get("enabled")
            and cand["face_value_cents"] / cand["threshold_cents"] > cons.max_ft_ratio):
        violations.append({
            "constraint": "max_ft_ratio",
            "message": (f"F/T={cand['face_value_cents'] / cand['threshold_cents']:.2%} "
                        f"超过业务折扣上限 {cons.max_ft_ratio:.2%}（业务规则，非套利证明）"),
        })
    return violations, controlled_loss


def _breakeven(spec: ScenarioSpec, cand: dict, row: dict) -> dict:
    """提案 6.1：回本所需毛新增成交率及其预算复核（复用主循环测算结果）。"""
    n = spec.baseline.visitors if spec.baseline.visitors is not None else 1
    c0 = spec.baseline.conversion_rate
    h, c = spec.behavior, spec.cost
    t, f = cand["threshold_cents"], cand["face_value_cents"]

    def _pi_new(nb: dict) -> float:
        amt = t if nb.get("amount_cents", "at_threshold") == "at_threshold" else nb["amount_cents"]
        m_j = nb.get("margin_rate", c.margin_base_rate)
        paid = amt - int(nb["redeem"]) * f
        v_fee = c.fixed_fee_cents + (c.fee_rate * paid if c.fee_basis == "customer_paid" else c.fee_rate * amt)
        return amt * m_j - int(nb["redeem"]) * c.merchant_share_rho * f - v_fee - c.return_adj_cents

    pi_new_avg = sum(float(nb["weight"]) * _pi_new(nb) for nb in h.new_basket)
    k = c.fixed_activity_cost_cents
    pi_base_after = row["metrics"]["total_contribution_cents"] - row["decomposition"]["new_orders"] + k
    pi0 = row["metrics"]["baseline_contribution_cents"]
    nonpositive = pi_new_avg <= 0
    if nonpositive:
        return {"pi_new_avg_cents": pi_new_avg, "nonpositive_pi_new": True,
                "note": "新增成交单均贡献非正，无法靠增加新增成交回本，需改变券或成本结构"}
    d_be = max(0.0, (pi0 + k - pi_base_after) / (n * pi_new_avg))
    retention = row["metrics"]["retention"]
    c_be = c0 * retention + d_be
    # 与 §4.4 ΔC⁺ 上限同式（可触达非购买者比例），比 1−C₀R 更保守、口径一致
    reachable_cap = (1.0 - c0) * float(h.reach_new)
    within = d_be <= reachable_cap + 1e-12

    # 在 ΔC⁺=BE 处重算商家券补并复核预算（结构不变假设）
    data = spec.to_dict()
    data["behavior"]["conversion"] = {"mode": "absolute", "delta_c_plus": d_be}
    subsidy_at_be, budget_ok = None, True
    try:
        res_be = simulate(load_spec(data), cand)
        subsidy_at_be = res_be.metrics["merchant_subsidy_cents"]
        budget = spec.constraints.merchant_coupon_budget_cents
        if budget is not None and subsidy_at_be > budget:
            budget_ok = False
    except SpecError:
        budget_ok = False
    return {
        "pi_new_avg_cents": pi_new_avg,
        "nonpositive_pi_new": False,
        "d_c_plus_be": d_be,
        "c_be": c_be,
        "delta_c_be": c_be - c0,
        "reachable_cap": reachable_cap,
        "within_reachable_cap": within,
        "merchant_subsidy_at_be_cents": subsidy_at_be,
        "budget_ok_at_be": budget_ok,
        "note": None if within else "回本所需新增超过可触达非购买者上限：当前假设下不可回本",
    }


def _neighbors(rows: list) -> None:
    enabled_rows = [r for r in rows if r["candidate"].get("enabled") and r.get("metrics")]
    for row in enabled_rows:
        cand = row["candidate"]
        t, f = cand["threshold_cents"], cand["face_value_cents"]
        same_f = [r for r in enabled_rows if r is not row
                  and r["candidate"]["face_value_cents"] == f]
        same_t = [r for r in enabled_rows if r is not row
                  and r["candidate"]["threshold_cents"] == t]
        picked = []
        below = sorted((r for r in same_f if r["candidate"]["threshold_cents"] < t),
                       key=lambda r: -r["candidate"]["threshold_cents"])
        above = sorted((r for r in same_f if r["candidate"]["threshold_cents"] > t),
                       key=lambda r: r["candidate"]["threshold_cents"])
        less = sorted((r for r in same_t if r["candidate"]["face_value_cents"] < f),
                      key=lambda r: -r["candidate"]["face_value_cents"])
        more = sorted((r for r in same_t if r["candidate"]["face_value_cents"] > f),
                      key=lambda r: r["candidate"]["face_value_cents"])
        for group in (below[:1], above[:1], less[:1], more[:1]):
            picked.extend(group)
        row["neighbors"] = [{
            "label": nb["label"],
            "threshold_cents": nb["candidate"]["threshold_cents"],
            "face_value_cents": nb["candidate"]["face_value_cents"],
            "feasible": nb["feasible"],
            "filtered_reason": "；".join(v["message"] for v in nb["violations"]) or None,
        } for nb in picked]


def _dominates(a: dict, b: dict) -> bool:
    da, db = a["metrics"], b["metrics"]
    return (da["incremental_contribution_cents"] >= db["incremental_contribution_cents"]
            and da["delta_c"] >= db["delta_c"]
            and (da["incremental_contribution_cents"] > db["incremental_contribution_cents"]
                 or da["delta_c"] > db["delta_c"]))


def compare(spec: ScenarioSpec, candidates: list | None = None) -> ComparisonResult:
    """对候选集（缺省取 spec.candidates）执行同口径比较，输出排序、约束、结论与盈亏平衡。"""
    vres = validate_spec(spec)
    if vres["errors"]:
        raise SpecError("；".join(vres["errors"]))

    cand_list = candidates if candidates is not None else spec.candidates
    if not cand_list:
        cand_list = generate_candidates(spec)

    rows = []
    for cand in cand_list:
        cand = dict(cand)
        row = {
            "label": cand.get("label") or (
                "无券" if not cand.get("enabled")
                else f"满{cand['threshold_cents'] // 100}减{cand['face_value_cents'] // 100}"),
            "candidate": cand,
            "extrapolated": bool(cand.get("extrapolated", False)),
            "metrics": None, "violations": [], "feasible": False,
            "controlled_loss": False, "neighbors": [], "breakeven": None,
            "limitations": [],
        }
        try:
            res = simulate(spec, cand)
        except SpecError as exc:
            row["violations"].append({"constraint": "coupon_legality", "message": str(exc)})
            rows.append(row)
            continue
        row["metrics"] = res.metrics
        row["warnings"] = [lim for lim in res.limitations if "穿过粗桶" in lim]
        row["ledger"] = res.ledger
        row["decomposition"] = res.decomposition
        row["limitations"] = res.limitations
        violations, controlled = _check_constraints(spec, cand, res.metrics)
        row["violations"] = violations
        row["controlled_loss"] = controlled
        row["feasible"] = not violations
        rows.append(row)

    valid_rows = [r for r in rows if r["metrics"] is not None]
    if not valid_rows:
        return ComparisonResult(rows=rows, ranking=[], pareto=[], objective=spec.objective,
                                conclusion={"type": "invalid_comparison",
                                            "message": "所有候选均不合法，无法形成有效比较，请先修复输入",
                                            "evidence_status": spec.evidence_status})

    feasible = [r for r in valid_rows if r["feasible"]]
    for row in feasible:
        if row["candidate"].get("enabled"):
            row["breakeven"] = _breakeven(spec, row["candidate"], row)
    _neighbors(rows)

    objective = spec.objective or "incremental_contribution"
    if objective == "conversion":
        ranking = sorted(feasible, key=lambda r: (-r["metrics"]["conversion_rate"],
                                                  -r["metrics"]["incremental_contribution_cents"]))
    elif objective == "balanced":
        params = getattr(spec, "objective_params", {}) or {}
        w_profit = float(params.get("w_profit", 0.5))
        w_conv = float(params.get("w_conversion", 0.5))
        # §5.2：尺度/权重/方向存入场景，禁止从当前候选集自动推导归一化尺度
        if "profit_scale" not in params or "conversion_scale" not in params:
            raise SpecError("均衡模式必须在 objective_params 显式提供 profit_scale（分）"
                            "与 conversion_scale，不得从候选集自动推导")
        profit_scale = float(params["profit_scale"])
        conv_scale = float(params["conversion_scale"])
        if profit_scale <= 0 or conv_scale <= 0:
            raise SpecError("均衡模式尺度必须为正数")
        for r in feasible:
            r["score"] = (w_profit * r["metrics"]["incremental_contribution_cents"] / profit_scale
                          + w_conv * r["metrics"]["delta_c"] / conv_scale)
        ranking = sorted(feasible, key=lambda r: -r["score"])
    else:
        ranking = sorted(feasible, key=lambda r: -r["metrics"]["incremental_contribution_cents"])

    pareto = [r for r in feasible
              if not any(_dominates(o, r) for o in feasible if o is not r)]

    enabled_feasible = [r for r in feasible if r["candidate"].get("enabled")]
    no_coupon = next((r for r in valid_rows if not r["candidate"].get("enabled")), None)
    weak_evidence = spec.evidence_status in ("synthetic_assumptions", "historical_descriptive", "business_input")
    if not enabled_feasible:
        if no_coupon is not None and no_coupon["feasible"]:
            conclusion = {"type": "no_feasible_coupon",
                          "message": "建议不发券：当前候选与约束下没有满足约束的券方案（无券候选可行）",
                          "evidence_status": spec.evidence_status}
        else:
            conclusion = {"type": "no_feasible_coupon",
                          "message": "当前候选与约束下无可行解：券方案不满足约束，且无券基准也不满足业务目标",
                          "evidence_status": spec.evidence_status}
    elif weak_evidence:
        conclusion = {"type": "needs_validation",
                      "message": "存在潜在可行方案，但关键行为参数缺少适用证据（证据状态："
                                 f"{spec.evidence_status}），建议小范围验证后再放量",
                      "evidence_status": spec.evidence_status}
    else:
        conclusion = {"type": "feasible",
                      "message": "当前候选集合、模型结构、参数与约束下的条件性建议",
                      "evidence_status": spec.evidence_status}

    return ComparisonResult(rows=rows, ranking=ranking, pareto=pareto,
                            conclusion=conclusion, objective=objective)

