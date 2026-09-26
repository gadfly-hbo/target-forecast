"""Excel 报表输出：说明 / 总盘 / 客群结构 / 商品结构 / 交叉校验 / 全渠道汇总 / 参数。"""

from __future__ import annotations

from datetime import datetime

import numpy as np
import pandas as pd
from openpyxl.utils import get_column_letter

MONEY_COLS = {"gmv", "new_gmv", "old_gmv", "GMV_主口径", "新客GMV", "老客GMV", "人视角GMV",
              "人视角GMV", "场视角GMV", "货视角GMV", "基期年化GMV", "目标年度GMV", "uv", "UV"}
RATE_COLS = {"cvr", "aov", "new_arpu", "old_aov", "old_freq", "全渠道客单", "全渠道转化率", "增速"}


def _fmt_frame(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    for c in out.columns:
        if c in MONEY_COLS and pd.api.types.is_numeric_dtype(out[c]):
            out[c] = out[c].round(0)
        elif c in RATE_COLS and pd.api.types.is_numeric_dtype(out[c]):
            out[c] = out[c].round(3)
    return out


def _build_check_sheet(results: dict) -> pd.DataFrame:
    """人/场/货三视角月度GMV对比，与主口径差异>5%打标。"""
    rows = []
    for platform, r in results.items():
        person_m = r["person"].groupby(["scenario", "month"], as_index=False)["gmv"].sum()
        person_m = person_m.rename(columns={"gmv": "人视角GMV"})
        merged = person_m
        if r["field"] is not None:
            f = r["field"].groupby(["scenario", "month"], as_index=False)["gmv"].sum().rename(columns={"gmv": "场视角GMV"})
            merged = merged.merge(f, on=["scenario", "month"], how="left")
        else:
            merged["场视角GMV"] = np.nan
        if r["goods"] is not None:
            g = r["goods"].groupby(["scenario", "month"], as_index=False)["gmv"].sum().rename(columns={"gmv": "货视角GMV"})
            merged = merged.merge(g, on=["scenario", "month"], how="left")
        else:
            merged["货视角GMV"] = np.nan
        main_col = f"{r['main_view']}视角GMV"
        merged["主口径"] = r["main_view"]
        merged["主口径GMV"] = merged[main_col]
        for view in ["人视角GMV", "场视角GMV", "货视角GMV"]:
            diff = merged[view] / merged["主口径GMV"] - 1
            merged[f"{view}差异"] = diff.round(4)
            flag = diff.abs() > 0.05
            merged.loc[flag, "校验"] = "⚠ 与主口径差>5%"
        merged.insert(0, "platform", platform)
        merged["校验"] = merged.get("校验", pd.Series([""] * len(merged))).fillna("")
        rows.append(merged)
    cols = ["platform", "scenario", "month", "主口径", "主口径GMV",
            "人视角GMV", "人视角GMV差异", "场视角GMV", "场视角GMV差异",
            "货视角GMV", "货视角GMV差异", "校验"]
    return pd.concat(rows, ignore_index=True)[cols]


def _build_goods_sheet(results: dict) -> pd.DataFrame:
    parts = []
    for platform, r in results.items():
        if r["goods"] is None:
            continue
        ann = (r["goods"].groupby(["scenario", "品类", "梯队"], as_index=False)
               .agg(gmv=("gmv", "sum"), 款数=("款数", "first")))
        piv = ann.pivot_table(index=["品类", "梯队", "款数"], columns="scenario", values="gmv").reset_index()
        piv.insert(0, "platform", platform)
        parts.append(piv)
    if not parts:
        return pd.DataFrame(columns=["platform", "品类", "梯队", "款数"])
    return pd.concat(parts, ignore_index=True)


def write_report(out_path, results: dict, consolidated: pd.DataFrame,
                 platform_summary: pd.DataFrame, cfg: dict, demo: bool = False) -> None:
    main_parts, person_parts, field_parts = [], [], []
    for platform, r in results.items():
        main_df = r["field"] if r["main_view"] == "场" else r["person"]
        main_parts.append(main_df.assign(platform=platform))
        person_parts.append(r["person"].assign(platform=platform))
        if r["field"] is not None:
            field_parts.append(r["field"].assign(platform=platform))
    main_all = pd.concat(main_parts, ignore_index=True)
    person_all = pd.concat(person_parts, ignore_index=True)
    field_all = pd.concat(field_parts, ignore_index=True) if field_parts else None

    # 总盘：主口径GMV + 新老客拆分
    zongpan = (main_all[["platform", "scenario", "month", "gmv"]]
               .merge(person_all[["platform", "scenario", "month", "new_gmv", "old_gmv", "orders"]],
                      on=["platform", "scenario", "month"], how="left")
               .rename(columns={"gmv": "GMV目标", "orders": "订单数目标",
                                "new_gmv": "新客GMV", "old_gmv": "老客GMV"}))
    zongpan["新客GMV占比"] = zongpan["新客GMV"] / zongpan["GMV目标"]

    kequn = person_all[["platform", "scenario", "month", "new_customers", "new_arpu",
                        "new_gmv", "old_customers", "old_freq", "old_aov", "old_gmv", "gmv"]].copy()
    kequn = kequn.rename(columns={
        "new_customers": "新客数", "new_arpu": "新客客单", "new_gmv": "新客GMV",
        "old_customers": "老客数(月活)", "old_freq": "老客复购频次", "old_aov": "老客客单",
        "old_gmv": "老客GMV", "gmv": "人视角GMV"})

    check = _build_check_sheet(results)
    goods = _build_goods_sheet(results)

    notes = [
        "零售目标测算报告（线上 · 人货场三视角）",
        f"生成时间：{datetime.now():%Y-%m-%d %H:%M}    数据标记：{'演示数据 DEMO' if demo else '正式数据'}",
        "",
        "【口径说明】",
        "1. GMV = 支付口径实付金额之和（应已扣除退款；抖音等高退货平台务必用净额）。",
        f"2. 新客 = 下单前 {cfg['caliber']['new_customer_window_days']} 天内无购买的顾客（滚动口径）；"
        "用户当月身份由当月首单决定。明细数据左截断：数据起点前的购买不可见，首单一律记新客。",
        f"3. 款梯队 = 单款GMV降序累计占比 ≤ {cfg['caliber']['tier_pareto_pct']:.0%} 为爆款、"
        f"末段 ≤ {cfg['caliber']['tier_tail_pct']:.0%} 为尾部、其余腰部；首次售卖距基期末 "
        f"{cfg['caliber']['new_product_days']} 天内记新品，不参与帕累托。",
        "4. 老客复购频次 = 老客订单数 ÷ 老客人数（月内口径）。",
        "5. 订单明细不含UV/转化率（流量数据在平台后台），模式A主口径为人视角；"
        "聚合模式填了UV的平台主口径为场视角（UV×转化×客单）。",
        "6. 全渠道为平台口径加总，用户跨平台不去重；全渠道客单/转化率用分子分母重算，非平台均值。",
        "",
        "【测算方法】基线 = 最近%d个月历史水平；目标 = 基线 × (1+情景增速)，"
        "流量型指标按历史季节性分摊到月，价值型指标平推。" % cfg["caliber"]["baseline_months"],
        "交叉校验表里任一视角与主口径差 > 5%% 会打 ⚠，说明该视角参数假设需要复核。",
    ]
    notes_df = pd.DataFrame({"说明": notes})

    param_rows = []
    for name, p in cfg["scenarios"].items():
        for k, v in p.items():
            if k == "tier_growth":
                for tier, tv in v.items():
                    param_rows.append({"情景": name, "视角": "货", "参数": f"梯队增速-{tier}", "值": tv})
            else:
                view = "场" if k in ("uv_growth", "cvr_growth", "aov_growth") else "人"
                param_rows.append({"情景": name, "视角": view, "参数": k, "值": v})
    for k, v in cfg["caliber"].items():
        param_rows.append({"情景": "口径", "视角": "-", "参数": k, "值": v})
    params = pd.DataFrame(param_rows)

    sheets = {
        "00_说明": notes_df,
        "01_总盘": _fmt_frame(zongpan),
        "02_客群结构": _fmt_frame(kequn),
        "03_商品结构": _fmt_frame(goods),
        "04_交叉校验": _fmt_frame(check),
        "05_全渠道汇总": _fmt_frame(consolidated),
        "06_平台年度汇总": _fmt_frame(platform_summary),
        "07_参数": params,
    }
    with pd.ExcelWriter(out_path, engine="openpyxl") as xw:
        for name, df in sheets.items():
            df.to_excel(xw, sheet_name=name, index=False)
        for name, df in sheets.items():
            ws = xw.sheets[name]
            for i, c in enumerate(df.columns, start=1):
                width = max(10, min(24, max(len(str(c)) * 2, 12)))
                ws.column_dimensions[get_column_letter(i)].width = width
