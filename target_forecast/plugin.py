"""目标测算的 workbench 插件适配：manifest + 路由绑定。

壳内路径 /t/forecast/... 剥离前缀后复用 server.route_get/route_post（单一事实源）。
root 必须为仓库根绝对路径（含 config.yaml 与 data/）。
"""
from __future__ import annotations

from pathlib import Path

from . import server


def build_tool(root: Path) -> dict:
    root = Path(root).resolve()
    cfg = server.load_cfg(root)
    state = server.WorkbenchState(root, cfg["caliber"])

    def handle_get(h, path):
        return server.route_get(state, cfg, h, path)

    def handle_post(h, path):
        return server.route_post(state, cfg, h, path)

    return {
        "id": "forecast",
        "name": "目标测算",
        "icon": "🎯",
        "static_dir": server.STATIC_DIR,
        "seed_demo": None,
        "actions": [
            {
                "id": "get_state",
                "description": "读取目标测算工作台状态：平台清单、模式A/B、演示/正式标记、默认情景参数。",
                "parameters": {"type": "object", "properties": {}, "required": []},
            },
            {
                "id": "calc",
                "description": "按指定三档情景参数重算人/场/货三视角与全渠道汇总，返回各平台结果。scenarios 省略时用默认参数。",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "scenarios": {"type": "object", "description": "三档情景参数（与 /api/calc 同结构）"}
                    },
                    "required": [],
                },
            },
            {
                "id": "set_scenario_params",
                "description": "调整某档情景的增长参数（写操作，需用户确认）：给出 scenario 与参数补丁，返回调整后该档的全渠道年化GMV。",
                "write": True,
                "parameters": {
                    "type": "object",
                    "properties": {
                        "scenario": {"type": "string", "enum": ["保守", "基准", "挑战"]},
                        "params": {"type": "object", "description": "增长参数补丁，如 {\"new_customers_growth\": 0.2}"},
                    },
                    "required": ["scenario", "params"],
                },
            },
        ],
        "handle_get": handle_get,
        "handle_post": handle_post,
    }
