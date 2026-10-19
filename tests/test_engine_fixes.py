# -*- coding: utf-8 -*-
"""阶段A：六项已确认引擎正确性修正的业务期望测试（先红后绿）。

期望值全部来自业务口径定义（独立真源），不从旧输出指纹推导：
1. 无 UV 的全模式A 汇总不崩溃，且客单用同视角分母
2. SKU 梯队按 GMV 正确划分（索引对齐，与 SKU 排列顺序无关）
3. 短历史基期年化 = 月均 × 12（不是窗口内简单求和）
4. 同平台 A/B 双来源必须显式选择，不得静默覆盖
5. 全渠道客单 = 主口径GMV ÷ 主口径订单数（同视角分子分母）
6. 多平台共用同一目标期（共同基期末月之后 12 个月），缺口平台如实标记
"""

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from target_forecast import aggregate, engine, ingest_detail, pipeline  # noqa: E402

CALIBER = {"baseline_months": 12, "target_months": 12, "tier_scope": "platform",
           "tier_pareto_pct": 0.78, "tier_tail_pct": 0.20, "goods_window_months": 12,
           "new_product_days": 90, "new_customer_window_days": 365}

PERSON_PARAMS = {"new_customers_growth": 0.0, "new_arpu_growth": 0.0,
                 "old_customers_growth": 0.0, "old_freq_growth": 0.0, "old_aov_growth": 0.0}


def _unified(platform, start, n, gmv=1000.0, uv=np.nan):
    rows = []
    for i, m in enumerate(pd.period_range(start, periods=n, freq="M")):
        rows.append({"platform": platform, "month": str(m), "gmv": gmv, "orders": 10.0,
                     "units": 20.0, "buyers": 8.0, "uv": uv,
                     "new_customers": 4.0, "new_gmv": gmv * 0.4, "new_orders": 4.0,
                     "old_customers": 4.0, "old_gmv": gmv * 0.6, "old_orders": 6.0})
    return pd.DataFrame(rows)


# ---------- 修正 1：无 UV 缺列 ----------

def test_consolidate_all_mode_a_no_uv_no_crash():
    """全模式A（无 UV）汇总：不 KeyError；GMV 加总正确；无 UV 列；口径标记"无UV数据"。"""
    cols = ["platform", "scenario", "month", "gmv", "orders", "new_gmv", "old_gmv"]
    person = pd.concat([
        _unified("天猫", "2027-01", 1, 1000.0).assign(scenario="基准")[cols],
        _unified("京东", "2027-01", 1, 2000.0).assign(scenario="基准")[cols],
    ])
    main_all = person[["platform", "scenario", "month", "gmv", "orders"]].copy()
    out = aggregate.consolidate(person, main_all, None)
    r = out.iloc[0]
    assert r["GMV_主口径"] == 3000.0
    assert r["人视角GMV"] == 3000.0
    assert r["订单数"] == 20.0
    assert r["全渠道客单"] == 150.0
    assert "UV" not in out.columns
    assert pd.isna(r["全渠道转化率"])
    assert r["转化率覆盖口径"] == "无UV数据"


# ---------- 修正 2：SKU 梯队索引对齐 ----------

def test_tier_assignment_independent_of_sku_order():
    """梯队划分只由 GMV 决定：字母序与 GMV 序相反时，5 元的款绝不能是爆款。"""
    # 商品ID 字母序 S01..S10；GMV 恰好反向（S01=5 元最小，S10=10000 元最大）
    gmvs = {"S10": 10000.0, "S09": 2000.0, "S08": 1000.0, "S07": 500.0, "S06": 400.0,
            "S05": 300.0, "S04": 100.0, "S03": 50.0, "S02": 20.0, "S01": 5.0}
    rows = []
    for sku, gmv in gmvs.items():
        rows.append({"日期": pd.Timestamp("2026-06-15"), "订单号": f"O-{sku}",
                     "用户ID": "U1", "商品ID": sku, "品类": "测试", "件数": 1, "实付金额": gmv})
    lines = pd.DataFrame(rows)
    end = pd.Timestamp("2026-09-30")
    struct = ingest_detail.goods_structure(lines, CALIBER, end)
    tiers = dict(zip(struct["梯队"], struct["gmv"]))
    # 帕累托 78%：仅 S10(10000, 69.6%) 为爆款；S09(累计83.5%) 超出 → 腰部
    # 末段 20%：S01..S08 累计 2375(16.5%) 为尾部
    assert tiers["爆款"] == 10000.0
    assert tiers["腰部"] == 2000.0
    assert tiers["尾部"] == 2375.0


# ---------- 修正 3：短历史年化 ----------

def test_short_history_baseline_annualized():
    """4 个月历史（每月 GMV 100）的基期年化 GMV = 月均×12 = 1200，而非 400；覆盖月数如实给出。"""
    monthly = _unified("天猫", "2026-06", 4, gmv=100.0)
    base = engine.baseline(monthly, 12)
    assert base["annual_gmv"] == pytest.approx(1200.0)
    assert base["coverage_months"] == 4
    assert base["annualized"] is True


def test_platform_annual_growth_against_annualized_base():
    """短历史平台的年度增速必须对年化基期计算：目标 1500 vs 年化 1200 → +25%（不是 +275%）。"""
    main_all = pd.DataFrame([{"platform": "天猫", "scenario": "基准", "month": f"2027-{i:02d}",
                              "gmv": 125.0, "orders": 5.0} for i in range(1, 13)])
    baselines = {"天猫": {"annual_gmv": 1200.0}}
    out = aggregate.platform_annual(main_all, baselines)
    assert out.iloc[0]["增速"] == pytest.approx(0.25)


