"""模式A：通用订单明细 → 统一月度指标层 + 货维度结构。

注意：订单明细里没有 UV / 转化率（流量数据在生意参谋/抖音罗盘，不在订单系统），
所以模式A的主测算口径是人货驱动：
    GMV = 新客数 × 新客客单 + 老客数 × 复购频次 × 老客客单
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from .schema import DETAIL_REQUIRED, UNIFIED_COLUMNS


def load_detail(path, platform: str) -> pd.DataFrame:
    """读取并校验通用订单明细表，附加 month 列。"""
    df = pd.read_excel(path, sheet_name=0, dtype={"订单号": str, "用户ID": str, "商品ID": str})
    missing = [c for c in DETAIL_REQUIRED if c not in df.columns]
    if missing:
        raise ValueError(f"[{platform}] 订单明细缺少必填字段: {missing}")
    df["日期"] = pd.to_datetime(df["日期"], errors="coerce")
    if df["日期"].isna().any():
        raise ValueError(f"[{platform}] 「日期」列存在无法解析的值，请检查格式")
    df["实付金额"] = pd.to_numeric(df["实付金额"], errors="coerce")
    bad = df["实付金额"].isna() | (df["实付金额"] <= 0)
    if bad.any():
        raise ValueError(f"[{platform}] 「实付金额」存在空值/非正值共 {int(bad.sum())} 行，请先清洗")
    for col, default in (("品类", "未分类"), ("件数", 1), ("原价金额", np.nan)):
        if col not in df.columns:
            df[col] = default
    df["month"] = df["日期"].dt.strftime("%Y-%m")
    return df


def order_level(lines: pd.DataFrame) -> pd.DataFrame:
    """订单行 → 订单级（一行 = 一个订单号）。"""
    od = (lines.groupby("订单号", as_index=False)
          .agg(日期=("日期", "first"), 用户ID=("用户ID", "first"),
               实付金额=("实付金额", "sum"), 件数=("件数", "sum")))
    return od.sort_values("日期").reset_index(drop=True)


def classify_new(od: pd.DataFrame, window_days: int) -> pd.DataFrame:
    """滚动口径新老客：下单前 window_days 天内无购买 → 新客。

    用户当月的新老身份由当月首单决定，该用户当月全部订单计入同一桶。
    数据起点之前的购买史不可见（左截断），首单一律记新客，见 README 口径说明。
    """
    od = od.sort_values(["用户ID", "日期"]).copy()
    prev = od.groupby("用户ID")["日期"].shift(1)
    gap = (od["日期"] - prev).dt.days
    od["is_new"] = prev.isna() | (gap > window_days)
    od["month"] = od["日期"].dt.strftime("%Y-%m")
    status = od.drop_duplicates(["用户ID", "month"], keep="first")[["用户ID", "month", "is_new"]]
    od = od.drop(columns=["is_new"]).merge(status, on=["用户ID", "month"], how="left")
    return od


def to_unified(od: pd.DataFrame, platform: str) -> pd.DataFrame:
    """订单级数据（已带 is_new）→ 统一月度指标。"""
    rows = []
    for month, m in od.groupby("month"):
        new, old = m[m["is_new"]], m[~m["is_new"]]
        rows.append({
            "platform": platform, "month": month,
            "gmv": m["实付金额"].sum(), "orders": len(m),
            "units": m["件数"].sum(), "buyers": m["用户ID"].nunique(), "uv": np.nan,
            "new_customers": new["用户ID"].nunique(), "new_gmv": new["实付金额"].sum(), "new_orders": len(new),
            "old_customers": old["用户ID"].nunique(), "old_gmv": old["实付金额"].sum(), "old_orders": len(old),
        })
    return pd.DataFrame(rows, columns=UNIFIED_COLUMNS).sort_values("month").reset_index(drop=True)


# ---------------- 货维度：品类 × 款梯队 ----------------

def _assign_tiers(core: pd.DataFrame, pareto_pct: float, tail_pct: float) -> pd.Series:
    """对一组SKU按GMV划梯队：降序累计 ≤ pareto_pct 为爆款，末段累计 ≤ tail_pct 为尾部，其余腰部。"""
    order = core.sort_values("gmv", ascending=False)
    tiers = np.full(len(order), "腰部", dtype=object)
    total = order["gmv"].sum()
    if total <= 0:
        return pd.Series(tiers, index=order.index)
    cum_top = order["gmv"].cumsum().values / total
    for i in range(len(order)):
        if i == 0 or cum_top[i] <= pareto_pct:
            tiers[i] = "爆款"
        else:
            break
    cum_bottom = order["gmv"].values[::-1].cumsum()[::-1] / total
    for i in range(len(order) - 1, -1, -1):
        if tiers[i] != "腰部":
            continue
        if i == len(order) - 1 or cum_bottom[i] <= tail_pct:
            tiers[i] = "尾部"
        else:
            break
    return pd.Series(tiers, index=order.index)


def goods_structure(lines: pd.DataFrame, caliber: dict, history_end: pd.Timestamp) -> pd.DataFrame:
    """基期（goods_window_months 内）品类×梯队结构表：[品类, 梯队, gmv, 款数]。

    首次售卖距基期末 ≤ new_product_days 的款记为「新品」，不参与帕累托划分、单列一行。
    """
    window_start = history_end - pd.DateOffset(months=caliber["goods_window_months"])
    win = lines[lines["日期"] > window_start]
    if win.empty:
        return pd.DataFrame(columns=["品类", "梯队", "gmv", "款数"])
    first_seen = lines.groupby("商品ID")["日期"].min()
    sku = (win.groupby("商品ID")
           .agg(gmv=("实付金额", "sum"), 品类=("品类", "first"))
           .reset_index())
    sku["first_seen"] = sku["商品ID"].map(first_seen)
    new_cut = history_end - pd.Timedelta(days=caliber["new_product_days"])
    sku["梯队"] = np.where(sku["first_seen"] >= new_cut, "新品", "")

    core = sku[sku["梯队"] == ""]
    if not core.empty:
        core = core.copy()
        if caliber["tier_scope"] == "category":
            for _, g in core.groupby("品类"):
                core.loc[g.index, "梯队"] = _assign_tiers(g, caliber["tier_pareto_pct"], caliber["tier_tail_pct"]).values
        else:
            core["梯队"] = _assign_tiers(core, caliber["tier_pareto_pct"], caliber["tier_tail_pct"]).values
        sku.loc[core.index, "梯队"] = core["梯队"]

    struct = (sku.groupby(["品类", "梯队"], as_index=False)
              .agg(gmv=("gmv", "sum"), 款数=("商品ID", "nunique")))
    return struct.sort_values(["gmv"], ascending=False).reset_index(drop=True)
