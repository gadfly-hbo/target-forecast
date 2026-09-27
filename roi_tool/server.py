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


class App:
    """roi 工作台上下文（P3）：注入仓库根，assistant_params 落盘到 workspace/roi/。

    引擎仍无业务持久化；root 仅为助手调参通道服务（测试可隔离）。
    """

    def __init__(self, root: Path):
        self.root = Path(root).resolve()

    def params_path(self) -> Path:
        return self.root / "workspace" / "roi" / "assistant_params.json"

    def load_assistant_params(self) -> dict:
        f = self.params_path()
        if f.is_file():
            return json.loads(f.read_text(encoding="utf-8"))
        return {}

    def save_assistant_params(self, store: dict) -> None:
        f = self.params_path()
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(json.dumps(store, ensure_ascii=False, indent=2), encoding="utf-8")


def route_get(app: App, h: BaseHTTPRequestHandler, path: str) -> bool:
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
    elif path == "/api/assistant_params":
        r.json(app.load_assistant_params())
    else:
        return False
    return True


def route_post(app: App, h: BaseHTTPRequestHandler, path: str) -> bool:
    """处理 POST；返回 False 表示未命中（调用方回 404）。"""
    r = _Responder(h)
    if path == "/api/assistant_params":
        # 写操作：助手调参（经确认门后由壳执行到此），按计划名合并补丁；
        # 未知计划名拒绝（防 LLM 幻觉名落盘）
        body = r.read_body()
        known = {p["name"] for p in demo.build_demo_plans()}
        unknown = [n for n in (body.get("plans") or {}) if n not in known]
        if unknown:
            r.json({"error": f"未知计划名：{'、'.join(unknown)}（现有：{'、'.join(sorted(known))}）"}, 422)
            return True
        store = app.load_assistant_params()
        for name, params in (body.get("plans") or {}).items():
            store.setdefault("plans", {}).setdefault(name, {}).update(params or {})
        app.save_assistant_params(store)
        r.json({"saved": True, "plans": store.get("plans", {})})
        return True
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


def make_handler(app: App | None = None):
    app = app or App(Path.cwd())

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, fmt, *args):  # 安静模式
            pass

        def do_GET(self):
            if not route_get(app, self, self.path):
                _Responder(self).json({"error": "not found"}, 404)

        def do_POST(self):
            if not route_post(app, self, self.path):
                _Responder(self).json({"error": "not found"}, 404)

    return Handler


def serve(port: int = 8320):
    httpd = ThreadingHTTPServer(("127.0.0.1", port), make_handler(App(Path.cwd())))
    print(f"投放 ROI 测算工作台：http://127.0.0.1:{port}（本机运行）")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        httpd.shutdown()
