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


def ingest_platforms(detail: dict, agg: dict, caliber: dict) -> dict:
    """模式 A/B 输入 → 统一月度指标层（只 ingest 不算引擎；server 直接缓存此返回）。"""
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


def run_engine(platforms: dict, scenarios: dict, caliber: dict) -> dict:
    """逐平台跑引擎（保持 platforms 插入序）；results 带 unified 供 main.py 落盘中间指标。"""
    return {p: {"mode": v["mode"], "unified": v["unified"],
                **engine.run(v["unified"], v["structure"], scenarios, caliber)}
            for p, v in platforms.items()}


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
