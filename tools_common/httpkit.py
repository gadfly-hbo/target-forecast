# -*- coding: utf-8 -*-
"""HTTP 管道单一事实源：标准库 http.server 的响应/分发/启动模板。

收敛自 coupon_tool/server.py、target_forecast/server.py、roi_tool/server.py、
workbench/server.py 的四份拷贝；漂移点一律取最严实现（.flow/prd.md 阶段1）：

- send 统一带 ``Cache-Control: no-store``（源自三个工具 server；壳原缺，deliberate-change #1）
- json 统一 ``ensure_ascii=False, allow_nan=False``（源自 forecast，最严）
- static 统一带路径穿越防护（源自壳）；缺失文件回 404 JSON
- serve_quiet 退出统一 ``finally: server_close()``（GRILL Q2）

依赖方向：tools_common ← 工具 ← 壳；本模块不得 import 任何业务包。
"""
from __future__ import annotations

import json
import mimetypes
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path


def json_bytes(obj) -> bytes:
    """JSON 响应体的唯一序列化入口（NaN/Inf 直接抛 ValueError，不放行非法 JSON）。"""
    return json.dumps(obj, ensure_ascii=False, allow_nan=False).encode("utf-8")


class Responder:
    """handler 的响应帮助方法（独立 server 与壳分发共用）。

    static_dir 由调用方注入（各工具绑定自己的 STATIC_DIR；壳用 raw send 不走这里）。
    """

    def __init__(self, h: BaseHTTPRequestHandler, static_dir: Path | None = None):
        self.h = h
        self.static_dir = Path(static_dir).resolve() if static_dir is not None else None

    def send(self, code: int, body: bytes, ctype: str):
        self.h.send_response(code)
        self.h.send_header("Content-Type", ctype)
        self.h.send_header("Content-Length", str(len(body)))
        self.h.send_header("Cache-Control", "no-store")
        self.h.end_headers()
        self.h.wfile.write(body)

    def json(self, obj, code: int = 200):
        self.send(code, json_bytes(obj), "application/json; charset=utf-8")

    def read_body(self) -> dict:
        length = int(self.h.headers.get("Content-Length") or 0)
        if not length:
            return {}
        return json.loads(self.h.rfile.read(length).decode("utf-8"))

    def read_raw_body(self) -> bytes:
        """读取原始字节请求体（文件上传等场景）。"""
        length = int(self.h.headers.get("Content-Length") or 0)
        return self.h.rfile.read(length) if length else b""

    def static(self, name: str):
        """服务 static_dir 下的文件；越界或不存在一律 404 JSON。"""
        path = (self.static_dir / name).resolve() if self.static_dir is not None else None
        if path is None or not str(path).startswith(str(self.static_dir) + os.sep) \
                or not path.is_file():
            self.json({"error": "not found"}, 404)
            return
        ctype = mimetypes.guess_type(str(path))[0] or "application/octet-stream"
        self.send(200, path.read_bytes(), ctype + "; charset=utf-8")


def make_dispatch_handler(handle_get, handle_post):
    """安静模式 Handler 工厂：handle_*(handler, path) -> bool，未命中回 JSON 404。"""

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, fmt, *args):  # 安静模式
            pass

        def do_GET(self):
            if not handle_get(self, self.path):
                Responder(self).json({"error": "not found"}, 404)

        def do_POST(self):
            if not handle_post(self, self.path):
                Responder(self).json({"error": "not found"}, 404)

    return Handler


def serve_quiet(handler, port: int, banner: str) -> None:
    """公共启动模板：bind 127.0.0.1 + 横幅 + Ctrl+C 安静退出（finally 回收 socket）。"""
    httpd = ThreadingHTTPServer(("127.0.0.1", port), handler)
    print(banner)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        httpd.server_close()


class AssistantParamsStore:
    """助手调参落盘（assistant_params.json）的唯一读写入口。

    只负责 load/save/merge；合法性校验（如 roi 拒绝未知计划名）留在各工具路由层。
    路径推导也留在各工具——tools_common 不学 workspace 布局。
    """

    def __init__(self, path: Path):
        self.path = Path(path)

    def load(self) -> dict:
        if self.path.is_file():
            return json.loads(self.path.read_text(encoding="utf-8"))
        return {}

    def save(self, store: dict) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(store, ensure_ascii=False, indent=2), encoding="utf-8")

    def merge(self, section: str, patches: dict) -> dict:
        """按 section（如 "scenarios"/"plans"）逐名合并参数补丁，返回合并后的 section。"""
        store = self.load()
        for name, params in patches.items():
            store.setdefault(section, {}).setdefault(name, {}).update(params or {})
        self.save(store)
        return store.get(section, {})
