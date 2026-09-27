# -*- coding: utf-8 -*-
"""优惠券测算的 workbench 插件适配：manifest + 路由绑定。

壳内路径 /t/coupon/... 剥离前缀后复用 server.route_get/route_post（单一事实源）。
root 必须为仓库根绝对路径，消除 cwd 依赖。
"""
from __future__ import annotations

from pathlib import Path

from . import server


def build_tool(root: Path) -> dict:
    root = Path(root).resolve()
    app = server.Workbench(data_dir=str(root / "workspace" / "coupon"),
                           out_dir=str(root / "workspace" / "coupon" / "output"),
                           templates_dir=str(root / "templates"))

    def handle_get(h, path):
        return server.route_get(app, h, path)

    def handle_post(h, path):
        return server.route_post(app, h, path)

    return {
        "id": "coupon",
        "name": "优惠券测算",
        "icon": "🎟",
        "static_dir": server.STATIC_DIR,
        "seed_demo": None,
        "actions": [],
        "handle_get": handle_get,
        "handle_post": handle_post,
    }
