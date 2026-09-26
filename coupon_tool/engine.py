# -*- coding: utf-8 -*-
"""L2 测算引擎：四个子模型 + 统一收益账本（提案 §4 逐式实现）。

① 命中与核销（4.2） ② 凑单与流失（4.3） ③ 转化响应（4.4） ④ 统一账本（4.5）
所有指标（转化率、订单、核销、补贴、贡献）出自同一组互斥分支；4.6 拆解与 ΔΠ 对平。
金额单位：分（float 参与期望计算，输出取整分）；概率：float。
"""
from __future__ import annotations

import math
from dataclasses import dataclass

from .spec import ENGINE_VERSION, ScenarioSpec, SpecError, validate_spec


@dataclass
class SimulationResult:
    candidate: dict
    metrics: dict
    ledger: list
    validation: dict
    limitations: list
    decomposition: dict
    engine_version: str = ENGINE_VERSION


def _per_basket(value, i, n):
    if isinstance(value, list):
        if len(value) != n:
            raise SpecError("逐篮子参数长度与篮子数不一致")
        return float(value[i])
    return float(value)


def _q_i(spec: ScenarioSpec, amount_cents: int, t: int, f: int) -> float:
    h = spec.behavior
    if h.q_mode == "zero":
        return 0.0
    if h.q_mode == "table":
        g = (t - amount_cents) / amount_cents
        ftr = f / t
        for row in h.q_table:
            gap_ok = row.get("gap_max") is None or g <= row["gap_max"]
            ftr_ok = row.get("ftr_max") is None or ftr <= row["ftr_max"]
            if gap_ok and ftr_ok:
                return float(row["q"])
        return 0.0
    qc = h.q_curve
    g = (t - amount_cents) / amount_cents
    return float(qc["q_cap"]) * math.exp(-float(qc["lam"]) * g) * min(1.0, (f / t) / float(qc["d_ref"]))


def _variable_fee(spec: ScenarioSpec, amount: float, u: int, f: int) -> float:
    c = spec.cost
    base = (amount - u * f) if c.fee_basis == "customer_paid" else amount
    return c.fixed_fee_cents + c.fee_rate * base


def _row(group, branch, basket, prob, orders, amount, u, f, spec, margin_rate, m_addon, base_amount,
         basket_index=None):
    """构造一条成交分支账本行；contribution = G − 商家券补 − V − H。"""
    c = spec.cost
    if group == "loss":
        # 流失分支：没有订单——无收入、无费用、无补贴；机会损失经 ΔΠ 体现
        gross = merchant = platform = v_fee = h_adj = contrib = 0.0
    else:
        addon = max(0.0, amount - base_amount) if group != "new" else 0.0
        if group == "new":
            gross = amount * margin_rate
        else:
            gross = base_amount * margin_rate + addon * m_addon
        merchant = u * c.merchant_share_rho * f
        platform = u * (1.0 - c.merchant_share_rho) * f
        v_fee = _variable_fee(spec, amount, u, f)
        h_adj = c.return_adj_cents
        contrib = gross - merchant - v_fee - h_adj
    return {
        "group": group, "branch": branch, "basket": basket, "basket_index": basket_index,
        "probability": prob, "expected_orders": orders,
        "amount_cents": round(amount, 6), "customer_paid_cents": round(amount - u * f, 6),
        "redeemed": u,
        "merchant_subsidy_cents": round(merchant * orders, 6),
        "platform_subsidy_cents": round(platform * orders, 6),
        "gross_margin_cents": round(gross * orders, 6),
        "variable_fee_cents": round(v_fee * orders, 6),
        "return_adj_cents": round(h_adj * orders, 6),
        "contribution_cents": round(contrib * orders, 6),
        "_pi_single": contrib,
    }


