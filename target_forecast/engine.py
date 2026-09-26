"""测算引擎：对统一月度指标做「基线 + 增量」测算，输出人 / 场 / 货三视角。

测算方法：
- 基线 = 最近 baseline_months 个月的水平（流量型取月均、价值型取加权均值）
- 目标 = 基线 × (1 + 情景增速)，再按历史季节性分摊到月（流量型分摊，价值型平推）
- 人视角：GMV = 新客数×新客客单 + 老客数×复购频次×老客客单   —— 模式A主口径
- 场视角：GMV = UV × 转化率 × 客单                           —— 有UV数据时启用（模式B主口径）
- 货视角：GMV = Σ(品类×梯队 基期 × (1+梯队增速))             —— 有订单明细时启用
"""

from __future__ import annotations

import numpy as np
import pandas as pd


def season_shares(monthly: pd.DataFrame) -> pd.Series:
    """历史GMV的月度季节占比（1-12月，合计=1）。

    历史不足12个自然月或某月缺席时，缺席月用全均值补齐，避免目标月被清零。
    """
    t = monthly.copy()
    t["cal"] = t["month"].str[-2:].astype(int)
    avg = t.groupby("cal")["gmv"].mean()
    full = avg.reindex(range(1, 13))
    fill = avg.mean()
    full = full.fillna(fill if pd.notna(fill) else 1.0)
    return full / full.sum()


def baseline(monthly: pd.DataFrame, months: int) -> dict:
    """最近N个月的基线水平。uv 缺失时为 None（场视角降级）。"""
    win = monthly.sort_values("month").tail(months)

    def _safe(num, den):
        return float(num) / float(den) if den else 0.0

    b = {
        "new_customers": float(win["new_customers"].mean()),
        "new_arpu": _safe(win["new_gmv"].sum(), win["new_customers"].sum()),
        "new_orders_per_cust": _safe(win["new_orders"].sum(), win["new_customers"].sum()),
        "old_customers": float(win["old_customers"].mean()),
        "old_freq": _safe(win["old_orders"].sum(), win["old_customers"].sum()),
        "old_aov": _safe(win["old_gmv"].sum(), win["old_orders"].sum()),
        "aov_total": _safe(win["gmv"].sum(), win["orders"].sum()),
        "annual_gmv": float(win["gmv"].sum()),
    }
    if win["uv"].notna().any() and win["uv"].sum() > 0:
        b["uv"] = float(win["uv"].mean())
        b["cvr"] = _safe(win["orders"].sum(), win["uv"].sum())
    else:
        b["uv"] = None
        b["cvr"] = None
    return b


def _target_month_labels(monthly: pd.DataFrame, n_months: int) -> list[pd.Period]:
    last = pd.Period(monthly["month"].max(), freq="M")
    return pd.period_range(last + 1, periods=n_months, freq="M")


def project_person(base: dict, params: dict, target_months, shares: pd.Series) -> pd.DataFrame:
    rows = []
    for m in target_months:
        sm = float(shares[m.month])
        new_c = base["new_customers"] * (1 + params["new_customers_growth"]) * 12 * sm
        old_c = base["old_customers"] * (1 + params["old_customers_growth"]) * 12 * sm
        arpu = base["new_arpu"] * (1 + params["new_arpu_growth"])
        freq = base["old_freq"] * (1 + params["old_freq_growth"])
        aov = base["old_aov"] * (1 + params["old_aov_growth"])
        new_gmv = new_c * arpu
        old_gmv = old_c * freq * aov
        rows.append({
            "scenario": params["_name"], "month": str(m),
            "new_customers": new_c, "new_arpu": arpu, "new_gmv": new_gmv,
            "old_customers": old_c, "old_freq": freq, "old_aov": aov, "old_gmv": old_gmv,
            "gmv": new_gmv + old_gmv,
            "orders": new_c * base["new_orders_per_cust"] + old_c * freq,
        })
    return pd.DataFrame(rows)


def project_field(base: dict, params: dict, target_months, shares: pd.Series) -> pd.DataFrame | None:
    if not base.get("uv"):
        return None
    rows = []
    for m in target_months:
        sm = float(shares[m.month])
        uv = base["uv"] * (1 + params["uv_growth"]) * 12 * sm
        cvr = base["cvr"] * (1 + params["cvr_growth"])
        aov = base["aov_total"] * (1 + params["aov_growth"])
        orders = uv * cvr
        rows.append({
            "scenario": params["_name"], "month": str(m),
            "uv": uv, "cvr": cvr, "aov": aov, "orders": orders, "gmv": orders * aov,
        })
    return pd.DataFrame(rows)


def project_goods(structure: pd.DataFrame, params: dict, target_months, shares: pd.Series) -> pd.DataFrame | None:
    """基期结构（goods_window_months 合计）× 梯队增速 → 月度目标。"""
    if structure is None or structure.empty:
        return None
    growth = params["tier_growth"]
    rows = []
    for _, r in structure.iterrows():
        g = growth.get(r["梯队"], 0.0)
        for m in target_months:
            rows.append({
                "scenario": params["_name"], "month": str(m),
                "品类": r["品类"], "梯队": r["梯队"], "款数": r["款数"],
                "gmv": r["gmv"] * (1 + g) * float(shares[m.month]),
            })
    return pd.DataFrame(rows)


def run(monthly: pd.DataFrame, structure: pd.DataFrame | None, scenarios: dict,
        caliber: dict) -> dict:
    """单平台测算入口。返回 {baseline, person, field, goods, main_view, target_months}。"""
    n_months = caliber.get("target_months", 12)
    base = baseline(monthly, caliber["baseline_months"])
    shares = season_shares(monthly)
    target_months = _target_month_labels(monthly, n_months)

    person_parts, field_parts, goods_parts = [], [], []
    for name, p in scenarios.items():
        p = {**p, "_name": name}
        person_parts.append(project_person(base, p, target_months, shares))
        f = project_field(base, p, target_months, shares)
        if f is not None:
            field_parts.append(f)
        g = project_goods(structure, p, target_months, shares)
        if g is not None:
            goods_parts.append(g)

    person = pd.concat(person_parts, ignore_index=True)
    field = pd.concat(field_parts, ignore_index=True) if field_parts else None
    goods = pd.concat(goods_parts, ignore_index=True) if goods_parts else None
    # 主口径：有流量数据用场（万能公式），否则用人（人货驱动）
    main_view = "场" if field is not None else "人"
    return {
        "baseline": base, "person": person, "field": field, "goods": goods,
        "main_view": main_view, "target_months": [str(m) for m in target_months],
        "shares": shares,
    }
