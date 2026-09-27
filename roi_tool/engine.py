# -*- coding: utf-8 -*-
"""投放 ROI 测算引擎：纯函数，无 IO。

链路（单计划）：
    点击   = 消耗 ÷ CPC
    订单   = 点击 × CVR
    GMV    = 订单 × 客单
    净毛利 = GMV × (1−退款率) × 毛利率 − 消耗
    ROI    = GMV ÷ 消耗
    盈亏平衡 CVR* = CPC ÷ (客单 × (1−退款率) × 毛利率)

情景对 CVR 与客单施加增速，其余参数平推。不合法输入抛 PlanError（字段名在消息中）。
"""
from __future__ import annotations

REQUIRED_FIELDS = ("name", "spend_cny", "cpc_cny", "cvr", "aov_cny", "gross_margin", "refund_rate")


class PlanError(ValueError):
    """计划参数不合法；消息携带计划名与字段名。"""


def validate_plan(plan: dict) -> None:
    name = plan.get("name", "未命名计划")
    for f in REQUIRED_FIELDS:
        if f not in plan or plan[f] in (None, ""):
            raise PlanError(f"{name}: 缺少字段 {f}")
    checks = [
        ("spend_cny", plan["spend_cny"] > 0, "消耗必须 > 0"),
        ("cpc_cny", plan["cpc_cny"] > 0, "CPC 必须 > 0"),
        ("cvr", 0 < plan["cvr"] < 1, "转化率必须在 (0, 1) 内"),
        ("aov_cny", plan["aov_cny"] > 0, "客单价必须 > 0"),
        ("gross_margin", 0 < plan["gross_margin"] < 1, "毛利率必须在 (0, 1) 内"),
        ("refund_rate", 0 <= plan["refund_rate"] < 1, "退款率必须在 [0, 1) 内"),
    ]
    for field, ok, msg in checks:
        if not ok:
            raise PlanError(f"{name}: {field} {msg}（当前值 {plan[field]}）")


def _eval_plan(plan: dict, cvr_growth: float, aov_growth: float) -> dict:
    cvr = plan["cvr"] * (1 + cvr_growth)
    aov = plan["aov_cny"] * (1 + aov_growth)
    spend, cpc = plan["spend_cny"], plan["cpc_cny"]
    keep = (1 - plan["refund_rate"]) * plan["gross_margin"]

    clicks = spend / cpc
    orders = clicks * cvr
    gmv = orders * aov
    net = gmv * keep - spend
    cvr_star = cpc / (aov * keep)
    return {
        "name": plan["name"],
        "spend": round(spend, 2),
        "clicks": round(clicks, 1),
        "orders": round(orders, 1),
        "cvr": round(cvr, 6),
        "aov": round(aov, 2),
        "gmv": round(gmv, 2),
        "net": round(net, 2),
        "roi": round(gmv / spend, 4),
        # 精度字段不舍入：舍入会破坏与精确分数的比对及盈亏平衡不变量
        "cvr_star": cvr_star,
        "gap": cvr_star - cvr,
        "below_breakeven": cvr < cvr_star,
        "verdict": "净贡献为正" if net > 0 else "净亏损",
    }


def evaluate(plans: list[dict], scenarios: dict[str, dict]) -> dict:
    """测算：plans 全量校验后对每档情景求值，输出每计划明细 + 汇总 + 排名。"""
    if not plans:
        raise PlanError("至少需要 1 个投放计划")
    for p in plans:
        validate_plan(p)
    if not scenarios:
        raise PlanError("至少需要 1 档情景")

    out = {"scenarios": {}}
    for sname, s in scenarios.items():
        cvr_growth = float(s.get("cvr_growth", 0.0))
        aov_growth = float(s.get("aov_growth", 0.0))
        evaluated = [_eval_plan(p, cvr_growth, aov_growth) for p in plans]
        totals = {
            "spend": round(sum(p["spend_cny"] for p in plans), 2),
            "gmv": round(sum(e["gmv"] for e in evaluated), 2),
            "net": round(sum(e["net"] for e in evaluated), 2),
        }
        out["scenarios"][sname] = {
            "growth": {"cvr_growth": cvr_growth, "aov_growth": aov_growth},
            "plans": evaluated,
            "totals": totals,
            "ranking": [e["name"] for e in sorted(evaluated, key=lambda e: e["net"], reverse=True)],
        }

    # 跨情景结论稳定性（PRD D2）：某计划在三档下净贡献符号是否一致
    stability = {}
    for idx, p in enumerate(plans):
        nets = [out["scenarios"][sname]["plans"][idx]["net"] for sname in scenarios]
        stability[p["name"]] = {
            "verdicts": {sname: out["scenarios"][sname]["plans"][idx]["verdict"] for sname in scenarios},
            "stable": all(n > 0 for n in nets) or all(n <= 0 for n in nets),
        }
    out["stability"] = stability
    return out
