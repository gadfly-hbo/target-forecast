"""测算工作台底座：壳服务 + 插件协议。

所有测算工具以插件形式注册（见 registry.py 的 Tool Contract），单端口单入口。
"""
from .registry import Registry
from .server import build_default_registry, make_handler, serve, serve_background

__all__ = ["Registry", "build_default_registry", "make_handler", "serve", "serve_background"]
