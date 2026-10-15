"""workbench 壳服务：单端口托管所有测算工具。

只用标准库 http.server，无新增依赖；数据与测算全部在本机完成。
- GET  /            壳导航页（左侧工具导航 + iframe 内容区）
- GET  /api/state   已注册工具清单（启动脚本健康检查与导航数据源）
- GET/POST /t/{tool_id}/...   剥离前缀后分发到对应插件的路由函数
"""
from __future__ import annotations

import importlib
import os
import re
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from tools_common.httpkit import Responder, json_bytes

from .registry import Registry

SHELL_DIR = Path(__file__).resolve().parent / "static"

# 分发前缀：/t/{tool_id}/...（id 限小写字母数字下划线）
_TOOL_PREFIX = re.compile(r"^/t/([a-z0-9_]+)(/.*)?$")

_SHELL_VERSION = "1.0"


def build_default_registry(root: Path) -> Registry:
    """装配默认注册表：逐个尝试导入已插件化的工具包，未插件化的跳过。

    root 必须为仓库根绝对路径——插件上下文不允许依赖 cwd（红队 K2）。
    """
    reg = Registry()
    for modname in ("coupon_tool.plugin", "target_forecast.plugin", "roi_tool.plugin"):
        try:
            mod = importlib.import_module(modname)
        except ImportError:
            continue
        reg.register(mod.build_tool(root))
    return reg


def make_handler(registry: Registry, assistant=None):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, fmt, *args):  # 安静模式
            pass

        def _route_tool(self, method: str) -> None:
            m = _TOOL_PREFIX.match(self.path)
            tool = registry.get(m.group(1)) if m else None
            if tool is None:
                Responder(self).json({"error": "unknown tool"}, 404)
                return
            sub = m.group(2) or "/"
            fn = tool["handle_get"] if method == "GET" else tool["handle_post"]
            if not fn(self, sub):
                Responder(self).json({"error": "not found"}, 404)

        def do_GET(self) -> None:
            if _TOOL_PREFIX.match(self.path):
                self._route_tool("GET")
            elif self.path.split("?")[0] in ("/", "/index.html"):
                # 容忍 query string：旧启动脚本的 /?tool=xxx 深链自 P0 起就在这里 404（P2 e2e 暴露）
                Responder(self).send(200, (SHELL_DIR / "index.html").read_bytes(), "text/html; charset=utf-8")
            elif self.path in ("/style.css", "/app.js") or self.path.startswith("/assets/"):
                f = (SHELL_DIR / self.path.lstrip("/")).resolve()
                if not str(f).startswith(str(SHELL_DIR.resolve()) + os.sep) or not f.is_file():
                    Responder(self).json({"error": "not found"}, 404)
                    return
                ctype = {"css": "text/css", "js": "application/javascript", "png": "image/png"}.get(
                    f.suffix.lstrip("."), "application/octet-stream")
                Responder(self).send(200, f.read_bytes(), f"{ctype}; charset=utf-8" if ctype.startswith("text") else ctype)
            elif self.path == "/api/assistant/status" and assistant is not None:
                Responder(self).send(200, json_bytes({"backend": type(assistant.backend).__name__}),
                      "application/json; charset=utf-8")
            elif re.fullmatch(r"/api/state(\?.*)?", self.path):
                Responder(self).send(200, json_bytes({"version": _SHELL_VERSION, "tools": registry.manifest()}),
                      "application/json; charset=utf-8")
            else:
                Responder(self).json({"error": "not found"}, 404)

        def do_POST(self) -> None:
            if _TOOL_PREFIX.match(self.path):
                self._route_tool("POST")
            elif self.path == "/api/assistant/chat" and assistant is not None:
                from .assistant import runtime
                code, body = runtime.handle_chat(assistant, Responder(self).read_body())
                Responder(self).send(code, json_bytes(body), "application/json; charset=utf-8")
            elif self.path == "/api/assistant/exec_read" and assistant is not None:
                # Path A：sidecar 读工具代理（名门禁在 service.exec_read）
                try:
                    body = Responder(self).read_body()
                    summary = assistant.exec_read(str(body.get("name", "")), body.get("args") or {})
                    Responder(self).send(200, json_bytes({"summary": summary}),
                                         "application/json; charset=utf-8")
                except (ValueError, KeyError, TypeError) as exc:
                    Responder(self).send(422, json_bytes({"error": str(exc)}),
                                         "application/json; charset=utf-8")
            elif self.path == "/api/assistant/stage" and assistant is not None:
                # Path A：sidecar 写提案登记（名门禁在 service.stage；不执行效果）
                try:
                    body = Responder(self).read_body()
                    staged = assistant.stage(str(body.get("name", "")), body.get("args") or {})
                    Responder(self).send(200, json_bytes(staged), "application/json; charset=utf-8")
                except (ValueError, KeyError, TypeError) as exc:
                    Responder(self).send(422, json_bytes({"error": str(exc)}),
                                         "application/json; charset=utf-8")
            else:
                Responder(self).json({"error": "not found"}, 404)

    return Handler


def serve(root: Path | str, port: int = 8300, registry: Registry | None = None) -> None:
    root = Path(root).resolve()
    registry = registry or build_default_registry(root)
    if port == 0:  # 显式 port 0：先探一个空闲端口，使 sidecar 拿到确定回环地址
        import socket as _socket
        probe = _socket.socket()
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
        probe.close()
    from .assistant import runtime
    sidecar = runtime.maybe_start_sidecar(root, shell_url=f"http://127.0.0.1:{port}")
    if sidecar is not None:
        print("[助手] pi-agent sidecar 已启动 (127.0.0.1:8321)", flush=True)
        # 启动脚本用 SIGTERM 停壳：转成 KeyboardInterrupt 以走 finally 回收 sidecar（防孤儿占 8321）
        import signal
        signal.signal(signal.SIGTERM, lambda *_: (_ for _ in ()).throw(KeyboardInterrupt()))
    assistant = runtime.build_service(root, registry)
    httpd = ThreadingHTTPServer(("127.0.0.1", port), make_handler(registry, assistant=assistant))
    assistant.bind_port(httpd.server_address[1])
    print(f"测算工作台已启动: http://127.0.0.1:{port}（Ctrl+C 退出）", flush=True)
    print(f"已注册工具: {', '.join(registry.ids()) or '（无）'}", flush=True)
    print(f"助手后端: {type(assistant.backend).__name__}", flush=True)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        httpd.server_close()
        if sidecar is not None:
            sidecar.terminate()


def serve_background(root: Path | str, port: int = 0, registry: Registry | None = None) -> tuple[ThreadingHTTPServer, str]:
    """测试用：随机端口后台启动，返回 (httpd, base_url)。"""
    registry = registry or build_default_registry(Path(root).resolve())
    httpd = ThreadingHTTPServer(("127.0.0.1", port), make_handler(registry))
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    return httpd, f"http://127.0.0.1:{httpd.server_address[1]}"
