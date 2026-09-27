# -*- coding: utf-8 -*-
"""三格式导出（提案 §8.3/8.4）：Markdown 决策摘要、CSV 逐候选/逐分支、JSON 运行记录。

所有导出带场景版本、参数来源、引擎版本与运行 ID；金额列以分为单位（内部口径）。
"""
from __future__ import annotations

import csv
import json
import os

CANDIDATE_COLUMNS = [
    "券组合", "证据状态", "最终转化率", "净转化变化", "原有人群流失", "毛新增订单",
    "自然核销量", "加购核销量", "商家补贴分", "总贡献分", "增量贡献分", "净增量ROI",
    "约束状态",
]

LEDGER_COLUMNS = [
    "券组合", "人群类型", "基准篮子", "结果分支", "概率", "期望订单数", "券前金额分",
    "客户实付分", "核销", "商家券补分", "平台券补分", "商品毛利分", "可变费用分",
    "退货调整分", "贡献分",
]


def _roi_str(roi):
    return "不适用" if roi is None else f"{roi:.4f}"


def export_candidates_csv(run: dict, path: str) -> str:
    evidence = run["scenario"].get("evidence_status", "")
    with open(path, "w", newline="", encoding="utf-8-sig") as fh:
        writer = csv.writer(fh)
        writer.writerow(CANDIDATE_COLUMNS)
        for row in run["results"]["rows"]:
            m = row["metrics"]
            if m is None:
                writer.writerow([row["label"], evidence] + ["—"] * (len(CANDIDATE_COLUMNS) - 3)
                                + ["；".join(v["message"] for v in row["violations"])])
                continue
            writer.writerow([
                row["label"], evidence, f"{m['conversion_rate']:.6f}",
                f"{m['delta_c']:.6f}", f"{m['churn_rate']:.6f}",
                f"{m['new_orders']:.2f}", f"{m['natural_redemptions']:.2f}",
                f"{m['topup_redemptions']:.2f}", f"{m['merchant_subsidy_cents']:.0f}",
                f"{m['total_contribution_cents']:.0f}",
                f"{m['incremental_contribution_cents']:.0f}",
                _roi_str(m["roi"]),
                "可行" if row["feasible"] else "；".join(v["message"] for v in row["violations"]),
            ])
    return path


def export_ledger_csv(run: dict, path: str) -> str:
    """逐候选 × 逐分支账本（来自运行记录中的封存账本，与界面/JSON 同源）。"""
    with open(path, "w", newline="", encoding="utf-8-sig") as fh:
        writer = csv.writer(fh)
        writer.writerow(LEDGER_COLUMNS)
        for row in run["results"]["rows"]:
            for entry in row.get("ledger") or []:
                writer.writerow([
                    row["label"], entry["group"], entry["basket"], entry["branch"],
                    f"{entry['probability']:.6f}", f"{entry['expected_orders']:.4f}",
                    f"{entry['amount_cents']:.0f}", f"{entry['customer_paid_cents']:.0f}",
                    entry["redeemed"], f"{entry['merchant_subsidy_cents']:.0f}",
                    f"{entry['platform_subsidy_cents']:.0f}", f"{entry['gross_margin_cents']:.0f}",
                    f"{entry['variable_fee_cents']:.0f}", f"{entry['return_adj_cents']:.0f}",
                    f"{entry['contribution_cents']:.0f}",
                ])
    return path


def export_json(run: dict, path: str) -> str:
    payload = {k: v for k, v in run.items() if not k.startswith("_")}
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, ensure_ascii=False, indent=2)
    return path


