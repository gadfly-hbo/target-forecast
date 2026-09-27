"""本地 HTML 工作台：静态页 + JSON API。

只用标准库 http.server，无新增依赖；数据与测算全部在本机完成。
- GET  /            工作台页面
- GET  /style.css /app.js
- GET  /api/state   平台清单、历史月度指标、基线、默认情景（?reload=1 强制重读 data/）
- POST /api/calc    提交三档情景参数 → 重算人/场/货三视角 + 全渠道汇总
"""

from __future__ import annotations

import json
import mimetypes
import re
import urllib.parse
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import numpy as np
import pandas as pd
import yaml

from . import aggregate, demo, engine, ingest_agg, ingest_detail, report

STATIC_DIR = Path(__file__).resolve().parent / "static"

# 参数合法范围：增速 [-50%, +200%]
_GROWTH_RANGE = (-0.5, 2.0)


def load_cfg(root: Path) -> dict:
    with open(root / "config.yaml", encoding="utf-8") as f:
        return yaml.safe_load(f)


def _scan(d: Path) -> dict:
    if not d.exists():
        return {}
    return {p.stem: p for p in sorted(d.glob("*.xlsx")) if not p.name.startswith("~$")}


class WorkbenchState:
    """workspace/forecast 输入的惰性加载与缓存（线程锁保护）。"""

    def __init__(self, root: Path, caliber: dict):
        self.root = root
        self.caliber = caliber
        self.lock = threading.Lock()
        self.platforms: dict[str, dict] = {}
        self.demo_used = False

    def load(self, force: bool = False) -> None:
        with self.lock:
            if self.platforms and not force:
                return
            detail, agg = _scan(self.root / "workspace" / "forecast" / "orders"), _scan(self.root / "workspace" / "forecast" / "metrics")
            if not detail and not agg:
                print("workspace/forecast 为空，自动生成演示数据 …")
                demo.generate(self.root)
                detail, agg = _scan(self.root / "workspace" / "forecast" / "orders"), _scan(self.root / "workspace" / "forecast" / "metrics")
                self.demo_used = True
            else:
                self.demo_used = False
            platforms = {}
            for platform, path in detail.items():
                lines = ingest_detail.load_detail(path, platform)
                od = ingest_detail.classify_new(ingest_detail.order_level(lines),
                                                self.caliber["new_customer_window_days"])
                unified = ingest_detail.to_unified(od, platform)
                structure = ingest_detail.goods_structure(lines, self.caliber, lines["日期"].max())
                platforms[platform] = {"mode": "A", "unified": unified, "structure": structure}
            for platform, path in agg.items():
                df = ingest_agg.load_agg(path, platform)
                platforms[platform] = {"mode": "B", "unified": ingest_agg.to_unified(df, platform),
                                       "structure": None}
            self.platforms = platforms

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
    results = {}
    for platform, v in state.platforms.items():
        results[platform] = {"mode": v["mode"], **engine.run(v["unified"], v["structure"], scenarios, caliber)}

    main_parts, person_parts, field_parts = [], [], []
    for platform, r in results.items():
        main_df = r["field"] if r["main_view"] == "场" else r["person"]
        main_parts.append(main_df.assign(platform=platform))
        person_parts.append(r["person"].assign(platform=platform))
        if r["field"] is not None:
            field_parts.append(r["field"].assign(platform=platform))
    main_all = pd.concat(main_parts, ignore_index=True)
    person_all = pd.concat(person_parts, ignore_index=True)
    field_all = pd.concat(field_parts, ignore_index=True) if field_parts else None
    baselines = {p: r["baseline"] for p, r in results.items()}

    consolidated = aggregate.consolidate(person_all, main_all, field_all)
    plat_annual = aggregate.platform_annual(main_all, baselines)
    check = report._build_check_sheet(results)
    goods = report._build_goods_sheet(results)

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
        "consolidated": _sanitize(consolidated),
        "platform_annual": _sanitize(plat_annual),
        "check": _sanitize(check),
        "goods": _sanitize(goods),
        "target_range": results[next(iter(results))]["target_months"] if results else [],
    }


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

    def json(self, obj, code=200):
        body = json.dumps(obj, ensure_ascii=False, allow_nan=False).encode("utf-8")
        self.send(code, body, "application/json; charset=utf-8")


def route_get(state: WorkbenchState, cfg: dict, h: BaseHTTPRequestHandler, path: str) -> bool:
    """处理 GET；返回 False 表示未命中（调用方回 404）。path 保留 query string。"""
    r = _Responder(h)
    try:
        if path in ("/", "/index.html"):
            r.send(200, (STATIC_DIR / "index.html").read_bytes(), "text/html; charset=utf-8")
        elif path in ("/style.css", "/app.js"):
            f = STATIC_DIR / path.lstrip("/")
            ctype = mimetypes.guess_type(f)[0] or "application/octet-stream"
            r.send(200, f.read_bytes(), f"{ctype}; charset=utf-8")
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


def route_post(state: WorkbenchState, cfg: dict, h: BaseHTTPRequestHandler, path: str) -> bool:
    """处理 POST；返回 False 表示未命中（调用方回 404）。"""
    r = _Responder(h)
    try:
        if path != "/api/calc":
            return False
        n = int(h.headers.get("Content-Length") or 0)
        payload = json.loads(h.rfile.read(n) or b"{}")
        scenarios = _validate_scenarios(payload.get("scenarios"), cfg["scenarios"])
        r.json(calc(state, cfg, scenarios))
    except Exception as e:  # noqa: BLE001
        r.json({"error": f"{type(e).__name__}: {e}"}, 500)
    return True


def make_handler(state: WorkbenchState, cfg: dict):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, fmt, *args):  # 安静模式，只记录错误
            pass

        def do_GET(self):
            if not route_get(state, cfg, self, self.path):
                _Responder(self).send(404, b"not found", "text/plain; charset=utf-8")

        def do_POST(self):
            if not route_post(state, cfg, self, self.path):
                _Responder(self).send(404, b"not found", "text/plain; charset=utf-8")

    return Handler


def serve(root: Path, port: int = 8300) -> None:
    cfg = load_cfg(root)
    state = WorkbenchState(root, cfg["caliber"])
    state.load()  # 启动即装载数据，失败早暴露
    httpd = ThreadingHTTPServer(("127.0.0.1", port), make_handler(state, cfg))
    print(f"目标测算工作台已启动 → http://127.0.0.1:{port}  （Ctrl+C 退出；数据不出本机）")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\n已退出。")