def _baseline_basket_rows(spec: ScenarioSpec) -> list:
    """无券基准分支（每篮子一行，u=0），供 Π₀ 与 π₀ᵢ 使用。"""
    c = spec.cost
    rows = []
    for i, bk in enumerate(spec.baseline.baskets):
        m_i = bk.margin_rate if bk.margin_rate is not None else c.margin_base_rate
        rows.append(_row("base", "无券基准原样购买", bk.label or f"A={bk.amount_cents}",
                         1.0, 1.0, float(bk.amount_cents), 0, 0, spec, m_i, 0.0, float(bk.amount_cents),
                         basket_index=i))
    return rows


def simulate(spec: ScenarioSpec, candidate: dict) -> SimulationResult:
    """对单个候选（含 enabled=false 无券候选）执行四子模型与统一账本。"""
    if not isinstance(candidate, dict):
        raise SpecError("candidate 必须是 dict")
    enabled = bool(candidate.get("enabled"))
    t = candidate.get("threshold_cents")
    f = candidate.get("face_value_cents", 0) or 0
    if enabled:
        if isinstance(t, bool) or not isinstance(t, int):
            raise SpecError("门槛必须是整数分")
        if isinstance(f, bool) or not isinstance(f, int):
            raise SpecError("面额必须是整数分")
        if f <= 0:
            raise SpecError("有效券要求 0 < F（面额必须为正整数分）")
        if f >= t:
            raise SpecError(f"有效券要求 0 < F < T（当前 F={f}, T={t}）")

    vres = validate_spec(spec)
    if vres["errors"]:
        raise SpecError("；".join(vres["errors"]))

    bl = spec.baseline
    h = spec.behavior
    c = spec.cost
    n_baskets = len(bl.baskets)
    n_visitors = bl.visitors if bl.visitors is not None else 1
    c0 = bl.conversion_rate

    limitations: list[str] = []
    if bl.visitors is None:
        limitations.append("缺 N：以下结果为每观察单位口径，不代表活动总量")

    base_rows = _baseline_basket_rows(spec)
    pi0_by_basket = [r["_pi_single"] for r in base_rows]

    ledger: list = []
    e_pi_after = 0.0     # Σ wᵢ·Σₕ p·π（基准人群，券场景）
    l_rate = 0.0         # L = Σ wᵢ·流失概率
    e_pi0 = 0.0          # Σ wᵢ·π₀ᵢ
    topup_at_threshold = False

    for i, bk in enumerate(bl.baskets):
        w = bk.weight
        m_i = bk.margin_rate if bk.margin_rate is not None else c.margin_base_rate
        m_addon = c.margin_addon_rate if c.margin_addon_rate is not None else m_i
        label = bk.label or f"A={bk.amount_cents}"
        a = float(bk.amount_cents)
        pi0 = pi0_by_basket[i]
        e_pi0 += w * pi0

        if not enabled:
            row = _row("base", "无券基准原样购买", label, 1.0, n_visitors * c0 * w, a, 0, 0,
                       spec, m_i, m_addon, a, basket_index=i)
            ledger.append(row)
            e_pi_after += w * row["_pi_single"]
            continue

        e_i = _per_basket(h.reach_base, i, n_baskets)
        d_i = _per_basket(h.churn, i, n_baskets)

        if a >= t:
            # 子模型①：自然命中三分支（P0：不估计超门槛加购与反向流失）
            r_i = _per_basket(h.redeem_natural, i, n_baskets)
            branches = [
                ("natural", "未触达·按原计划购买", 1.0 - e_i, a, 0),
                ("natural", "已触达并核销", e_i * r_i, a, 1),
                ("natural", "已触达未核销·按原计划购买", e_i * (1.0 - r_i), a, 0),
            ]
            loss_i = 0.0
        else:
            # 子模型②：凑单与流失五分支（概率合计=1）
            q_i = _q_i(spec, bk.amount_cents, t, f)
            b_amt = float(bk.topup_amount_cents if bk.topup_amount_cents is not None else t)
            if b_amt < t:
                raise SpecError(f"加购后金额 Bᵢ({b_amt}) 不得低于门槛 T({t})")
            if bk.topup_amount_cents is None:
                topup_at_threshold = True
            rp_i = _per_basket(h.redeem_topup, i, n_baskets)
            branches = [
                ("keep", "未触达·原样购买", 1.0 - e_i, a, 0),
                ("topup", "加购达标并核销", e_i * q_i * rp_i, b_amt, 1),
                ("topup", "加购达标未核销", e_i * q_i * (1.0 - rp_i), b_amt, 0),
                ("keep", "未加购·仍原样购买", e_i * (1.0 - q_i) * (1.0 - d_i), a, 0),
                ("loss", "未加购·放弃原本购买", e_i * (1.0 - q_i) * d_i, 0.0, 0),
            ]
            loss_i = e_i * (1.0 - q_i) * d_i

        if (enabled and bk.bucket_min_cents is not None and bk.bucket_max_cents is not None
                and bk.bucket_min_cents < t <= bk.bucket_max_cents):
            limitations.append(
                f"门槛 {t / 100:.0f} 元穿过粗桶 [{bk.bucket_min_cents / 100:.0f},"
                f"{bk.bucket_max_cents / 100:.0f}]：桶内分布未知，结果基于桶均金额——请细分或提供上下界")

        l_rate += w * loss_i
        for group, name, p, amt, u in branches:
            row = _row(group, name, label, p, n_visitors * c0 * w * p, amt, u, f, spec, m_i, m_addon, a,
                       basket_index=i)
            ledger.append(row)
            e_pi_after += w * p * row["_pi_single"]

    # 子模型③：转化响应（无券候选直接使用完整基准，不运行券诱导行为）
    retention = 1.0 - l_rate
    conv = h.conversion
    if not enabled:
        d_c_plus = 0.0
    elif conv.get("mode") == "absolute":
        d_c_plus = float(conv["delta_c_plus"])
        if d_c_plus > (1.0 - c0 * retention):
            limitations.append(f"绝对 ΔC⁺={d_c_plus:.4f} 超出可触达非购买者上限，模型与证据不相容")
    else:
        s_plus = min(float(conv.get("k", 0.9)) * (f / t), float(conv.get("s_max", 0.5)))
        e_new = float(h.reach_new)
        d_c_plus = min((1.0 - c0) * e_new, c0 * s_plus * e_new)
        if c0 == 0.0:
            limitations.append("C₀=0：相对响应曲线无法产生新增成交，如需新增请显式输入绝对 ΔC⁺")

    # 新增成交（归一化 vⱼ；不再乘基准命中率）
    if d_c_plus > 0:
        if not h.new_basket:
            raise SpecError("ΔC⁺>0 但缺少新增结果分布 vⱼ")
        for nb in h.new_basket:
            m_j = nb.get("margin_rate", c.margin_base_rate)
            amt_j = t if nb.get("amount_cents", "at_threshold") == "at_threshold" else nb["amount_cents"]
            row = _row("new", f"新增·{nb.get('label', amt_j)}", "新增成交",
                       float(nb["weight"]), n_visitors * d_c_plus * float(nb["weight"]),
                       float(amt_j), int(nb["redeem"]), f, spec, m_j, 0.0,
                       float(amt_j), basket_index=None)
            ledger.append(row)

    # 子模型④：统一账本（一切指标从 ledger 汇总）
    def _sum(key):
        return sum(r[key] for r in ledger)

    orders = sum(r["expected_orders"] for r in ledger if r["group"] != "loss")  # 流失行无订单
    gmv_pre = sum(r["expected_orders"] * r["amount_cents"] for r in ledger)
    gmv_paid = sum(r["expected_orders"] * r["customer_paid_cents"] for r in ledger)
    merchant_sub = _sum("merchant_subsidy_cents")
    platform_sub = _sum("platform_subsidy_cents")
    k_cost = c.fixed_activity_cost_cents if enabled else 0.0  # K 只含相对无券方案新增的固定费用（§4.5）
    pi_coupon = _sum("contribution_cents") - k_cost
    pi0_total = n_visitors * c0 * e_pi0
    delta_pi = pi_coupon - pi0_total
    conversion = c0 * retention + d_c_plus
    natural_red = sum(r["expected_orders"] for r in ledger
                      if r["group"] == "natural" and r["redeemed"] == 1)
    topup_red = sum(r["expected_orders"] for r in ledger
                    if r["group"] == "topup" and r["redeemed"] == 1)
    new_orders = sum(r["expected_orders"] for r in ledger if r["group"] == "new")
    lost_orders = sum(r["expected_orders"] for r in ledger if r["group"] == "loss")

    if topup_at_threshold and enabled:
        limitations.append("加购金额按“恰好凑到门槛”(B=T)简化，非商品可凑性保证")
    if h.q_mode == "curve" and enabled:
        limitations.append("凑单概率使用演示情景曲线 q=q_cap·exp(−λg)·min(1,(F/T)/d_ref)，非行为定律，参数须可替换")
    if c.fixed_fee_cents == 0 and c.fee_rate == 0:
        limitations.append("可变费用未配置（按 0 计），履约/支付费用需另行确认")
    if c.return_adj_cents == 0:
        limitations.append("退货调整为 0 的情景估计，未含退货结算规则")
    if enabled and len(h.new_basket) == 1 and h.new_basket[0].get("amount_cents", "at_threshold") == "at_threshold":
        limitations.append("新增成交篮子为单一结果类型（金额=门槛）——演算简化，寻优需对新增篮子做压力检查")
    if conv.get("mode") == "relative" and enabled:
        limitations.append("新增篮子结构未随门槛调整（静态假设），跨候选比较时需显式说明")

    # 4.6 贡献拆解（与 ΔΠ 对平）
    def _delta_vs_pi0(group_filter, redeemed_only=None):
        total = 0.0
        for r in ledger:
            if r["group"] != group_filter:
                continue
            if redeemed_only is not None and r["redeemed"] != redeemed_only:
                continue
            idx = r.get("basket_index")
            pi0_ref = pi0_by_basket[idx] if idx is not None else 0.0
            if r["group"] == "loss":
                # 流失订单的损失 = 放弃的原本贡献（π_single 已为 0）
                total += r["expected_orders"] * (0.0 - pi0_ref)
            else:
                total += r["expected_orders"] * (r["_pi_single"] - pi0_ref)
        return total

    decomposition = {
        "natural_redemption": _delta_vs_pi0("natural", 1),
        "topup": _delta_vs_pi0("topup"),
        "other_retained": _delta_vs_pi0("natural", 0) + _delta_vs_pi0("keep") + _delta_vs_pi0("base"),
        "lost_orders": _delta_vs_pi0("loss"),
        "new_orders": sum(r["contribution_cents"] for r in ledger if r["group"] == "new"),
        "fixed_costs": -float(k_cost),
    }

    metrics = {
        "conversion_rate": conversion,
        "delta_c": d_c_plus - c0 * l_rate,
        "churn_rate": c0 * l_rate,
        "retention": retention,
        "gross_new_rate": d_c_plus,
        "orders": orders,
        "orders_baseline": n_visitors * c0,
        "new_orders": new_orders,
        "lost_orders": lost_orders,
        "natural_redemptions": natural_red,
        "topup_redemptions": topup_red,
        "gmv_pre_cents": round(gmv_pre, 6),
        "gmv_paid_cents": round(gmv_paid, 6),
        "merchant_subsidy_cents": round(merchant_sub, 6),
        "platform_subsidy_cents": round(platform_sub, 6),
        "baseline_contribution_cents": round(pi0_total, 6),
        "total_contribution_cents": round(pi_coupon, 6),
        "incremental_contribution_cents": round(delta_pi, 6),
        "roi": None if round(merchant_sub, 6) == 0 else delta_pi / merchant_sub,
        "avg_contribution_cents": (round(pi_coupon / orders, 6) if orders > 0 else None),
    }

    for r in ledger:
        r.pop("_pi_single", None)

    return SimulationResult(
        candidate=dict(candidate),
        metrics=metrics,
        ledger=ledger,
        validation=vres,
        limitations=limitations,
        decomposition={k: round(v, 6) for k, v in decomposition.items()},
    )
