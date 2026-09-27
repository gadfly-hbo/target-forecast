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
        "actions": [
            {
                "id": "get_state",
                "description": "读取优惠券工作台状态：引擎版本、已存场景清单、运行封存清单。",
                "parameters": {"type": "object", "properties": {}, "required": []},
            },
            {
                "id": "list_runs",
                "description": "列出已封存的测算运行（run_id 清单）。",
                "parameters": {"type": "object", "properties": {}, "required": []},
            },
            {
                "id": "compare",
                "description": "对已保存的某个场景执行候选券方案测算比较（含无券基准），返回各候选 ROI/增量利润与结论。",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "scenario_id": {"type": "string", "description": "场景 ID，如 coupon-demo-001"}
                    },
                    "required": ["scenario_id"],
                },
            },
        ],
        "handle_get": handle_get,
        "handle_post": handle_post,
    }
