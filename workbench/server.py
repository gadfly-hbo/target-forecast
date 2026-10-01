"""workbench 壳服务：单端口托管所有测算工具。

只用标准库 http.server，无新增依赖；数据与测算全部在本机完成。
- GET  /            壳导航页（左侧工具导航 + iframe 内容区）
- GET  /api/state   已注册工具清单（启动脚本健康检查与导航数据源）
- GET/POST /t/{tool_id}/...   剥离前缀后分发到对应插件的路由函数
"""
from __future__ import annotations

import importlib
import json
import os
import re
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

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


def _json_bytes(obj) -> bytes:
    return json.dumps(obj, ensure_ascii=False).encode("utf-8")


def _send(handler, code: int, body: bytes, ctype: str) -> None:
    handler.send_response(code)
    handler.send_header("Content-Type", ctype)
    handler.send_header("Content-Length", str(len(body)))
    handler.end_headers()
    handler.wfile.write(body)


def make_handler(registry: Registry, assistant=None):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, fmt, *args):  # 安静模式
            pass

        def _route_tool(self, method: str) -> None:
            m = _TOOL_PREFIX.match(self.path)
            tool = registry.get(m.group(1)) if m else None
            if tool is None:
                _send(self, 404, b'{"error": "unknown tool"}', "application/json; charset=utf-8")
                return
            sub = m.group(2) or "/"
            fn = tool["handle_get"] if method == "GET" else tool["handle_post"]
            if not fn(self, sub):
                _send(self, 404, b'{"error": "not found"}', "application/json; charset=utf-8")

        def _read_json_body(self) -> dict:
            n = int(self.headers.get("Content-Length") or 0)
            return json.loads(self.rfile.read(n) or b"{}")

        def do_GET(self) -> None:
            if _TOOL_PREFIX.match(self.path):
                self._route_tool("GET")
            elif self.path.split("?")[0] in ("/", "/index.html"):
                # 容忍 query string：旧启动脚本的 /?tool=xxx 深链自 P0 起就在这里 404（P2 e2e 暴露）
                _send(self, 200, (SHELL_DIR / "index.html").read_bytes(), "text/html; charset=utf-8")
            elif self.path in ("/style.css", "/app.js") or self.path.startswith("/assets/"):
                f = (SHELL_DIR / self.path.lstrip("/")).resolve()
                if not str(f).startswith(str(SHELL_DIR.resolve()) + os.sep) or not f.is_file():
                    _send(self, 404, b'{"error": "not found"}', "application/json; charset=utf-8")
                    return
                ctype = {"css": "text/css", "js": "application/javascript", "png": "image/png"}.get(
                    f.suffix.lstrip("."), "application/octet-stream")
                _send(self, 200, f.read_bytes(), f"{ctype}; charset=utf-8" if ctype.startswith("text") else ctype)
            elif self.path == "/api/assistant/status" and assistant is not None:
                _send(self, 200, _json_bytes({"backend": type(assistant.backend).__name__}),
                      "application/json; charset=utf-8")
            elif re.fullmatch(r"/api/state(\?.*)?", self.path):
                _send(self, 200, _json_bytes({"version": _SHELL_VERSION, "tools": registry.manifest()}),
                      "application/json; charset=utf-8")
            else:
                _send(self, 404, b'{"error": "not found"}', "application/json; charset=utf-8")

        def do_POST(self) -> None:
            if _TOOL_PREFIX.match(self.path):
                self._route_tool("POST")
            elif self.path == "/api/assistant/chat" and assistant is not None:
                from .assistant import runtime
                code, body = runtime.handle_chat(assistant, self._read_json_body())
                _send(self, code, _json_bytes(body), "application/json; charset=utf-8")
            else:
                _send(self, 404, b'{"error": "not found"}', "application/json; charset=utf-8")

    return Handler


def serve(root: Path | str, port: int = 8300, registry: Registry | None = None) -> None:
    root = Path(root).resolve()
    registry = registry or build_default_registry(root)
    from .assistant import runtime
    sidecar = runtime.maybe_start_sidecar(root)
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
