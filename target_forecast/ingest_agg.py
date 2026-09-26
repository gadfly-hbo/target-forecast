"""模式B：聚合指标表 → 统一月度指标层。

GMV 由人公式派生：GMV = 新客数×新客客单 + 老客数×复购频次×老客客单。
若填了 UV，则场视角（UV×转化×客单）完整启用；若另填了 GMV/转化率，仅作一致性校验。
"""

from __future__ import annotations

import warnings

import numpy as np
import pandas as pd

from .schema import AGG_REQUIRED, UNIFIED_COLUMNS


def _norm_month(v) -> str:
    if isinstance(v, (pd.Timestamp,)):
        return v.strftime("%Y-%m")
    s = str(v).strip()
    if len(s) == 7 and s[4] == "-":
        return s
    # '2026/9' / '2026.09' / '202609' 等常见写法
    s2 = s.replace("/", "-").replace(".", "-")
    parts = s2.split("-")
    if len(parts) == 2:
        return f"{int(parts[0]):04d}-{int(parts[1]):02d}"
    if len(s) == 8 and s.isdigit():
        return f"{s[:4]}-{s[4:6]}"
    raise ValueError(f"无法解析月份: {v!r}，请用 YYYY-MM")


def load_agg(path, platform: str) -> pd.DataFrame:
    df = pd.read_excel(path, sheet_name=0)
    missing = [c for c in AGG_REQUIRED if c not in df.columns]
    if missing:
        raise ValueError(f"[{platform}] 聚合指标表缺少必填字段: {missing}")
    df["月份"] = df["月份"].map(_norm_month)
    for c in ["新客数", "新客客单", "老客数", "老客复购频次", "老客客单", "UV", "新客订单数", "转化率", "GMV"]:
        if c in df.columns:
            df[c] = pd.to_numeric(df[c], errors="coerce")
    return df.sort_values("月份").reset_index(drop=True)


def to_unified(df: pd.DataFrame, platform: str) -> pd.DataFrame:
    rows = []
    for _, r in df.iterrows():
        new_gmv = r["新客数"] * r["新客客单"]
        old_orders = r["老客数"] * r["老客复购频次"]
        old_gmv = old_orders * r["老客客单"]
        new_orders = r["新客订单数"] if ("新客订单数" in df.columns and pd.notna(r.get("新客订单数"))) else r["新客数"]
        orders = new_orders + old_orders
        gmv = new_gmv + old_gmv
        uv = r.get("UV", np.nan)

        if "GMV" in df.columns and pd.notna(r.get("GMV")) and r["GMV"] > 0:
            if abs(gmv / r["GMV"] - 1) > 0.05:
                warnings.warn(f"[{platform}] {r['月份']} 填写的GMV与公式派生GMV差>5%: "
                              f"填写{r['GMV']:.0f} vs 派生{gmv:.0f}")
        if "转化率" in df.columns and pd.notna(r.get("转化率")) and pd.notna(uv) and uv > 0:
            implied = orders / uv
            if abs(implied / r["转化率"] - 1) > 0.10:
                warnings.warn(f"[{platform}] {r['月份']} 填写的转化率与隐含转化率差>10%: "
                              f"填写{r['转化率']:.3f} vs 隐含{implied:.3f}")

        rows.append({
            "platform": platform, "month": r["月份"],
            "gmv": gmv, "orders": orders, "units": np.nan,
            "buyers": r["新客数"] + r["老客数"], "uv": uv,
            "new_customers": r["新客数"], "new_gmv": new_gmv, "new_orders": new_orders,
            "old_customers": r["老客数"], "old_gmv": old_gmv, "old_orders": old_orders,
        })
    return pd.DataFrame(rows, columns=UNIFIED_COLUMNS).sort_values("month").reset_index(drop=True)
