#!/usr/bin/env python3
"""零售目标测算 · 命令行入口。

用法：
    .venv/bin/python main.py demo       # 生成演示数据并跑通全流程（首次体验用）
    .venv/bin/python main.py run        # 用 data/ 下的正式数据测算
    .venv/bin/python main.py serve      # 启动本地 HTML 工作台（--port 指定端口）
    .venv/bin/python main.py templates  # 重新生成输入模板
"""

from __future__ import annotations

import argparse
import sys
import warnings
from pathlib import Path

import pandas as pd
import yaml

from target_forecast import aggregate, demo, engine, ingest_agg, ingest_detail, report, server, templates

ROOT = Path(__file__).resolve().parent
OUT_DIR = ROOT / "output"


def load_cfg() -> dict:
    with open(ROOT / "config.yaml", encoding="utf-8") as f:
        return yaml.safe_load(f)


def _collect_inputs() -> tuple[dict, dict]:
    def scan(d: Path):
        return {p.stem: p for p in sorted(d.glob("*.xlsx")) if not p.name.startswith("~$")} if d.exists() else {}
    return scan(ROOT / "data" / "orders"), scan(ROOT / "data" / "metrics")


def run_flow(cfg: dict, demo_flag: bool) -> None:
    detail_files, agg_files = _collect_inputs()
    if not detail_files and not agg_files:
        sys.exit("data/orders 与 data/metrics 下没有任何 xlsx 输入文件。先运行 `main.py demo` 或按 templates/ 模板填数。")

    caliber = cfg["caliber"]
    caliber["target_months"] = cfg["target"]["months"]
    results = {}

    for platform, path in detail_files.items():
        print(f"[{platform}] 模式A 明细测算 …", end=" ")
        lines = ingest_detail.load_detail(path, platform)
        od = ingest_detail.classify_new(ingest_detail.order_level(lines), caliber["new_customer_window_days"])
        unified = ingest_detail.to_unified(od, platform)
        structure = ingest_detail.goods_structure(lines, caliber, lines["日期"].max())
        results[platform] = {"mode": "A", "unified": unified, **engine.run(unified, structure, cfg["scenarios"], caliber)}
        print(f"历史 {unified['month'].min()}~{unified['month'].max()} 共{len(unified)}月 · 主口径[{results[platform]['main_view']}]")

    for platform, path in agg_files.items():
        print(f"[{platform}] 模式B 聚合测算 …", end=" ")
        df = ingest_agg.load_agg(path, platform)
        unified = ingest_agg.to_unified(df, platform)
        results[platform] = {"mode": "B", "unified": unified, **engine.run(unified, None, cfg["scenarios"], caliber)}
        print(f"历史 {unified['month'].min()}~{unified['month'].max()} 共{len(unified)}月 · 主口径[{results[platform]['main_view']}]")

    # 汇总与报表
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

    consolidated = aggregate.consolidate(person_all, main_all, field_all)
    plat_annual = aggregate.platform_annual(main_all, baselines)

    OUT_DIR.mkdir(exist_ok=True)
    (OUT_DIR / "中间指标").mkdir(exist_ok=True)
    for platform, r in results.items():
        r["unified"].to_csv(OUT_DIR / "中间指标" / f"月度指标_{platform}.csv",
                            index=False, encoding="utf-8-sig")
    out_path = OUT_DIR / "目标测算报告.xlsx"
    report.write_report(out_path, results, consolidated, plat_annual, cfg, demo=demo_flag)

    # 控制台摘要
    print("\n===== 平台年度目标（主口径） =====")
    for _, r in plat_annual.iterrows():
        print(f"  [{r['platform']:<4}] {r['scenario']}: 基期 {r['基期年化GMV']:>12,.0f} → "
              f"目标 {r['目标年度GMV']:>12,.0f}（{r['增速']:+.1%}）")
    tm = next(iter(results.values()))["target_months"] if results else []
    if tm:
        print(f"测算期：{tm[0]} ~ {tm[-1]}")
    base_total = sum(b["annual_gmv"] for b in baselines.values())
    for scenario in cfg["scenarios"]:
        tot = consolidated[consolidated["scenario"] == scenario]["GMV_主口径"].sum()
        print(f"全渠道[{scenario}] 年度GMV: {tot:,.0f}（基期 {base_total:,.0f}，{tot / base_total - 1:+.1%}）")
    print(f"\n报表 → {out_path}")
    print("中间月度指标 → output/中间指标/")


def main() -> None:
    ap = argparse.ArgumentParser(description="零售目标测算（线上 · 人货场）")
    ap.add_argument("command", choices=["demo", "run", "serve", "templates"],
                    help="demo=演示数据跑通 | run=正式测算 | serve=本地工作台 | templates=生成输入模板")
    ap.add_argument("--port", type=int, default=8300, help="serve 模式端口（默认 8300）")
    args = ap.parse_args()
    cfg = load_cfg()
    if args.command == "templates":
        templates.build(ROOT)
    elif args.command == "serve":
        server.serve(ROOT, port=args.port)
    elif args.command == "demo":
        demo.generate(ROOT)
        with warnings.catch_warnings(record=True) as wlist:
            warnings.simplefilter("always")
            run_flow(cfg, demo_flag=True)
            for w in wlist:
                print(f"  ⚠ {w.message}")
    else:
        with warnings.catch_warnings(record=True) as wlist:
            warnings.simplefilter("always")
            run_flow(cfg, demo_flag=False)
            for w in wlist:
                print(f"  ⚠ {w.message}")


if __name__ == "__main__":
    main()
