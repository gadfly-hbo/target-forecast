"""从插件 manifest 的 actions 生成 LLM tool 定义。

内部格式在 OpenAI function 上扩展 x-tool/x-action/x-write 元信息；
to_openai() 剥离扩展字段得到可发给 LLM 的干净定义。
"""
from __future__ import annotations


def build_tools(registry) -> list[dict]:
    """遍历注册表，把每个插件的 actions 展平为命名空间 tool 定义。"""
    tools = []
    for tool_id in registry.ids():
        tool = registry.get(tool_id)
        for action in tool.get("actions") or []:
            tools.append({
                "type": "function",
                "function": {
                    "name": f"{tool_id}__{action['id']}",
                    "description": action["description"],
                    "parameters": action["parameters"],
                    "x-tool": tool_id,
                    "x-action": action["id"],
                    "x-write": bool(action.get("write")),
                },
            })
    return tools


def to_openai(tools: list[dict]) -> list[dict]:
    """剥离 x-* 扩展字段，输出标准 OpenAI tools 格式。"""
    return [{
        "type": "function",
        "function": {k: v for k, v in t["function"].items() if not k.startswith("x-")},
    } for t in tools]