def export_markdown(run: dict, path: str, decision: dict | None = None) -> str:
    sc = run["scenario"]
    results = run["results"]
    ranking = results.get("ranking_rows") or []
    top = ranking[0] if ranking else None
    lines: list[str] = []
    add = lines.append

    add("# 优惠券测算决策摘要")
    add("")
    add(f"- 场景：{sc.get('scenario_id')}　场景版本：{sc.get('schema_version')}　运行 ID：`{run['run_id']}`")
    add(f"- 引擎版本：{run['engine_version']}　证据状态：{sc.get('evidence_status')}")
    add(f"- 结论类型：{results['conclusion']['type']}——{results['conclusion']['message']}")
    add("")
    if top is not None:
        m = top["metrics"]
        add("## 基准排序首选（条件性建议，非全局最优）")
        add("")
        add(f"- 券组合：**{top['label']}**"
            + ("（受控亏损）" if top.get("controlled_loss") else ""))
        add(f"- 相对无券的增量贡献：{m['incremental_contribution_cents'] / 100:.2f} 元")
        add(f"- 商家预计券补：{m['merchant_subsidy_cents'] / 100:.2f} 元")
        add(f"- 转化变化：{(m['delta_c']) * 100:.4f} 个百分点（相对变化 "
            f"{m['delta_c'] / sc['baseline']['conversion_rate'] * 100 if sc['baseline']['conversion_rate'] else 0:.2f}%）")
        add(f"- 净增量 ROI：{_roi_str(m['roi'])}")
        add("")
        be = top.get("breakeven")
        add("### 回本条件")
        if be:
            if be.get("nonpositive_pi_new"):
                add(f"- {be.get('note', '')}")
            else:
                add(f"- 所需毛新增成交率 ΔC⁺ = {be['d_c_plus_be']:.4%}（对应最终转化率 "
                    f"{be['c_be']:.4%}，净变化 {be['delta_c_be'] * 100:.4f} pp）")
                add(f"- 可触达非购买者上限：{be['reachable_cap']:.4%}——"
                    + ("未超限" if be["within_reachable_cap"] else "**超过上限：当前假设下不可回本**"))
                add(f"- 该新增量下商家券补：{(be.get('merchant_subsidy_at_be_cents') or 0) / 100:.2f} 元，"
                    + ("预算内" if be.get("budget_ok_at_be") else "**超预算**"))
        else:
            add("- （该候选为无券基准或不可行，无回本条件）")
        add("")
        add("### 收益来自（与总 ΔΠ 对平）")
        d = top.get("decomposition") or {}
        if d:
            for key, name in [("natural_redemption", "自然核销影响"), ("topup", "加购"),
                              ("other_retained", "其他保留成交"), ("lost_orders", "流失订单损失"),
                              ("new_orders", "新增成交"), ("fixed_costs", "新增固定费用")]:
                add(f"- {name}：{d.get(key, 0) / 100:.2f} 元")
        add("")
        add("### 邻近候选与未选原因")
        if top.get("neighbors"):
            for nb in top["neighbors"]:
                add(f"- {nb['label']}：{'可行' if nb['feasible'] else '被过滤——' + (nb['filtered_reason'] or '')}")
        else:
            add("- （无相邻候选）")
        add("")
    stress = run.get("stress")
    add("### 最敏感假设与不利情景")
    if stress and stress.get("sensitive_params"):
        p = stress["sensitive_params"][0]
        add(f"- 最敏感参数：{p['param']}（ΔΠ 极差 {p['delta_pi_spread_cents'] / 100:.2f} 元）")
        selected = stress["baseline"].get("selected_label")
        worst = None
        for sc2 in stress["scenarios"]:
            for row in sc2["rows"]:
                if row["label"] == selected and (worst is None or row["delta_pi_cents"] < worst[1]):
                    worst = (sc2["name"], row["delta_pi_cents"])
        if worst:
            add(f"- 不利情景：{worst[0]} 下所选方案 ΔΠ = {worst[1] / 100:.2f} 元"
                + ("（转负）" if worst[1] < 0 else ""))
    else:
        add("- （本次运行未配置敏感性情景——压力结论缺失，不能视为稳健）")
    add("")
    add("### 已知限制")
    for lim in (top.get("limitations") if top else None) or []:
        add(f"- {lim}")
    add("")
    add("### 人工确认")
    if decision:
        add(f"- 选择：{decision.get('choice')}")
        add(f"- 确认依据 / 未采纳模型排序的原因：{decision.get('reason', '（待填）')}")
        add(f"- 确认人 / 时间：{decision.get('confirmed_by', '')} / {decision.get('confirmed_at', '')}")
    else:
        add("- 选择：____（方案 / 暂不发券 / 暂不决策）")
        add("- 确认依据 / 未采纳模型排序的原因：____")
        add("> 人工选择不要求与排序第一一致，但必须保留理由；人工确认只代表业务选择，不代表模型被实验验证。")
    add("")
    add("---")
    add("*本摘要由确定性引擎生成；所有数字可经运行记录 JSON 重放复核。合成参数与演示结果不是真实经营证据。*")
    with open(path, "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines))
    return path


def export_all(run: dict, out_dir: str = "workspace/coupon/output", decision: dict | None = None) -> dict:
    os.makedirs(out_dir, exist_ok=True)
    rid = run["run_id"]
    paths = {
        "markdown": export_markdown(run, os.path.join(out_dir, f"{rid}_决策摘要.md"), decision),
        "csv_candidates": export_candidates_csv(run, os.path.join(out_dir, f"{rid}_候选表.csv")),
        "csv_ledger": export_ledger_csv(run, os.path.join(out_dir, f"{rid}_分支账本.csv")),
        "json": export_json(run, os.path.join(out_dir, f"{rid}_运行记录.json")),
    }
    return paths
