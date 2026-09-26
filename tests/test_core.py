"""核心不变量测试：基线与测算数学、梯队划分、聚合派生、全渠道重算规则。"""

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from target_forecast import aggregate, engine, ingest_agg, ingest_detail  # noqa: E402

CALIBER = {"baseline_months": 12, "target_months": 6, "tier_scope": "platform",
           "tier_pareto_pct": 0.78, "tier_tail_pct": 0.20, "goods_window_months": 12,
           "new_product_days": 90, "new_customer_window_days": 365}


def flat_monthly(n=12):
    """12个月完全平坦的历史：新客100人×客单150，老客200人×频次1.5×客单200。"""
    rows = []
    for i in range(n):
        month = (pd.Period("2025-01", "M") + i).strftime("%Y-%m")
        new_gmv, old_orders, old_gmv = 100 * 150, 200 * 1.5, 200 * 1.5 * 200
        rows.append({"platform": "P", "month": month, "gmv": new_gmv + old_gmv,
                     "orders": 100 + 300, "units": 800, "buyers": 300, "uv": np.nan,
                     "new_customers": 100, "new_gmv": new_gmv, "new_orders": 100,
                     "old_customers": 200, "old_gmv": old_gmv, "old_orders": 300})
    return pd.DataFrame(rows)


def test_flat_zero_growth_projected_flat():
    monthly = flat_monthly()
    base = engine.baseline(monthly, 12)
    shares = engine.season_shares(monthly)
    params = {"_name": "基准", "new_customers_growth": 0, "new_arpu_growth": 0,
              "old_customers_growth": 0, "old_freq_growth": 0, "old_aov_growth": 0}
    out = engine.project_person(base, params, pd.period_range("2026-01", periods=3, freq="M"), shares)
    assert len(out) == 3
    # 平坦历史 + 零增速 → 每月应等于基期月度水平
    assert out["new_customers"].round(6).eq(100).all()
    assert out["old_customers"].round(6).eq(200).all()
    assert out["gmv"].round(6).eq(75000).all()
    assert out["orders"].round(6).eq(400).all()


def test_annualized_growth_identity():
    monthly = flat_monthly()
    base = engine.baseline(monthly, 12)
    shares = engine.season_shares(monthly)
    params = {"_name": "T", "new_customers_growth": 0.10, "new_arpu_growth": 0.0,
              "old_customers_growth": 0.0, "old_freq_growth": 0.0, "old_aov_growth": 0.0}
    out = engine.project_person(base, params, pd.period_range("2026-01", periods=12, freq="M"), shares)
    # 全年新客数应精确等于 基期月均×12×1.1
    assert out["new_customers"].sum() == pytest.approx(100 * 12 * 1.1)


def test_field_view_matches_person_when_consistent():
    monthly = flat_monthly().copy()
    monthly["uv"] = 400 / 0.10  # cvr=10% 时订单=400，与人数公式一致
    base = engine.baseline(monthly, 12)
    shares = engine.season_shares(monthly)
    p = {"_name": "S", "uv_growth": 0.0, "cvr_growth": 0.0, "aov_growth": 0.0}
    f = engine.project_field(base, p, pd.period_range("2026-01", periods=2, freq="M"), shares)
    assert f is not None
    # aov_total = 75000/400 = 187.5 → 场视角GMV应与人视角完全一致
    assert f["gmv"].round(6).eq(75000).all()


def test_tier_assignment_pareto():
    # 10款GMV：降序累计78%内→爆款，末段20%→尾部
    gmv = [100, 50, 30, 20, 15, 10, 8, 6, 5, 4]
    core = pd.DataFrame({"gmv": gmv})
    tiers = ingest_detail._assign_tiers(core, 0.78, 0.20)
    assert tiers.tolist()[0:3] == ["爆款"] * 3
    assert tiers.tolist()[3] == "腰部"
    assert tiers.tolist()[4:] == ["尾部"] * 6
    assert core["gmv"].sum() == sum(gmv)


def test_goods_structure_new_product_flag():
    end = pd.Timestamp("2026-01-31")
    dates = [pd.Timestamp("2025-06-01") + pd.Timedelta(days=7 * i) for i in range(10)]
    lines = pd.DataFrame({
        "日期": dates, "订单号": [f"O{i}" for i in range(10)], "用户ID": ["U0"] * 10,
        "商品ID": [f"S{i}" for i in range(10)], "品类": ["A"] * 10,
        "实付金额": [100.0, 50, 30, 20, 15, 10, 8, 6, 5, 4], "件数": [1] * 10,
    })
    lines.loc[lines.index[-1], "日期"] = end - pd.Timedelta(days=10)  # 仅 S9 是近90天新品
    struct = ingest_detail.goods_structure(lines, CALIBER, end)
    tiers = dict(zip(struct["梯队"], struct["gmv"]))
    assert tiers == {"爆款": 180.0, "腰部": 20.0, "尾部": 44.0, "新品": 4.0}
    assert struct["gmv"].sum() == 248.0  # 结构守恒：梯队加总=基期GMV


def test_agg_ingest_derives_gmv():
    df = pd.DataFrame([{"月份": "2026-01", "UV": 10000, "新客数": 200, "新客客单": 150.0,
                        "老客数": 800, "老客复购频次": 1.5, "老客客单": 180.0}])
    out = ingest_agg.to_unified(df, "测试")
    r = out.iloc[0]
    assert r["new_gmv"] == 200 * 150
    assert r["old_gmv"] == 800 * 1.5 * 180
    assert r["gmv"] == r["new_gmv"] + r["old_gmv"]
    assert r["orders"] == 200 + 800 * 1.5


def test_consolidate_recomputes_ratios():
    person = pd.DataFrame([
        {"platform": "A", "scenario": "基准", "month": "2026-01", "new_gmv": 300, "old_gmv": 700, "orders": 10, "uv": np.nan},
        {"platform": "B", "scenario": "基准", "month": "2026-01", "new_gmv": 200, "old_gmv": 800, "orders": 30, "uv": 1000.0},
    ])
    main_all = person.rename(columns={"new_gmv": "x", "old_gmv": "y"}).assign(gmv=lambda d: d["x"] + d["y"])
    field = pd.DataFrame([{"platform": "B", "scenario": "基准", "month": "2026-01",
                           "uv": 1000.0, "cvr": 0.03, "aov": 33.3, "orders": 30.0, "gmv": 1000.0}])
    out = aggregate.consolidate(person, main_all, field)
    r = out.iloc[0]
    # 加总：GMV=2000，订单=40；重算：客单=50，转化率=30/1000=3%（不能用平台平均）
    assert r["GMV_主口径"] == 2000
    assert r["订单数"] == 40
    assert r["全渠道客单"] == 50
    assert r["全渠道转化率"] == pytest.approx(0.03)
    assert r["转化率覆盖口径"] == "仅含填报UV的平台"
