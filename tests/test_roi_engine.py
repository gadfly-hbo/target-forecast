"""roi_tool 引擎黄金案例与不变量测试。

黄金值全部手工算定：
  计划A（正）：spend=10000 cpc=2 cvr=0.05 aov=200 margin=0.4 refund=0.1
    clicks=5000 orders=250 GMV=50000 net=50000×0.9×0.4−10000=8000 ROI=5.0
    cvr_star=2/(200×0.9×0.4)=2/72=1/36≈0.027778
  计划B（亏）：spend=20000 cpc=1.5 cvr=0.02 aov=150 margin=0.3 refund=0.15
    clicks=13333.333 orders=266.667 GMV=40000 net=40000×0.85×0.3−20000=−9800 ROI=2.0
    cvr_star=1.5/(150×0.85×0.3)=1.5/38.25≈0.0392157
  计划C（边界）：spend=5000 cpc=1 cvr=0.028 aov=100 margin=0.35 refund=0.1
    clicks=5000 orders=140 GMV=14000 net=14000×0.315−5000=−590 ROI=2.8
    cvr_star=1/(100×0.9×0.35)=1/31.5≈0.031746
    挑战(+20%, cvr与aov同调): cvr=0.0336 aov=120 orders=168 GMV=20160 net=20160×0.315−5000=+1350.4 → 转正
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from roi_tool import demo, engine  # noqa: E402

PLAN_A = {"name": "计划A", "spend_cny": 10000, "cpc_cny": 2, "cvr": 0.05,
          "aov_cny": 200, "gross_margin": 0.4, "refund_rate": 0.1}
PLAN_B = {"name": "计划B", "spend_cny": 20000, "cpc_cny": 1.5, "cvr": 0.02,
          "aov_cny": 150, "gross_margin": 0.3, "refund_rate": 0.15}
PLAN_C = {"name": "计划C", "spend_cny": 5000, "cpc_cny": 1, "cvr": 0.028,
          "aov_cny": 100, "gross_margin": 0.35, "refund_rate": 0.1}

DEFAULT_SCENARIOS = {"保守": {"cvr_growth": -0.2, "aov_growth": -0.2},
                     "基准": {"cvr_growth": 0.0, "aov_growth": 0.0},
                     "挑战": {"cvr_growth": 0.2, "aov_growth": 0.2}}


def _plan(res, scenario, name):
    return next(p for p in res["scenarios"][scenario]["plans"] if p["name"] == name)


def test_golden_plan_a_positive():
    res = engine.evaluate([PLAN_A], DEFAULT_SCENARIOS)
    a = _plan(res, "基准", "计划A")
    assert a["clicks"] == pytest.approx(5000)
    assert a["orders"] == pytest.approx(250)
    assert a["gmv"] == pytest.approx(50000)
    assert a["net"] == pytest.approx(8000)
    assert a["roi"] == pytest.approx(5.0)
    assert a["cvr_star"] == pytest.approx(1 / 36)
    assert a["verdict"] == "净贡献为正"
    assert a["below_breakeven"] is False


def test_golden_plan_b_negative():
    res = engine.evaluate([PLAN_B], DEFAULT_SCENARIOS)
    b = _plan(res, "基准", "计划B")
    assert b["gmv"] == pytest.approx(40000)
    assert b["net"] == pytest.approx(-9800)
    assert b["roi"] == pytest.approx(2.0)
    assert b["cvr_star"] == pytest.approx(1.5 / 38.25)
    assert b["verdict"] == "净亏损"
    assert b["below_breakeven"] is True


def test_golden_plan_c_challenge_turns_positive():
    """挑战情景 cvr 与 aov 同时 +20%：cvr=0.0336 aov=120。"""
    res = engine.evaluate([PLAN_C], DEFAULT_SCENARIOS)
    c_base = _plan(res, "基准", "计划C")
    c_up = _plan(res, "挑战", "计划C")
    assert c_base["net"] == pytest.approx(-590)
    assert c_base["verdict"] == "净亏损"
    assert c_up["gmv"] == pytest.approx(5000 * 0.0336 * 120)  # 20160
    assert c_up["net"] == pytest.approx(20160 * 0.315 - 5000)  # 1350.4
    assert c_up["verdict"] == "净贡献为正"


def test_breakeven_invariant_net_is_zero():
    """cvr = cvr_star 时净毛利必须 ≈ 0（引擎核心不变量）。"""
    p = dict(PLAN_A, cvr=1 / 36)
    res = engine.evaluate([p], {"基准": {"cvr_growth": 0.0, "aov_growth": 0.0}})
    assert _plan(res, "基准", "计划A")["net"] == pytest.approx(0.0, abs=1e-6)


def test_scenario_monotonicity():
    res = engine.evaluate([PLAN_C], DEFAULT_SCENARIOS)
    nets = [res["scenarios"][s]["plans"][0]["net"] for s in ("保守", "基准", "挑战")]
    assert nets[0] <= nets[1] <= nets[2]


def test_totals_and_ranking():
    res = engine.evaluate([PLAN_A, PLAN_B], DEFAULT_SCENARIOS)
    base = res["scenarios"]["基准"]
    assert base["totals"]["spend"] == pytest.approx(30000)
    assert base["totals"]["gmv"] == pytest.approx(90000)
    assert base["totals"]["net"] == pytest.approx(-1800)
    assert base["ranking"] == ["计划A", "计划B"]  # 按 net 降序


def test_validation_matrix():
    bad_cases = [
        ({**PLAN_A, "spend_cny": 0}, "spend_cny"),
        ({**PLAN_A, "spend_cny": -1}, "spend_cny"),
        ({**PLAN_A, "cpc_cny": 0}, "cpc_cny"),
        ({**PLAN_A, "cvr": 0}, "cvr"),
        ({**PLAN_A, "cvr": 1.5}, "cvr"),
        ({**PLAN_A, "aov_cny": 0}, "aov_cny"),
        ({**PLAN_A, "gross_margin": 0}, "gross_margin"),
        ({**PLAN_A, "gross_margin": 1.2}, "gross_margin"),
        ({**PLAN_A, "refund_rate": -0.1}, "refund_rate"),
        ({**PLAN_A, "refund_rate": 1.0}, "refund_rate"),
    ]
    for plan, field in bad_cases:
        with pytest.raises(engine.PlanError, match=field):
            engine.evaluate([plan], DEFAULT_SCENARIOS)


def test_validation_reports_plan_name():
    with pytest.raises(engine.PlanError, match="计划X"):
        engine.evaluate([{**PLAN_A, "name": "计划X", "cvr": 2}], DEFAULT_SCENARIOS)


def test_demo_plans_are_synthetic_and_valid():
    plans = demo.build_demo_plans()
    assert len(plans) == 4
    res = engine.evaluate(plans, DEFAULT_SCENARIOS)  # 不抛 = 全部合法
    assert set(res["scenarios"]) == {"保守", "基准", "挑战"}
    meta = demo.demo_meta()
    assert meta["synthetic"] is True and meta["demo_used"] is True


def test_demo_plans_match_g1_narrative():
    """GRILL G1 行为意图（review round 1 blocker）：演示集的教学叙述必须真实。

    ① 搜索型基准稳赚；② 信息流基准亏挑战转正（情景敏感）；③ 站内基准贴边
    （|net| ≤ 100）；④ 高客单基准亏挑战转正。跨情景结论稳定性字段如实标注翻转。
    """
    res = demo.evaluate_demo()

    def net(name, sc):
        return next(p["net"] for p in res["scenarios"][sc]["plans"] if p["name"] == name)

    assert net("天猫直通车-搜索", "基准") > 0                      # ① 稳赚
    assert net("抖音千川-信息流", "基准") < 0                      # ② 量大利薄
    assert net("抖音千川-信息流", "挑战") > 0                      # ② 情景敏感
    assert abs(net("京东快车-站内", "基准")) <= 100               # ③ 基准贴边
    assert net("小红书聚光-种草", "基准") < 0                      # ④ 基准亏
    assert net("小红书聚光-种草", "挑战") > 0                      # ④ 挑战转正

    stab = res["stability"]
    assert stab["天猫直通车-搜索"]["stable"] is True               # 三档同号
    assert stab["抖音千川-信息流"]["stable"] is False              # 结论翻转
    assert stab["小红书聚光-种草"]["stable"] is False
    assert set(stab["小红书聚光-种草"]["verdicts"]) == {"保守", "基准", "挑战"}
