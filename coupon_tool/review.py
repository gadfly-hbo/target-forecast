# -*- coding: utf-8 -*-
"""轻量复盘（提案 §9.2/9.3、门禁 D）：预测 vs 实际 → 偏差分类 → 人工确认 → 参数新版本。

顺序固定：先口径核查，再对比，再讨论参数。参数更新需人工确认，旧版本不可变；
预测误差不自动写回；描述性对比不升级为因果结论。
"""
from __future__ import annotations

import copy
import json
import os
from datetime import datetime, timezone

DEVIATION_CATEGORIES = [
    "流量偏差", "基准转化偏差", "客单结构偏差", "触达/核销偏差",
    "加购/流失假设偏差", "成本/结算偏差", "未识别剩余差异",
]

_REQUIRED_ACTUALS = ("orders", "gmv_pre_cents", "merchant_subsidy_cents", "window")
_METRIC_KEYS = [
    ("orders", "订单数"),
    ("conversion_rate", "最终转化率"),
    ("gmv_pre_cents", "券前 GMV（分）"),
    ("gmv_paid_cents", "客户支付商品额（分）"),
    ("merchant_subsidy_cents", "商家券补（分）"),
    ("redemptions", "核销量"),
]


def _caliber_checks(actuals: dict, run: dict) -> list[str]:
    """先核对口径：窗口、单位与缺失声明。返回待确认问题（不阻断，但必须可见）。"""
    issues = []
    n = run["scenario"]["baseline"].get("visitors")
    if n and actuals.get("orders", 0) > n * 1.0:
        issues.append(f"实际订单数 {actuals['orders']} 超过场景 N={n}：观察单位口径可能不一致（订单≠用户）")
    if actuals.get("window") and run["scenario"].get("window", {}).get("days"):
        pass  # 窗口文本比对属人工确认；此处只要求字段在
    if not actuals.get("refund_handling"):
        issues.append("实际值未声明退款口径：预测为未扣退款口径，比较前先确认实际口径一致")
    return issues


def _resolve_chosen(store, run: dict, chosen_label: str | None) -> tuple[dict | None, str]:
    """预测基准优先级：显式选择 > 决策记录 > 排序第一（§8.3 人工选择可不与排序一致）。"""
    rows = {r["label"]: r for r in run["results"]["rows"] if r.get("metrics")}
    decision = None
    dpath = os.path.join(store.root, "decisions", f"{run['run_id']}.json")
    if os.path.exists(dpath):
        with open(dpath, encoding="utf-8") as fh:
            decision = json.load(fh)
    label = chosen_label or (decision or {}).get("choice")
    if label == "暂不发券":
        nc = next((r for r in run["results"]["rows"]
                   if not r["candidate"].get("enabled") and r.get("metrics")), None)
        return (nc, "decision") if nc else (None, "none")
    elif label == "暂不决策":
        label = None
    if label in rows:
        source = "explicit" if chosen_label else ("decision" if decision else "ranking_default")
        return rows[label], source
    ranking = run["results"].get("ranking") or []
    if ranking and ranking[0] in rows:
        return rows[ranking[0]], "ranking_default"
    return None, "none"


def create_review(store, run_id: str, actuals: dict, notes: dict,
                  confirmed_by: str = "", params_patch: dict | None = None,
                  chosen_label: str | None = None) -> dict:
    run = store.load_run(run_id)
    missing = [k for k in _REQUIRED_ACTUALS if actuals.get(k) in (None, "")]
    if missing:
        raise ValueError(f"实际结果缺少必填字段：{', '.join(missing)}")
    for k in ("orders", "gmv_pre_cents", "gmv_paid_cents", "merchant_subsidy_cents", "redemptions"):
        if k in actuals and actuals[k] is not None and actuals[k] < 0:
            raise ValueError(f"实际值 {k} 不能为负")

    top, chosen_source = _resolve_chosen(store, run, chosen_label)
    if top is None:
        raise ValueError("该运行无可比候选（结论=无可行/无效比较），先复盘输入再对比实际")
    m = top["metrics"]
    n = run["scenario"]["baseline"].get("visitors") or 1

    predicted = {
        "orders": m["orders"],
        "conversion_rate": m["conversion_rate"],
        "gmv_pre_cents": m["gmv_pre_cents"],
        "gmv_paid_cents": m["gmv_paid_cents"],
        "merchant_subsidy_cents": m["merchant_subsidy_cents"],
        "redemptions": m["natural_redemptions"] + m["topup_redemptions"],
    }
    diffs = []
    for key, label in _METRIC_KEYS:
        pred, act = predicted.get(key), actuals.get(key)
        if pred is None or act is None:
            continue
        diffs.append({
            "metric": key, "metric_label": label,
            "predicted": pred, "actual": act,
            "diff": act - pred,
            "pct": (act - pred) / pred if pred else None,
        })

    param_version = None
    if params_patch:
        data = copy.deepcopy(run["scenario"])
        for path, value in params_patch.items():
            node = data
            keys = path.split(".")
            for k in keys[:-1]:
                node = node[k]
            node[keys[-1]] = value
        base_id = run["scenario"]["scenario_id"]
        existing = [sid for sid in _scenario_ids(store)
                    if sid == base_id or sid.startswith(base_id + "-v")]
        new_id = f"{base_id}-v{len(existing)}" if existing else f"{base_id}-v2"
        data["scenario_id"] = new_id
        data.setdefault("parameter_sources", {})
        data["parameter_sources"][f"review:{run_id}"] = {
            "source_type": "historical_descriptive",
            "note": f"复盘参数新版本（来自运行 {run_id}，人工确认：{confirmed_by or '未署名'}）",
        }
        from .spec import load_spec
        store.save_spec(load_spec(data), name=new_id)
        param_version = {"scenario_id": new_id, "changes": params_patch,
                         "confirmed_by": confirmed_by}

    review = {
        "review_id": f"review-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%f')}",
        "run_id": run_id,
        "created_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "selected_label": top["label"],
        "chosen_source": chosen_source,
        "predicted": predicted,
        "actuals": actuals,
        "diffs": diffs,
        "caliber_checks": _caliber_checks(actuals, run),
        "deviation_notes": {c: notes.get(c, "") for c in DEVIATION_CATEGORIES if notes.get(c)},
        "parameter_new_version": param_version,
        "confirmed_by": confirmed_by,
        "causal_claim": False,  # 门禁 D：描述性对比 ≠ 因果结论；无对照时不识别真实增量
    }
    store.save_review(run_id, review)
    return review


def _scenario_ids(store) -> list[str]:
    sc_dir = os.path.join(store.root, "scenarios")
    if not os.path.exists(sc_dir):
        return []
    return sorted(p[:-5] for p in os.listdir(sc_dir) if p.endswith(".json"))
