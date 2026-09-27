"""插件协议与注册表。

插件协议（Tool Contract，见 .flow/prd.md D2）——每个测算工具一个包，入口暴露 manifest：
    {
        "id": "coupon",                 # URL 前缀 /t/{id}/，全局唯一
        "name": "优惠券测算",            # 壳导航显示名
        "icon": "🎟",
        "static_dir": Path | None,      # 工具静态资源目录
        "seed_demo": callable(root) | None,   # 数据为空时播种（可选）
        "actions": [],                  # 机器可读 action 清单（JSON Schema，P3 LLM 预留）
        "handle_get":  callable(handler, path) -> bool,   # path 已剥离 /t/{id} 前缀
        "handle_post": callable(handler, path) -> bool,   # 返回 False 表示未命中（壳回 404）
    }

路由函数收到的 path 保留 query string（如 "/api/state?reload=1"）。
"""
from __future__ import annotations

MANIFEST_KEYS = ("id", "name", "icon")


class Registry:
    """显式工具注册表（G4：本地静态工具集，不用动态扫描）。"""

    def __init__(self) -> None:
        self._tools: dict[str, dict] = {}

    def register(self, tool: dict) -> None:
        tid = tool.get("id")
        if not tid or not isinstance(tid, str):
            raise ValueError("插件缺少合法 id")
        if tid in self._tools:
            raise ValueError(f"工具 id 重复: {tid}")
        for key in ("name", "handle_get", "handle_post"):
            if key not in tool:
                raise ValueError(f"插件 {tid} 缺少字段: {key}")
        self._tools[tid] = tool

    def get(self, tool_id: str) -> dict | None:
        return self._tools.get(tool_id)

    def ids(self) -> list[str]:
        return list(self._tools)

    def manifest(self) -> list[dict]:
        """壳 /api/state 暴露的工具清单（仅 manifest 键）。"""
        return [{k: t[k] for k in MANIFEST_KEYS} for t in self._tools.values()]
