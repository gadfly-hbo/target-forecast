"""本地 HTML 工作台：静态页 + JSON API。

只用标准库 http.server，无新增依赖；数据与测算全部在本机完成。
- GET  /            工作台页面
- GET  /style.css /app.js
- GET  /api/state   平台清单、历史月度指标、基线、默认情景（?reload=1 强制重读 data/）
- POST /api/calc    提交三档情景参数 → 重算人/场/货三视角 + 全渠道汇总
"""

from __future__ import annotations

import re
import urllib.parse
import threading
from pathlib import Path

import pandas as pd
import yaml

from tools_common.httpkit import (AssistantParamsStore, Responder,
                                  make_dispatch_handler, serve_quiet)

from . import demo, pipeline

STATIC_DIR = Path(__file__).resolve().parent / "static"

# 参数合法范围：增速 [-50%, +200%]
_GROWTH_RANGE = (-0.5, 2.0)


def load_cfg(root: Path) -> dict:
    with open(root / "config.yaml", encoding="utf-8") as f:
        return yaml.safe_load(f)


class WorkbenchState:
    """workspace/forecast 输入的惰性加载与缓存（线程锁保护）。"""

    def __init__(self, root: Path, caliber: dict):
        self.root = root
        self.caliber = caliber
        self.lock = threading.Lock()
        self.platforms: dict[str, dict] = {}
        self.demo_used = False
        self.params = AssistantParamsStore(
            root / "workspace" / "forecast" / "assistant_params.json")

    def load(self, force: bool = False) -> None:
        with self.lock:
            if self.platforms and not force:
                return
            detail, agg = pipeline.scan_inputs(self.root)
            if not detail and not agg:
                print("workspace/forecast 为空，自动生成演示数据 …")
                demo.generate(self.root)
                detail, agg = pipeline.scan_inputs(self.root)
                self.demo_used = True
            else:
                self.demo_used = False
            self.platforms = pipeline.ingest_platforms(detail, agg, self.caliber)

    def state_payload(self, cfg: dict, force: bool = False) -> dict:
        self.load(force)
        return {
            "demo_used": self.demo_used,
            "caliber": cfg["caliber"],
            "target_months": cfg["target"]["months"],
            "scenarios": cfg["scenarios"],
            "platforms": {
                p: {
                    "mode": v["mode"],
                    "months": len(v["unified"]),
                    "history": _sanitize(v["unified"]),
                }
                for p, v in self.platforms.items()
            },
        }


def _sanitize(df: pd.DataFrame) -> list[dict]:
    return df.astype(object).where(df.notna(), None).to_dict(orient="records")


def _validate_scenarios(payload: dict, defaults: dict) -> dict:
    """前端提交的三档情景参数：结构对齐默认值，数值夹到合法范围。"""
    out = {}
    for name, default_params in defaults.items():
        src = (payload or {}).get(name, {})
        params = {}
        for k, v in default_params.items():
            if k == "tier_growth":
                tg = src.get("tier_growth", {})
                params[k] = {t: _clip(tg.get(t, tv)) for t, tv in v.items()}
            else:
                params[k] = _clip(src.get(k, v))
        out[name] = params
    return out


def _clip(x) -> float:
    try:
        x = float(x)
    except (TypeError, ValueError):
        return 0.0
    return max(_GROWTH_RANGE[0], min(_GROWTH_RANGE[1], x))


def calc(state: WorkbenchState, cfg: dict, scenarios: dict) -> dict:
    state.load()
    caliber = {**cfg["caliber"], "target_months": cfg["target"]["months"]}
    results = pipeline.run_engine(state.platforms, scenarios, caliber)
    views = pipeline.build_views(results)

    return {
        "platforms": {
            p: {
                "mode": r["mode"],
                "main_view": r["main_view"],
                "baseline": {k: (None if v is None else round(float(v), 4)) for k, v in r["baseline"].items()},
                "person": _sanitize(r["person"]),
                "field": _sanitize(r["field"]) if r["field"] is not None else None,
            }
            for p, r in results.items()
        },
        "consolidated": _sanitize(views["consolidated"]),
        "platform_annual": _sanitize(views["platform_annual"]),
        "check": _sanitize(views["check"]),
        "goods": _sanitize(views["goods"]),
        "target_range": results[next(iter(results))]["target_months"] if results else [],
    }


def route_get(state: WorkbenchState, cfg: dict, h, path: str) -> bool:
    """处理 GET；返回 False 表示未命中（调用方回 404）。path 保留 query string。"""
    r = Responder(h, STATIC_DIR)
    try:
        if path in ("/", "/index.html"):
            r.static("index.html")
        elif path == "/style.css":
            r.static("style.css")
        elif path == "/app.js":
            r.static("app.js")
        elif path == "/api/assistant_params":
            # 助手调参持久化（P3）：前端启动时读取并应用，刷新后生效
            r.json(state.params.load())
        elif re.match(r"^/api/state(\?|$)", path):
            force = "reload=1" in path
            r.json(state.state_payload(cfg, force=force))
        elif path == "/api/export/report":
            f = state.root / "workspace" / "forecast" / "output" / "目标测算报告.xlsx"
            if not f.is_file():
                r.json({"error": "报表不存在：先运行 main.py run 生成"}, 404)
            else:
                r.send(200, f.read_bytes(),
                       "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
        elif m := re.fullmatch(r"/api/export/metrics/([^/?]+)(\?.*)?", path):
            platform = urllib.parse.unquote(m.group(1))
            if "/" in platform or "\\" in platform or ".." in platform:
                r.json({"error": "非法平台名"}, 404)
                return True
            f = state.root / "workspace" / "forecast" / "output" / "中间指标" / f"月度指标_{platform}.csv"
            if not f.is_file():
                r.json({"error": f"中间指标不存在：{platform}（先运行 main.py run 生成）"}, 404)
            else:
                r.send(200, f.read_bytes(), "text/csv; charset=utf-8")
        else:
            return False
    except Exception as e:  # noqa: BLE001 —— 本地工作台把错误如实回给页面
        r.json({"error": f"{type(e).__name__}: {e}"}, 500)
    return True


def route_post(state: WorkbenchState, cfg: dict, h, path: str) -> bool:
    """处理 POST；返回 False 表示未命中（调用方回 404）。"""
    r = Responder(h, STATIC_DIR)
    try:
        if path == "/api/assistant_params":
            # 写操作：助手调参（经确认门后由壳执行到此），按情景合并补丁
            body = r.read_body()
            scenarios = state.params.merge("scenarios", body.get("scenarios") or {})
            r.json({"saved": True, "scenarios": scenarios})
            return True
        if path != "/api/calc":
            return False
        payload = r.read_body()
        scenarios = _validate_scenarios(payload.get("scenarios"), cfg["scenarios"])
        r.json(calc(state, cfg, scenarios))
    except Exception as e:  # noqa: BLE001
        r.json({"error": f"{type(e).__name__}: {e}"}, 500)
    return True


def make_handler(state: WorkbenchState, cfg: dict):
    def handle_get(h, path):
        return route_get(state, cfg, h, path)

    def handle_post(h, path):
        return route_post(state, cfg, h, path)

    return make_dispatch_handler(handle_get, handle_post)


def serve(root: Path, port: int = 8300) -> None:
    cfg = load_cfg(root)
    state = WorkbenchState(root, cfg["caliber"])
    state.load()  # 启动即装载数据，失败早暴露
    serve_quiet(make_handler(state, cfg), port,
                f"目标测算工作台已启动 → http://127.0.0.1:{port}  （Ctrl+C 退出；数据不出本机）")
