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


def run_flow(cfg: dict, demo_flag: bool, root: Path = None) -> None:
    root = root or ROOT
    out_dir = root / "workspace" / "forecast" / "output"
    detail_files, agg_files = pipeline.scan_inputs(root)
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

    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "中间指标").mkdir(exist_ok=True)
    for platform, r in results.items():
        r["unified"].to_csv(out_dir / "中间指标" / f"月度指标_{platform}.csv",
                            index=False, encoding="utf-8-sig")
    out_path = out_dir / "目标测算报告.xlsx"
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
    print(f"中间月度指标 → {out_dir / '中间指标'}/")


def _v2(args, root: Path) -> None:
    """v2 方案/运行薄壳：全部只调 plans.service（与手动、AI 同一业务更新入口）。"""
    from target_forecast.plans import service
    from target_forecast.plans.service import StaleError, ValidationError
    from target_forecast.plans.store import ConflictError, NotFoundError

    try:
        if args.command == "plans":
            plans = service.list_plans(root)
            if not plans:
                print("还没有测算方案。用 plan-create 创建。")
            for p in plans:
                print(f"  {p['plan_id']}  {p['title']}  r{p['revision']}  "
                      f"{'有数据' if p['has_data'] else '无数据'}  运行 {p['runs']} 个  更新 {p['updated']}")
        elif args.command == "plan":
            d = service.load_draft(root, args.extra[0])
            print(f"{d['plan_id']}  {d['title']}  r{d['revision']}")
            print(f"  目标: {d['goal'].get('value') or '未定'}{d['goal'].get('unit', '元')}  "
                  f"期间: {d['period']['target_months']} 个月  采用档: {d['selected']}")
            print(f"  数据快照: {d['data'].get('snapshot_id') or '未导入'}")
            st = service.confirmation_status(d)
            for kind, s in st.items():
                print(f"  确认[{kind}]: {'有效' if s['confirmed'] else ('已失效' if s['stale'] else '未确认')}")
            issues = service.readiness(d)
            print("  就绪: " + ("可以计算" if not issues else "；".join(issues)))
            for r in service.list_runs(root, d["plan_id"]):
                print(f"  运行 {r['run_id']}  版本 {r['version']}  保存 {r['saved']}")
        elif args.command == "plan-create":
            if not args.need:
                sys.exit("plan-create 需要 --need \"业务描述\"")
            d = service.create_plan(root, args.need, title=args.title,
                                    source="import" if args.from_config else "cli")
            print(f"已创建 {d['plan_id']}（r{d['revision']}）"
                  + (f"，参数来源 config.yaml@{d['provenance']['hash']}" if d.get("provenance") else ""))
        elif args.command == "plan-calc":
            d = service.load_draft(root, args.extra[0])
            job = service.start_run(root, d["plan_id"], base_revision=d["revision"], sync=True)
            print(f"计算 {job['job_id']}: {job['status']}"
                  + (f"（{job['error']['message']}）" if job.get("error") else ""))
        elif args.command == "plan-save":
            job_id = args.extra[1] if len(args.extra) > 1 else None
            if not job_id:
                jobs = service.list_jobs(root, args.extra[0])
                done = [j for j in jobs if j["status"] == "done"]
                if not done:
                    sys.exit("没有已完成的计算；先 plan-calc")
                job_id = done[0]["job_id"]
            out = service.save_run(root, args.extra[0], job_id)
            tag = "已存在，去重返回" if out["duplicate"] else "已保存"
            print(f"{tag}: {out['run']['run_id']}（版本 {out['run']['version']}）")
        elif args.command == "plan-export":
            plan_id, run_id = args.extra[0], args.extra[1]
            out = service.export_run(root, plan_id, run_id, args.format)
            print(f"{'复用已有导出' if out['reused'] else '已导出'}: {out['file']}")
    except (ValidationError, StaleError, ConflictError, NotFoundError) as e:
        sys.exit(f"错误：{e}")
    except IndexError:
        sys.exit(f"{args.command} 参数不足，见 --help")


def main() -> None:
    ap = argparse.ArgumentParser(description="零售目标测算（线上 · 人货场）")
    ap.add_argument("command", choices=["demo", "run", "serve", "templates",
                                        "plans", "plan", "plan-create", "plan-calc",
                                        "plan-save", "plan-export"],
                    help="demo=演示数据跑通 | run=正式测算(旧版) | serve=本地工作台 | templates=生成输入模板\n"
                         "v2: plans=方案列表 | plan <id>=详情 | plan-create=创建 | plan-calc <id>=计算\n"
                         "    plan-save <id> [job]=保存运行 | plan-export <id> <run>=导出")
    ap.add_argument("extra", nargs="*", help="v2 子命令的位置参数（plan_id / job_id / run_id）")
    ap.add_argument("--port", type=int, default=8300, help="serve 模式端口（默认 8300）")
    ap.add_argument("--root", default=None, help="仓库根目录（默认 main.py 所在目录）")
    ap.add_argument("--format", default="xlsx", choices=["xlsx", "csv", "json"], help="plan-export 格式")
    ap.add_argument("--title", default=None, help="plan-create 标题")
    ap.add_argument("--need", default=None, help="plan-create 业务描述")
    ap.add_argument("--from-config", action="store_true", help="plan-create 从 config.yaml 导入参数")
    args = ap.parse_args()
    root = Path(args.root).resolve() if args.root else ROOT
    if args.command in ("plans", "plan", "plan-create", "plan-calc", "plan-save", "plan-export"):
        _v2(args, root)
        return
    cfg = server.load_cfg(root)
    if args.command == "templates":
        templates.build(root)
    elif args.command == "serve":
        server.serve(root, port=args.port)
    elif args.command == "demo":
        demo.generate(root)
        with warnings.catch_warnings(record=True) as wlist:
            warnings.simplefilter("always")
            run_flow(cfg, demo_flag=True, root=root)
            for w in wlist:
                print(f"  ⚠ {w.message}")
    else:
        with warnings.catch_warnings(record=True) as wlist:
            warnings.simplefilter("always")
            run_flow(cfg, demo_flag=False, root=root)
            for w in wlist:
                print(f"  ⚠ {w.message}")


if __name__ == "__main__":
    main()
