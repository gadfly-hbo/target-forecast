# -*- coding: utf-8 -*-
"""测算流水线编排的单一事实源：scan → ingest → engine → views。

main.py（CLI 一次性流程）与 server.py（工作台缓存 + 懒算）共用本模块：
- server 的 `WorkbenchState.load` 只共享 ingest 半段（缓存 unified/structure，引擎在 calc 懒算）；
- main.py 的 `run_flow` 走全四段。

caliber 不对称（刻意保留，勿"修正"）：main.py 壳对 `cfg["caliber"]` 原地变异加入
`target_months`——`report.write_report` 的 07_参数 sheet 遍历 `cfg["caliber"]`，
该行靠此副作用存在；server.calc 用拷贝式 `{**cfg["caliber"], ...}`，不污染共享 cfg。
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd

from . import aggregate, engine, ingest_agg, ingest_detail, report


def scan_inputs(root: Path) -> tuple[dict, dict]:
    """扫描 workspace/forecast 的 orders（模式A明细）与 metrics（模式B聚合）输入。

    只扫描；空输入策略（CLI sys.exit / 工作台自动生成 demo）由调用方各自决定。
    """
    def scan(d: Path) -> dict:
        if not d.exists():
            return {}
        return {p.stem: p for p in sorted(d.glob("*.xlsx")) if not p.name.startswith("~$")}

    base = Path(root) / "workspace" / "forecast"
    return scan(base / "orders"), scan(base / "metrics")


class InputConflictError(ValueError):
    """同一平台同时存在模式A（订单明细）与模式B（月度指标）输入且未显式选源。"""


class JobCancelled(Exception):
    """计算任务被用户停止：不写半结果。"""


def detect_conflicts(detail: dict, agg: dict) -> list:
    """同时出现在两种输入中的平台名（同名 A/B 冲突清单）。"""
    return sorted(set(detail) & set(agg))


def ingest_platforms(detail: dict, agg: dict, caliber: dict, source_choice: dict | None = None) -> dict:
    """模式 A/B 输入 → 统一月度指标层（只 ingest 不算引擎；server 直接缓存此返回）。

    同平台 A/B 冲突不得静默覆盖：未提供 source_choice 时抛 InputConflictError；
    source_choice={平台: "A"|"B"} 时按用户显式选择 ingest，被放弃的来源不参与。
    """
    conflicts = detect_conflicts(detail, agg)
    unresolved = [p for p in conflicts
                  if not source_choice or source_choice.get(p) not in ("A", "B")]
    if unresolved:
        raise InputConflictError(
            "同一平台同时存在订单明细与月度指标两种输入，请显式选择每个平台的来源: "
            + "、".join(unresolved))
    if conflicts:
        drop_from_agg = {p for p in conflicts if source_choice[p] == "A"}
        drop_from_detail = {p for p in conflicts if source_choice[p] == "B"}
        agg = {k: v for k, v in agg.items() if k not in drop_from_agg}
        detail = {k: v for k, v in detail.items() if k not in drop_from_detail}

    platforms = {}
    for platform, path in detail.items():
        lines = ingest_detail.load_detail(path, platform)
        od = ingest_detail.classify_new(ingest_detail.order_level(lines),
                                        caliber["new_customer_window_days"])
        unified = ingest_detail.to_unified(od, platform)
        structure = ingest_detail.goods_structure(lines, caliber, lines["日期"].max())
        platforms[platform] = {"mode": "A", "unified": unified, "structure": structure}
    for platform, path in agg.items():
        df = ingest_agg.load_agg(path, platform)
        platforms[platform] = {"mode": "B", "unified": ingest_agg.to_unified(df, platform),
                               "structure": None}
    return platforms


def _coverage(unified: pd.DataFrame, common_end) -> dict:
    """平台覆盖事实：历史区间、区间内缺月、相对共同末月的缺口、短历史标记。"""
    months = [str(m) for m in unified["month"]] if len(unified) else []
    trailing: list = []
    if months and common_end is not None:
        own_end = pd.Period(max(months), freq="M")
        if own_end < common_end:
            trailing = [str(m) for m in pd.period_range(own_end + 1, common_end, freq="M")]
    missing: list = []
    if months:
        have = set(months)
        missing = [str(m) for m in pd.period_range(min(months), max(months), freq="M")
                   if str(m) not in have]
    return {"history_months": len(months),
            "history_start": min(months) if months else None,
            "history_end": max(months) if months else None,
            "trailing_gap": trailing, "missing_months": missing,
            "short_history": len(months) < 12}


def run_engine(platforms: dict, scenarios: dict, caliber: dict, should_cancel=None) -> dict:
    """逐平台跑引擎（保持 platforms 插入序）；results 带 unified 供 main.py 落盘中间指标。

    目标期多平台对齐：共同基期末月 = 各平台历史末月的最大值，目标期为其后连续
    target_months 个月；历史末月早于共同末月的平台在 coverage.trailing_gap 如实标记，
    不静默错配（由上层决定缩短范围或排除平台，需用户确认）。
    should_cancel：可选可调用，每个平台计算前检查，为真则抛 JobCancelled（不写半结果）。
    """
    n_months = caliber.get("target_months", 12)
    ends = [pd.Period(v["unified"]["month"].max(), freq="M")
            for v in platforms.values() if len(v["unified"])]
    common_end = max(ends) if ends else None
    target_months = (pd.period_range(common_end + 1, periods=n_months, freq="M")
                     if common_end is not None else None)
    out = {}
    for p, v in platforms.items():
        if should_cancel is not None and should_cancel():
            raise JobCancelled()
        r = engine.run(v["unified"], v["structure"], scenarios, caliber,
                       target_months=target_months)
        r["coverage"] = _coverage(v["unified"], common_end)
        out[p] = {"mode": v["mode"], "unified": v["unified"], **r}
    return out


def build_views(results: dict) -> dict:
    """三视角 concat + 汇总视图；返回 consolidated/platform_annual/check/goods/baselines 五键。"""
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
    baselines = {p: r["baseline"] for p, r in results.items()}
    return {
        "consolidated": aggregate.consolidate(person_all, main_all, field_all),
        "platform_annual": aggregate.platform_annual(main_all, baselines),
        "check": report._build_check_sheet(results),
        "goods": report._build_goods_sheet(results),
        "baselines": baselines,
    }
