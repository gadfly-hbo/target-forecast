"""CLI：python -m workbench serve（测算工作台统一入口）。"""
from __future__ import annotations

import argparse
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def main() -> None:
    p = argparse.ArgumentParser(prog="python -m workbench", description="测算工作台底座")
    sub = p.add_subparsers(dest="cmd", required=True)
    sp = sub.add_parser("serve", help="启动壳服务（默认 8300）")
    sp.add_argument("--port", type=int, default=8300)
    mp = sub.add_parser("migrate", help="把 data/、coupon_data/、output/ 无损收编到 workspace/")
    args = p.parse_args()

    if args.cmd == "serve":
        from .server import serve

        serve(ROOT, port=args.port)
    elif args.cmd == "migrate":
        from .migrate import apply

        rep = apply(ROOT)
        print(f"[迁移] 移动 {rep.moved} 个文件，同内容去重 {rep.dedup} 个，清理空目录 {len(rep.removed_dirs)} 个")
        for src, dst in rep.conflicts:
            print(f"[冲突] 目标已存在，已跳过（源保留）：{src.relative_to(ROOT)} -> {dst.relative_to(ROOT)}")
        if rep.conflicts:
            print("请人工核对以上冲突文件后，删除旧位置或合并内容。")


if __name__ == "__main__":
    main()
