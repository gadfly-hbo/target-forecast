# -*- coding: utf-8 -*-
"""投放 ROI 本地服务：标准库 http.server + JSON API + 静态页（无框架、离线）。

无持久化：/api/state 返回内置合成演示集，/api/calc 对请求体中的计划求值。

- GET  / /style.css /app.js
- GET  /api/state     引擎版本、演示计划、默认情景、合成假设标注、本机运行声明
- POST /api/calc      {plans, scenarios} → 测算结果（输入不合法 → 422 + 原因）
"""
from __future__ import annotations

import json
import mimetypes
import re
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from . import ENGINE_VERSION, PlanError, demo
from .engine import evaluate

STATIC_DIR = Path(__file__).resolve().parent / "static"


def _json_bytes(obj) -> bytes:
    return json.dumps(obj, ensure_ascii=False).encode("utf-8")


class _Responder:
    """handler 的响应帮助方法（独立 server 与 workbench 壳分发共用）。"""

    def __init__(self, h: BaseHTTPRequestHandler):
        self.h = h

    def send(self, code: int, body: bytes, ctype: str):
        self.h.send_response(code)
        self.h.send_header("Content-Type", ctype)
        self.h.send_header("Content-Length", str(len(body)))
        self.h.send_header("Cache-Control", "no-store")
        self.h.end_headers()
        self.h.wfile.write(body)

    def json(self, obj, code: int = 200):
        self.send(code, _json_bytes(obj), "application/json; charset=utf-8")

    def read_body(self) -> dict:
        length = int(self.h.headers.get("Content-Length") or 0)
        if not length:
            return {}
        return json.loads(self.h.rfile.read(length).decode("utf-8"))

    def static(self, name: str):
        path = (STATIC_DIR / name).resolve()
        if not path.is_file():
            self.json({"error": "not found"}, 404)
            return
        ctype = mimetypes.guess_type(str(path))[0] or "application/octet-stream"
        self.send(200, path.read_bytes(), ctype + "; charset=utf-8")


def state_payload() -> dict:
    return {
        "engine_version": ENGINE_VERSION,
        "plans": demo.build_demo_plans(),
        "scenarios": demo.default_scenarios(),
        # G4 契约：新增计划的参数默认值由服务端下发，前端不硬编码
        "param_defaults": {"spend_cny": 10000, "cpc_cny": 2.0, "cvr": 0.03,
                           "aov_cny": 200, "gross_margin": 0.4, "refund_rate": 0.1},
        "boundary": "本机运行：数据与测算全部在本机完成，不上传任何明细数据",
        **demo.demo_meta(),
    }


def route_get(h: BaseHTTPRequestHandler, path: str) -> bool:
    """处理 GET；返回 False 表示未命中（调用方回 404）。"""
    r = _Responder(h)
    if path in ("/", "/index.html"):
        r.static("index.html")
    elif path == "/style.css":
        r.static("style.css")
    elif path == "/app.js":
        r.static("app.js")
    elif path == "/api/state":
        r.json(state_payload())
    else:
        return False
    return True


def route_post(h: BaseHTTPRequestHandler, path: str) -> bool:
    """处理 POST；返回 False 表示未命中（调用方回 404）。"""
    r = _Responder(h)
    if path != "/api/calc":
        return False
    body = r.read_body()
    try:
        plans = body.get("plans") or []
        scenarios = body.get("scenarios") or {}
        r.json(evaluate(plans, scenarios))
    except PlanError as exc:
        r.json({"error": str(exc)}, 422)
    except (TypeError, KeyError, ValueError) as exc:
        r.json({"error": f"请求不合法：{exc}"}, 422)
    return True


def make_handler():
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, fmt, *args):  # 安静模式
            pass

        def do_GET(self):
            if not route_get(self, self.path):
                _Responder(self).json({"error": "not found"}, 404)

        def do_POST(self):
            if not route_post(self, self.path):
                _Responder(self).json({"error": "not found"}, 404)

    return Handler


def serve(port: int = 8320):
    httpd = ThreadingHTTPServer(("127.0.0.1", port), make_handler())
    print(f"投放 ROI 测算工作台：http://127.0.0.1:{port}（本机运行）")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        httpd.shutdown()
