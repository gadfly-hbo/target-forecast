# -*- coding: utf-8 -*-
"""CLI：python -m coupon_tool demo|console|templates|serve（提案 §8.4、门禁 B 最短路径）。"""
from __future__ import annotations

import argparse
import sys

from . import ENGINE_VERSION
from .compare import compare
from .exports import export_all
from .ingest import generate_templates
from .spec import SpecError
from .storage import Store
from .stress import stress_test
from .synthetic import build_synthetic_spec

DEMO_STRESS_VARIANTS = {
    "低响应": {"behavior.conversion.k": 0.45},
    "高响应": {"behavior.conversion.k": 1.35},
    "低凑单高流失": {"behavior.q_curve.q_cap": 0.4, "behavior.churn": 0.05},
}


def _pipeline(spec, store: Store, out_dir: str, with_stress: bool) -> dict:
    cmp_res = compare(spec)
    stress = stress_test(spec, DEMO_STRESS_VARIANTS) if with_stress else None
    run = store.record_run(spec, cmp_res, stress=stress)
    paths = export_all(run, out_dir=out_dir)
    return {"run": run, "cmp": cmp_res, "paths": paths}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="coupon_tool",
                                     description="优惠券情景测算与比较工具（本地、确定性）")
    parser.add_argument("--version", action="version", version=ENGINE_VERSION)
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_demo = sub.add_parser("demo", help="内置合成演示场景端到端（非真实经营数据）")
    p_demo.add_argument("--data-dir", default="coupon_data")
    p_demo.add_argument("--out", default="output/coupon")

    p_console = sub.add_parser("console", help="从数据目录加载已保存场景测算")
    p_console.add_argument("--scenario", required=True)
    p_console.add_argument("--data-dir", default="coupon_data")
    p_console.add_argument("--out", default="output/coupon")
    p_console.add_argument("--no-stress", action="store_true")

    p_tpl = sub.add_parser("templates", help="生成导入模板（分桶/订单明细 XLSX）")
    p_tpl.add_argument("--out", default="templates")

    p_serve = sub.add_parser("serve", help="启动本地工作台（默认 8310 端口）")
    p_serve.add_argument("--port", type=int, default=8310)
    p_serve.add_argument("--data-dir", default="coupon_data")

    args = parser.parse_args(argv)
    try:
        if args.cmd == "demo":
            spec = build_synthetic_spec()
            store = Store(args.data_dir)
            store.save_spec(spec)
            result = _pipeline(spec, store, args.out, with_stress=True)
            _print_summary(result, args)
        elif args.cmd == "console":
            store = Store(args.data_dir)
            spec = store.load_spec(args.scenario)
            result = _pipeline(spec, store, args.out, with_stress=not args.no_stress)
            _print_summary(result, args)
        elif args.cmd == "templates":
            written = generate_templates(args.out)
            print(f"模板已生成：{', '.join(written)}（目录 {args.out}）")
        elif args.cmd == "serve":
            from .server import serve
            serve(port=args.port, data_dir=args.data_dir)
            return 0
    except SpecError as exc:
        print(f"场景不合法：{exc}", file=sys.stderr)
        return 2
    return 0


def _print_summary(result: dict, args) -> None:
    run, cmp_res, paths = result["run"], result["cmp"], result["paths"]
    print(f"运行 {run['run_id']}（引擎 {run['engine_version']}）")
    print(f"结论：{cmp_res.conclusion['type']}——{cmp_res.conclusion['message']}")
    if cmp_res.ranking:
        top = cmp_res.ranking[0]
        m = top["metrics"]
        print(f"排序首选：{top['label']}　ΔΠ={m['incremental_contribution_cents'] / 100:.2f} 元　"
              f"商家券补={m['merchant_subsidy_cents'] / 100:.2f} 元　"
              f"转化率={m['conversion_rate']:.4%}")
    for kind, path in paths.items():
        print(f"导出[{kind}]：{path}")
    print(f"演示参数为合成假设（synthetic_assumptions），非真实经营证据。")


if __name__ == "__main__":
    raise SystemExit(main())
