# -*- coding: utf-8 -*-
"""forecast 工具插件化适配：向壳暴露 manifest 与路由。

壳内路径 /t/forecast/... 剥离前缀后与 standalone（main.py serve）共用
server.make_routes 的同一组路由（单一事实源）。
standalone=True：壳导航整页跳转（v2 方案工作区自带完整 chrome，不进 iframe）。
AI 动作（G2 双轨）：读与提案 dry-run 不落草稿；唯一写动作 apply_proposal 走确认门，
采纳仍是用户显式决定；工作区页面的采纳按钮与之共用同一业务入口（plans.service）。
"""
from pathlib import Path

from . import server


def build_tool(root: Path) -> dict:
    root = Path(root).resolve()
    handle_get, handle_post = server.make_routes(root)

    return {
        "id": "forecast",
        "name": "目标测算",
        "icon": "🎯",
        "standalone": True,
        "handle_get": handle_get,
        "handle_post": handle_post,
        "static_dir": server.V2_STATIC,
        "seed_demo": None,
        "actions": [
            {
                "id": "get_plan_state",
                "description": "读取目标测算某方案状态：修订号、目标、数据与质量、三域确认、最近运行摘要（不含原始订单）。",
                "parameters": {
                    "type": "object",
                    "properties": {"plan_id": {"type": "string"}},
                    "required": ["plan_id"],
                },
            },
            {
                "id": "compare_runs",
                "description": "比较某方案下若干已保存运行：各运行的采用档、合计 GMV、引擎与保存时间。",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "plan_id": {"type": "string"},
                        "run_ids": {"type": "array", "items": {"type": "string"}},
                    },
                    "required": ["plan_id", "run_ids"],
                },
            },
            {
                "id": "propose_plan_changes",
                "description": "对指定方案的某档情景提出参数调整建议（dry-run，不落工作稿）：返回调整前后差异与影响说明，用户采纳后才生效。",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "plan_id": {"type": "string"},
                        "scenario": {"type": "string", "enum": ["保守", "基准", "挑战"]},
                        "patches": {"type": "object", "description": "增长参数补丁，如 {\"new_customers_growth\": 0.2}"},
                        "rationale": {"type": "string"},
                    },
                    "required": ["plan_id", "scenario", "patches"],
                },
            },
            {
                "id": "apply_proposal",
                "description": "采纳一条提案并写入方案工作稿（写操作，需用户确认）：假设确认随之失效，需要重新确认后计算；已有运行不变。",
                "write": True,
                "parameters": {
                    "type": "object",
                    "properties": {
                        "plan_id": {"type": "string"},
                        "proposal_id": {"type": "string"},
                    },
                    "required": ["plan_id", "proposal_id"],
                },
            },
        ],
    }
