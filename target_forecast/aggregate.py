"""全渠道汇总：核心指标直接加总，比率类指标用分子分母重算。

口径：各平台独立核算，用户跨平台不去重（打通需 unionid，属另一个工程）。
"""

from __future__ import annotations

import pandas as pd


def consolidate(person_all: pd.DataFrame, main_all: pd.DataFrame,
                field_all: pd.DataFrame | None) -> pd.DataFrame:
    """入参均含 platform 列（main_all 为各平台主口径月度目标，field_all 可为 None）。

    - GMV/新老客GMV/订单数：跨平台直接加总
    - 全渠道客单 = ΣGMV ÷ Σ订单数，全渠道转化率 = Σ订单数 ÷ ΣUV
      （比率一律重算，不可对平台均值求平均；转化率仅覆盖填报UV的平台）
    """
    main_tot = (main_all.groupby(["scenario", "month"], as_index=False)["gmv"].sum()
                .rename(columns={"gmv": "GMV_主口径"}))
    person_tot = (person_all.groupby(["scenario", "month"], as_index=False)
                  .agg(新客GMV=("new_gmv", "sum"), 老客GMV=("old_gmv", "sum"),
                       订单数=("orders", "sum")))
    out = main_tot.merge(person_tot, on=["scenario", "month"], how="left")
    out["人视角GMV"] = out["新客GMV"] + out["老客GMV"]
    out["全渠道客单"] = out["GMV_主口径"] / out["订单数"].replace(0, pd.NA)

    if field_all is not None and not field_all.empty:
        f = (field_all.groupby(["scenario", "month"], as_index=False)
             .agg(UV=("uv", "sum"), 订单数_场=("orders", "sum")))
        out = out.merge(f, on=["scenario", "month"], how="left")
        out["全渠道转化率"] = out["订单数_场"] / out["UV"].replace(0, pd.NA)
        out["转化率覆盖口径"] = "仅含填报UV的平台"
        out = out.drop(columns=["订单数_场"])
    else:
        out["全渠道转化率"] = pd.NA
        out["转化率覆盖口径"] = "无UV数据"

    cols = ["scenario", "month", "GMV_主口径", "新客GMV", "老客GMV", "人视角GMV",
            "订单数", "UV", "全渠道客单", "全渠道转化率", "转化率覆盖口径"]
    return out[cols].sort_values(["scenario", "month"]).reset_index(drop=True)


def platform_annual(main_all: pd.DataFrame, baselines: dict) -> pd.DataFrame:
    """每平台三档情景的年度目标 vs 基期年化GMV。"""
    rows = []
    ann = main_all.groupby(["platform", "scenario"], as_index=False)["gmv"].sum()
    for platform, g in ann.groupby("platform"):
        base = baselines[platform]["annual_gmv"]
        for _, r in g.iterrows():
            rows.append({
                "platform": platform, "scenario": r["scenario"],
                "基期年化GMV": base, "目标年度GMV": r["gmv"],
                "增速": r["gmv"] / base - 1 if base else pd.NA,
            })
    return pd.DataFrame(rows)