def test_full_history_baseline_unchanged():
    """12 个月完整历史：年化 = 求和（行为与旧版一致）。"""
    monthly = _unified("天猫", "2025-10", 12, gmv=100.0)
    base = engine.baseline(monthly, 12)
    assert base["annual_gmv"] == pytest.approx(1200.0)
    assert base["coverage_months"] == 12
    assert base["annualized"] is False


# ---------- 修正 4：同平台 A/B 来源冲突 ----------

def _write_detail_xlsx(path: Path) -> None:
    df = pd.DataFrame([{"日期": pd.Timestamp("2026-01-05"), "订单号": "O1", "用户ID": "U1",
                        "商品ID": "S1", "品类": "A", "件数": 1, "实付金额": 100.0}])
    with pd.ExcelWriter(path, engine="openpyxl") as xw:
        df.to_excel(xw, index=False)


def _write_agg_xlsx(path: Path) -> None:
    df = pd.DataFrame([{"月份": "2026-01", "新客数": 10, "新客客单": 100.0,
                        "老客数": 20, "老客复购频次": 1.5, "老客客单": 200.0}])
    with pd.ExcelWriter(path, engine="openpyxl") as xw:
        df.to_excel(xw, index=False)


def test_same_platform_ab_conflict_raises(tmp_path):
    """同一平台同时存在明细与月度文件：拒绝静默覆盖，冲突显式抛出。"""
    pa, pb = tmp_path / "天猫.xlsx", tmp_path / "天猫.xlsx"
    pa, pb = tmp_path / "a" / "天猫.xlsx", tmp_path / "b" / "天猫.xlsx"
    pa.parent.mkdir()
    pb.parent.mkdir()
    _write_detail_xlsx(pa)
    _write_agg_xlsx(pb)
    with pytest.raises(pipeline.InputConflictError) as exc:
        pipeline.ingest_platforms({"天猫": pa}, {"天猫": pb}, CALIBER)
    assert "天猫" in str(exc.value)


def test_same_platform_ab_conflict_explicit_choice(tmp_path):
    """用户显式选择来源后按选择 ingest（选 A 用明细，选 B 用聚合）。"""
    pa, pb = tmp_path / "a" / "天猫.xlsx", tmp_path / "b" / "天猫.xlsx"
    pa.parent.mkdir()
    pb.parent.mkdir()
    _write_detail_xlsx(pa)
    _write_agg_xlsx(pb)
    chosen_a = pipeline.ingest_platforms({"天猫": pa}, {"天猫": pb}, CALIBER,
                                         source_choice={"天猫": "A"})
    assert chosen_a["天猫"]["mode"] == "A"
    chosen_b = pipeline.ingest_platforms({"天猫": pa}, {"天猫": pb}, CALIBER,
                                         source_choice={"天猫": "B"})
    assert chosen_b["天猫"]["mode"] == "B"


# ---------- 修正 5：全渠道客单同视角分母 ----------

def test_consolidate_aov_uses_main_view_orders():
    """主口径为场（UV×转化×客单）时，全渠道客单 = 场GMV ÷ 场订单数，不混用人视角分母。"""
    person = pd.DataFrame([{"platform": "私域", "scenario": "基准", "month": "2027-01",
                            "new_gmv": 400.0, "old_gmv": 600.0, "orders": 10.0}])
    main_all = pd.DataFrame([{"platform": "私域", "scenario": "基准", "month": "2027-01",
                              "gmv": 1000.0, "orders": 8.0}])  # 场口径订单 = uv×cvr
    field = pd.DataFrame([{"platform": "私域", "scenario": "基准", "month": "2027-01",
                           "uv": 100.0, "cvr": 0.08, "aov": 125.0, "orders": 8.0, "gmv": 1000.0}])
    out = aggregate.consolidate(person, main_all, field)
    r = out.iloc[0]
    assert r["全渠道客单"] == pytest.approx(125.0)   # 1000 ÷ 8，而非 1000 ÷ 10
    assert r["订单数"] == 8.0                        # 订单数列 = 主口径口径
    assert r["全渠道转化率"] == pytest.approx(0.08)
    assert r["转化率覆盖口径"] == "仅含填报UV的平台"


# ---------- 修正 6：多平台共同目标期 ----------

def test_common_target_period_across_platforms():
    """各平台历史末月不同时，目标期从共同末月（最大值）之后起算；缺月平台如实标记缺口。"""
    platforms = {
        "天猫": {"mode": "A", "unified": _unified("天猫", "2026-01", 9), "structure": None},
        "私域": {"mode": "B", "unified": _unified("私域", "2026-01", 12), "structure": None},
    }
    results = pipeline.run_engine(platforms, {"基准": dict(PERSON_PARAMS)}, dict(CALIBER))
    assert results["私域"]["target_months"][0] == "2027-01"
    assert results["天猫"]["target_months"][0] == "2027-01"   # 不是 2026-10
    assert results["天猫"]["target_months"][-1] == "2027-12"
    cov = results["天猫"]["coverage"]
    assert cov["trailing_gap"] == ["2026-10", "2026-11", "2026-12"]
    assert results["私域"]["coverage"]["trailing_gap"] == []
