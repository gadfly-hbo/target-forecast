# -*- coding: utf-8 -*-
"""优惠券测算引擎验收测试。

黄金数值独立来源：《优惠券测算工具 v2.0｜独立产品方案》第七节合成案例
（.flow/proposal.md 已固定；红队复算确认公式-数值自洽）。
只测公共库接口 coupon_tool.load_spec / validate_spec / simulate。
"""
import math
import pytest

from coupon_tool import ENGINE_VERSION, load_spec, simulate, validate_spec
from coupon_tool.synthetic import build_synthetic_spec, GOLDEN_TABLE

TOL_CENTS = 1          # 金额容差 ±1 分
TOL_RATE = 5e-6        # 转化率容差（文档给到百分号后 4 位）


def _metrics_for(spec, threshold=None, face=0, enabled=None):
    cand = {"enabled": enabled if enabled is not None else threshold is not None,
            "threshold_cents": threshold, "face_value_cents": face}
    return simulate(spec, cand)


# ---------- 黄金案例：基准情景表（提案 7.2，10 行全量） ----------

@pytest.mark.parametrize("label,threshold,face,conv,bm,total,delta", GOLDEN_TABLE)
def test_golden_baseline_table(label, threshold, face, conv, bm, total, delta):
    spec = build_synthetic_spec()
    m = _metrics_for(spec, threshold, face, enabled=(threshold is not None)).metrics
    assert abs(m["conversion_rate"] - conv) < TOL_RATE, label
    assert abs(m["merchant_subsidy_cents"] - bm * 100) <= TOL_CENTS, label
    assert abs(m["total_contribution_cents"] - total * 100) <= TOL_CENTS, label
    assert abs(m["incremental_contribution_cents"] - delta * 100) <= TOL_CENTS, label


def test_golden_baseline_contribution():
    spec = build_synthetic_spec()
    m = _metrics_for(spec, enabled=False).metrics
    assert m["baseline_contribution_cents"] == 26_400_000  # 264,000.00 元
    assert m["incremental_contribution_cents"] == 0
    assert m["conversion_rate"] == pytest.approx(0.08)


# ---------- M04/M06：分支守恒与转化一致 ----------

def test_branch_probabilities_sum_to_one():  # M04
    spec = build_synthetic_spec()
    for cand in ({"enabled": True, "threshold_cents": 15900, "face_value_cents": 500},
                 {"enabled": True, "threshold_cents": 7900, "face_value_cents": 500},
                 {"enabled": False, "threshold_cents": None, "face_value_cents": 0}):
        res = simulate(spec, cand)
        per_basket = {}
        for row in res.ledger:
            per_basket.setdefault(row["basket"], []).append(row["probability"])
        assert per_basket, "账本为空"
        for basket, probs in per_basket.items():
            assert abs(sum(probs) - 1.0) < 1e-9, basket


def test_orders_over_n_equals_conversion_rate():  # M06
    spec = build_synthetic_spec()
    for t, f in [(15900, 500), (13900, 2000), (9900, 1000)]:
        m = simulate(spec, {"enabled": True, "threshold_cents": t, "face_value_cents": f}).metrics
        orders = sum(r["expected_orders"] for r in simulate(
            spec, {"enabled": True, "threshold_cents": t, "face_value_cents": f}).ledger
            if r["group"] != "loss")
        assert abs(orders / spec.baseline.visitors - m["conversion_rate"]) < 1e-9
        assert 0.0 <= m["conversion_rate"] <= 1.0


# ---------- M01/M02/M03/M08/M11：回到基准与不伪造 ----------

def _clone_with(spec, **overrides):
    data = spec.to_dict()
    behavior = data.setdefault("behavior", {})
    for k, v in overrides.items():
        behavior[k] = v
    return load_spec(data)


@pytest.mark.parametrize("k_cents", [0, 50_000])
def test_m01_no_coupon_equals_full_baseline(k_cents):
    data = build_synthetic_spec().to_dict()
    data["cost"]["fixed_activity_cost_cents"] = k_cents   # K 只属于券方案，无券候选不扣
    spec = load_spec(data)
    m = _metrics_for(spec, enabled=False).metrics
    assert m["total_contribution_cents"] == m["baseline_contribution_cents"]
    assert m["incremental_contribution_cents"] == 0
    assert m["merchant_subsidy_cents"] == 0
    # 有券候选的 ΔΠ 需承担 K
    m_c = _metrics_for(spec, 15900, 500).metrics
    assert m_c["incremental_contribution_cents"] == pytest.approx(
        _metrics_for(build_synthetic_spec(), 15900, 500).metrics["incremental_contribution_cents"]
        - k_cents, abs=2)


def test_m02_zero_reach_returns_baseline():
    spec = _clone_with(build_synthetic_spec(), reach_base=0.0, reach_new=0.0)
    for t, f in [(15900, 500), (9900, 1000)]:
        m = _metrics_for(spec, t, f).metrics
        assert m["incremental_contribution_cents"] == 0
        assert m["conversion_rate"] == pytest.approx(0.08)
        assert m["merchant_subsidy_cents"] == 0


def test_m03_zero_natural_redeem_no_subsidy_no_fake():
    spec = _clone_with(build_synthetic_spec(), redeem_natural=0.0,
                       conversion={"mode": "absolute", "delta_c_plus": 0.0})
    # 门槛低于最小篮子 → 全部自然命中
    m = _metrics_for(spec, 5000, 500).metrics
    assert m["merchant_subsidy_cents"] == 0
    assert m["natural_redemptions"] == 0


