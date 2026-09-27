# -*- coding: utf-8 -*-
"""投放 ROI 的 workbench 插件适配：manifest + 路由绑定。

无持久化目录需求（每次 calc 的计划来自请求体），root 仅作契约签名保留。
壳内路径 /t/roi/... 剥离前缀后复用 server.route_get/route_post。
"""
from __future__ import annotations

from pathlib import Path

from . import server


def build_tool(root: Path) -> dict:
    app = server.App(root)

    def handle_get(h, path):
        return server.route_get(app, h, path)

    def handle_post(h, path):
        return server.route_post(app, h, path)

    return {
        "id": "roi",
        "name": "投放 ROI",
        "icon": "📈",
        "static_dir": server.STATIC_DIR,
        "seed_demo": None,
        "actions": [
            {
                "id": "get_state",
                "description": "读取投放 ROI 工作台状态：演示计划集、默认情景与参数默认值（合成假设）。",
                "parameters": {"type": "object", "properties": {}, "required": []},
            },
            {
                "id": "calc",
                "description": "对投放计划集执行 ROI 测算（plans/scenarios 省略时用演示集与默认三档情景），返回每计划 ROI/净贡献/保本转化率与排名。",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "plans": {"type": "array", "items": {"type": "object"}, "description": "投放计划列表"},
                        "scenarios": {"type": "object", "description": "情景增速定义"},
                    },
                    "required": [],
                },
            },
            {
                "id": "set_plan_params",
                "description": "调整某个投放计划的参数（写操作，需用户确认）：按名称匹配计划并打补丁，返回调整后基准情景的净贡献。",
                "write": True,
                "parameters": {
                    "type": "object",
                    "properties": {
                        "plan": {"type": "string", "description": "计划名称，如 天猫直通车-搜索"},
                        "params": {"type": "object", "description": "参数补丁，如 {\"cvr\": 0.05}"},
                    },
                    "required": ["plan", "params"],
                },
            },
        ],
        "handle_get": handle_get,
        "handle_post": handle_post,
    }
