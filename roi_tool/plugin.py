# -*- coding: utf-8 -*-
"""投放 ROI 的 workbench 插件适配：manifest + 路由绑定。

无持久化目录需求（每次 calc 的计划来自请求体），root 仅作契约签名保留。
壳内路径 /t/roi/... 剥离前缀后复用 server.route_get/route_post。
"""
from __future__ import annotations

from pathlib import Path

from . import server


def build_tool(root: Path) -> dict:
    def handle_get(h, path):
        return server.route_get(h, path)

    def handle_post(h, path):
        return server.route_post(h, path)

    return {
        "id": "roi",
        "name": "投放 ROI",
        "icon": "📈",
        "static_dir": server.STATIC_DIR,
        "seed_demo": None,
        "actions": [],
        "handle_get": handle_get,
        "handle_post": handle_post,
    }