def test_m08_platform_bears_all_not_charged_to_merchant():
    data = build_synthetic_spec().to_dict()
    data["cost"]["merchant_share_rho"] = 0.0
    spec = load_spec(data)
    m = _metrics_for(spec, 15900, 500).metrics
    assert m["merchant_subsidy_cents"] == 0
    assert m["platform_subsidy_cents"] > 0
    # 平台承担且无其他行为差异时，贡献不低于基准（无商家成本被误扣）
    assert m["incremental_contribution_cents"] >= 0


def test_m11_all_behaviors_off_returns_baseline():
    spec = _clone_with(build_synthetic_spec(),
                       q_mode="zero",
                       churn=0.0,
                       conversion={"mode": "absolute", "delta_c_plus": 0.0})
    # 门槛高于最大篮子 → 无自然命中；q=0 无加购；d=0 无流失；无新增；K=0
    m = _metrics_for(spec, 20000, 500).metrics
    assert m["incremental_contribution_cents"] == 0
    assert m["conversion_rate"] == pytest.approx(0.08)


# ---------- M05/M07：新增分布与自然核销账 ----------

def test_m05_new_basket_normalized_not_rescaled_by_hit():
    data = build_synthetic_spec().to_dict()
    data["behavior"]["conversion"] = {"mode": "absolute", "delta_c_plus": 0.02}
    data["behavior"]["new_basket"] = [
        {"label": "新增-恰好达标", "weight": 0.6, "amount_cents": 15900, "margin_rate": 0.3, "redeem": 1},
        {"label": "新增-小额", "weight": 0.4, "amount_cents": 8000, "margin_rate": 0.3, "redeem": 1},
    ]
    # 明确使用固定金额（非跟随门槛），便于字面量断言
    spec = load_spec(data)
    res = simulate(spec, {"enabled": True, "threshold_cents": 15900, "face_value_cents": 500})
    new_rows = [r for r in res.ledger if r["group"] == "new"]
    total_new_orders = sum(r["expected_orders"] for r in new_rows)
    assert total_new_orders == pytest.approx(spec.baseline.visitors * 0.02)  # N×ΔC⁺，不乘 P₁
    # 逐结果类型期望贡献 = N×ΔC⁺×vⱼ×πⱼ，πⱼ 为字面量：159×0.3−5=42.7 元；80×0.3−5=19 元
    per_row = {r["branch"]: r["contribution_cents"] for r in new_rows}
    assert abs(per_row["新增·新增-恰好达标"] - 100000 * 0.02 * 0.6 * 4270) <= TOL_CENTS
    assert abs(per_row["新增·新增-小额"] - 100000 * 0.02 * 0.4 * 1900) <= TOL_CENTS


def test_m07_all_natural_hit_contribution_drop_equals_merchant_subsidy():
    data = build_synthetic_spec().to_dict()
    data["behavior"]["conversion"] = {"mode": "absolute", "delta_c_plus": 0.0}
    spec = load_spec(data)
    m = _metrics_for(spec, 5000, 500).metrics  # 全部自然命中，零其他费用
    assert m["incremental_contribution_cents"] == -m["merchant_subsidy_cents"]


# ---------- M13/M14：边界与阻断 ----------

def test_m13_c0_zero_relative_curve_visible_limitation():
    data = build_synthetic_spec().to_dict()
    data["baseline"]["conversion_rate"] = 0.0
    spec = load_spec(data)
    res = simulate(spec, {"enabled": True, "threshold_cents": 15900, "face_value_cents": 500})
    assert any("C₀=0" in lim or "C0=0" in lim for lim in res.limitations)
    # 相对曲线在 C0=0 不产生新增
    assert res.metrics["gross_new_rate"] == 0.0


def test_m14_illegal_candidates_blocked():
    from coupon_tool.spec import SpecError
    spec = build_synthetic_spec()
    with pytest.raises(SpecError):
        simulate(spec, {"enabled": True, "threshold_cents": 500, "face_value_cents": 500})
    with pytest.raises(SpecError):
        simulate(spec, {"enabled": True, "threshold_cents": 15900, "face_value_cents": 0})
    with pytest.raises(SpecError):
        simulate(spec, {"enabled": True, "threshold_cents": 5000, "face_value_cents": -100})
    # 非整数分金额在载入层阻断
    with pytest.raises(SpecError):
        load_spec({"baseline": {"visitors": 100, "conversion_rate": 0.1,
                                "baskets": [{"amount_cents": 100.5, "weight": 1.0}]},
                   "candidates": [], "cost": {}, "behavior": {}})


# ---------- 4.6 拆解与 ΔΠ 对平 ----------

@pytest.mark.parametrize("t,f", [(15900, 500), (15900, 1000), (13900, 2000), (9900, 1000), (7900, 500)])
def test_decomposition_sums_to_delta(t, f):
    spec = build_synthetic_spec()
    res = simulate(spec, {"enabled": True, "threshold_cents": t, "face_value_cents": f})
    d = res.decomposition
    total = (d["natural_redemption"] + d["topup"] + d["other_retained"]
             + d["lost_orders"] + d["new_orders"] + d["fixed_costs"])
    assert abs(total - res.metrics["incremental_contribution_cents"]) <= TOL_CENTS


def test_validate_spec_reports_weight_and_probability_issues():
    data = build_synthetic_spec().to_dict()
    data["baseline"]["baskets"][0]["weight"] = 0.5  # 权重和 ≠ 1
    data["behavior"]["redeem_natural"] = 1.5        # 非法概率
    result = validate_spec(load_spec(data, strict=False))
    assert any("权重" in e for e in result["errors"])
    assert any("概率" in e for e in result["errors"])


def test_engine_version_stamped():
    spec = build_synthetic_spec()
    res = simulate(spec, {"enabled": False, "threshold_cents": None, "face_value_cents": 0})
    assert res.engine_version == ENGINE_VERSION
