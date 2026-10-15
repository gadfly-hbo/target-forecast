# -*- coding: utf-8 -*-
"""投放 ROI 本地服务：标准库 http.server + JSON API + 静态页（无框架、离线）。

无持久化：/api/state 返回内置合成演示集，/api/calc 对请求体中的计划求值。

- GET  / /style.css /app.js
- GET  /api/state     引擎版本、演示计划、默认情景、合成假设标注、本机运行声明
- POST /api/calc      {plans, scenarios} → 测算结果（输入不合法 → 422 + 原因）
"""
from __future__ import annotations

from pathlib import Path

from tools_common.httpkit import (AssistantParamsStore, Responder,
                                  make_dispatch_handler, serve_quiet)

from . import ENGINE_VERSION, PlanError, demo
from .engine import evaluate

STATIC_DIR = Path(__file__).resolve().parent / "static"


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
        self.params = AssistantParamsStore(self.root / "workspace" / "roi" / "assistant_params.json")


def route_get(app: App, h, path: str) -> bool:
    """处理 GET；返回 False 表示未命中（调用方回 404）。"""
    r = Responder(h, STATIC_DIR)
    if path in ("/", "/index.html"):
        r.static("index.html")
    elif path == "/style.css":
        r.static("style.css")
    elif path == "/app.js":
        r.static("app.js")
    elif path == "/api/state":
        r.json(state_payload())
    elif path == "/api/assistant_params":
        r.json(app.params.load())
    else:
        return False
    return True


def route_post(app: App, h, path: str) -> bool:
    """处理 POST；返回 False 表示未命中（调用方回 404）。"""
    r = Responder(h, STATIC_DIR)
    if path == "/api/assistant_params":
        # 写操作：助手调参（经确认门后由壳执行到此），按计划名合并补丁；
        # 未知计划名拒绝（防 LLM 幻觉名落盘）
        body = r.read_body()
        known = {p["name"] for p in demo.build_demo_plans()}
        unknown = [n for n in (body.get("plans") or {}) if n not in known]
        if unknown:
            r.json({"error": f"未知计划名：{'、'.join(unknown)}（现有：{'、'.join(sorted(known))}）"}, 422)
            return True
        plans = app.params.merge("plans", body.get("plans") or {})
        r.json({"saved": True, "plans": plans})
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

    def handle_get(h, path):
        return route_get(app, h, path)

    def handle_post(h, path):
        return route_post(app, h, path)

    return make_dispatch_handler(handle_get, handle_post)


def serve(port: int = 8320):
    """独立入口（当前无 CLI 调用方，半保留）；壳内路径走 plugin.py。"""
    serve_quiet(make_handler(App(Path.cwd())), port,
                f"投放 ROI 测算工作台：http://127.0.0.1:{port}（本机运行）")
