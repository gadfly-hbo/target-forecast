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
    args = p.parse_args()

    if args.cmd == "serve":
        from .server import serve

        serve(ROOT, port=args.port)


if __name__ == "__main__":
    main()
