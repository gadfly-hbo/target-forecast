#!/usr/bin/env python3
"""零售目标测算 · 命令行入口。

用法：
    .venv/bin/python main.py demo       # 生成演示数据并跑通全流程（首次体验用）
    .venv/bin/python main.py run        # 用 workspace/forecast/ 下的正式数据测算
    .venv/bin/python main.py serve      # 启动本地 HTML 工作台（--port 指定端口）
    .venv/bin/python main.py templates  # 重新生成输入模板
"""

from __future__ import annotations

import argparse
import sys
import warnings
from pathlib import Path

from target_forecast import demo, pipeline, report, server, templates

ROOT = Path(__file__).resolve().parent
OUT_DIR = ROOT / "workspace" / "forecast" / "output"


def run_flow(cfg: dict, demo_flag: bool) -> None:
    detail_files, agg_files = pipeline.scan_inputs(ROOT)
    if not detail_files and not agg_files:
        sys.exit("workspace/forecast/orders 与 workspace/forecast/metrics 下没有任何 xlsx 输入文件。先运行 `main.py demo` 或按 templates/ 模板填数。")

    # 原地变异刻意保留：write_report 的 07_参数 sheet 遍历 cfg["caliber"] 取此行
    cfg["caliber"]["target_months"] = cfg["target"]["months"]
    platforms = pipeline.ingest_platforms(detail_files, agg_files, cfg["caliber"])
    results = pipeline.run_engine(platforms, cfg["scenarios"], cfg["caliber"])
    for platform, r in results.items():
        u = r["unified"]
        kind = "明细" if r["mode"] == "A" else "聚合"
        print(f"[{platform}] 模式{r['mode']} {kind}测算 … 历史 {u['month'].min()}~{u['month'].max()} "
              f"共{len(u)}月 · 主口径[{r['main_view']}]")

    # 汇总与报表
    views = pipeline.build_views(results)
    consolidated, plat_annual = views["consolidated"], views["platform_annual"]
    baselines = views["baselines"]

    OUT_DIR.mkdir(parents=True, exist_ok=True)
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
    print("中间月度指标 → workspace/forecast/output/中间指标/")


def main() -> None:
    ap = argparse.ArgumentParser(description="零售目标测算（线上 · 人货场）")
    ap.add_argument("command", choices=["demo", "run", "serve", "templates"],
                    help="demo=演示数据跑通 | run=正式测算 | serve=本地工作台 | templates=生成输入模板")
    ap.add_argument("--port", type=int, default=8300, help="serve 模式端口（默认 8300）")
    args = ap.parse_args()
    cfg = server.load_cfg(ROOT)
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
