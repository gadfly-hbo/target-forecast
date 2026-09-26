# -*- coding: utf-8 -*-
"""本地工作台服务：标准库 http.server + JSON API + 静态页（无框架、离线可用）。

- GET  / /style.css /app.js
- GET  /api/state                    引擎版本、场景清单、运行清单、目录
- POST /api/demo                     创建并保存合成演示场景
- GET  /api/scenario/{id}            场景全文
- POST /api/scenario/save            保存场景（按 scenario_id）
- POST /api/import                   分桶/订单明细导入 → 快照问题清单 + 基准预览
- POST /api/compare                  场景测算比较（输入不合法 → 422 + 原因）
- POST /api/stress                   敏感性情景
- POST /api/run                      封存运行 + 三格式导出
- GET  /api/runs / /api/run/{id}     运行清单 / 运行详情
- POST /api/decision                 保存人工决策
- GET  /api/export/{id}/{kind}       下载导出文件
- GET  /api/templates                生成导入模板
"""
from __future__ import annotations

import json
import mimetypes
import os
import re
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from . import ENGINE_VERSION
from .compare import compare
from .exports import export_all
from .ingest import generate_templates, import_buckets, import_orders
from .review import DEVIATION_CATEGORIES, create_review
from .spec import SpecError, load_spec, validate_spec
from .storage import Store
from .stress import stress_test
from .synthetic import build_synthetic_spec

STATIC_DIR = Path(__file__).resolve().parent / "static"


class Workbench:
    """线程安全的工作台上下文：Store + 导出目录。"""

    def __init__(self, data_dir: str = "coupon_data", out_dir: str = "output/coupon",
                 templates_dir: str = "templates"):
        self.data_dir = data_dir
        self.out_dir = out_dir
        self.templates_dir = templates_dir
        self.store = Store(data_dir)
        self.lock = threading.Lock()


def _json_bytes(obj) -> bytes:
    return json.dumps(obj, ensure_ascii=False).encode("utf-8")


def make_handler(app: Workbench):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, fmt, *args):  # 安静模式
            pass

        # ---------- 基础 ----------
        def _send(self, code: int, body: bytes, ctype: str):
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def _json(self, obj, code: int = 200):
            self._send(code, _json_bytes(obj), "application/json; charset=utf-8")

        def _read_body(self) -> dict:
            length = int(self.headers.get("Content-Length") or 0)
            if not length:
                return {}
            return json.loads(self.rfile.read(length).decode("utf-8"))

        def _static(self, name: str):
            path = (STATIC_DIR / name).resolve()
            if not path.is_file():
                self._json({"error": "not found"}, 404)
                return
            ctype = mimetypes.guess_type(str(path))[0] or "application/octet-stream"
            self._send(200, path.read_bytes(), ctype + "; charset=utf-8")

        # ---------- GET ----------
        def do_GET(self):
            if self.path in ("/", "/index.html"):
                self._static("index.html")
            elif self.path == "/style.css":
                self._static("style.css")
            elif self.path == "/app.js":
                self._static("app.js")
            elif self.path == "/api/state":
                with app.lock:
                    self._json({
                        "engine_version": ENGINE_VERSION,
                        "data_dir": app.data_dir,
                        "out_dir": app.out_dir,
                        "scenarios": _scenario_ids(app),
                        "runs": app.store.list_runs(),
                        "boundary": "本机运行：数据与测算全部在本机完成，不上传明细订单",
                    })
            elif m := re.fullmatch(r"/api/scenario/([^/]+)", self.path):
                try:
                    with app.lock:
                        spec = app.store.load_spec(m.group(1))
                    self._json(spec.to_dict())
                except (FileNotFoundError, SpecError) as exc:
                    self._json({"error": str(exc)}, 404)
            elif self.path == "/api/review/list":
                with app.lock:
                    rv_dir = Path(app.data_dir) / "reviews"
                    ids = sorted(p.stem for p in rv_dir.glob("*.json")) if rv_dir.exists() else []
                self._json({"reviewed_runs": ids})
            elif m := re.fullmatch(r"/api/runs", self.path):
                with app.lock:
                    self._json(app.store.list_runs())
            elif m := re.fullmatch(r"/api/run/([^/]+)", self.path):
                try:
                    with app.lock:
                        run = app.store.load_run(m.group(1))
                    self._json(run)
                except FileNotFoundError:
                    self._json({"error": "run not found"}, 404)
            elif m := re.fullmatch(r"/api/export/([^/]+)/(markdown|csv_candidates|csv_ledger|json)", self.path):
                run_id, kind = m.group(1), m.group(2)
                fname = {"markdown": f"{run_id}_决策摘要.md",
                         "csv_candidates": f"{run_id}_候选表.csv",
                         "csv_ledger": f"{run_id}_分支账本.csv",
                         "json": f"{run_id}_运行记录.json"}[kind]
                path = Path(app.out_dir) / fname
                if not path.is_file():
                    self._json({"error": f"导出文件不存在：{fname}（先运行 /api/run）"}, 404)
                    return
                ctype = {"markdown": "text/markdown", "json": "application/json"}.get(
                    kind, "text/csv")
                self._send(200, path.read_bytes(), ctype + "; charset=utf-8")
            elif self.path == "/api/templates":
                with app.lock:
                    files = generate_templates(app.templates_dir)
                self._json({"files": files, "dir": app.templates_dir})
            else:
                self._json({"error": "not found"}, 404)

        # ---------- POST ----------
        def do_POST(self):
            try:
                if self.path == "/api/demo":
                    spec = build_synthetic_spec()
                    with app.lock:
                        app.store.save_spec(spec)
                    self._json({"scenario_id": spec.scenario_id,
                                "validation": validate_spec(spec),
                                "scenario": spec.to_dict()})
                elif self.path == "/api/scenario/save":
                    body = self._read_body()
                    spec = load_spec(body.get("scenario", {}))
                    with app.lock:
                        path = app.store.save_spec(spec)
                    self._json({"saved": path, "scenario_id": spec.scenario_id,
                                "validation": validate_spec(spec)})
                elif self.path == "/api/import":
                    body = self._read_body()
                    mode = body.get("mode", "buckets")
                    meta = {"source": body.get("meta", {}).get("source", "workbench"),
                            "snapshot_id": body.get("meta", {}).get("snapshot_id", "workbench-import"),
                            **body.get("meta", {})}
                    rows = body.get("rows", [])
                    with app.lock:
                        snap = (import_buckets if mode == "buckets" else import_orders)(rows, meta=meta)
                    self._json({
                        "issues": snap.issues,
                        "row_count": snap.row_count,
                        "baskets": [{"amount_cents": b.amount_cents, "weight": round(b.weight, 6),
                                     "margin_rate": b.margin_rate, "label": b.label,
                                     "bucket_min_cents": b.bucket_min_cents,
                                     "bucket_max_cents": b.bucket_max_cents} for b in snap.baskets],
                    })
                elif self.path == "/api/compare":
                    body = self._read_body()
                    try:
                        spec = load_spec(body.get("scenario", {}))
                    except SpecError as exc:
                        self._json({"error": f"场景不合法：{exc}"}, 422)
                        return
                    res = compare(spec)
                    self._json(_comparison_payload(res))
                elif self.path == "/api/stress":
                    body = self._read_body()
                    try:
                        spec = load_spec(body.get("scenario", {}))
                    except SpecError as exc:
                        self._json({"error": f"场景不合法：{exc}"}, 422)
                        return
                    variants = body.get("variants") or {}
                    if not variants:
                        self._json({"error": "无情景变体：敏感性范围必须显式指定（不内置 ±20%）"}, 422)
                        return
                    res = stress_test(spec, variants)
                    self._json({"baseline": res.baseline, "scenarios": res.scenarios,
                                "sensitive_params": res.sensitive_params})
                elif self.path == "/api/run":
                    body = self._read_body()
                    try:
                        spec = load_spec(body.get("scenario", {}))
                    except SpecError as exc:
                        self._json({"error": f"场景不合法：{exc}"}, 422)
                        return
                    with app.lock:
                        app.store.save_spec(spec)
                        cmp_res = compare(spec)
                        stress = (stress_test(spec, body.get("variants") or {})
                                  if body.get("with_stress") else None)
                        run = app.store.record_run(spec, cmp_res, stress=stress)
                        if body.get("decision"):
                            app.store.save_decision(run["run_id"], body["decision"])
                            run["decision"] = body["decision"]
                        paths = export_all(run, out_dir=app.out_dir,
                                           decision=body.get("decision"))
                    self._json({"run_id": run["run_id"], "exports": paths,
                                "conclusion": cmp_res.conclusion})
                elif self.path == "/api/review":
                    body = self._read_body()
                    run_id = body.get("run_id")
                    if not run_id:
                        self._json({"error": "缺少 run_id"}, 422)
                        return
                    try:
                        with app.lock:
                            review = create_review(
                                app.store, run_id,
                                actuals=body.get("actuals") or {},
                                notes=body.get("notes") or {},
                                confirmed_by=body.get("confirmed_by", ""),
                                params_patch=body.get("params_patch"),
                                chosen_label=body.get("chosen_label"))
                    except (ValueError, FileNotFoundError, SpecError) as exc:
                        self._json({"error": str(exc)}, 422)
                        return
                    self._json({"review": review,
                                "deviation_categories": DEVIATION_CATEGORIES})
                elif self.path == "/api/decision":
                    body = self._read_body()
                    run_id = body.get("run_id")
                    if not run_id:
                        self._json({"error": "缺少 run_id"}, 422)
                        return
                    with app.lock:
                        path = app.store.save_decision(run_id, body)
                    self._json({"saved": path})
                else:
                    self._json({"error": "not found"}, 404)
            except SpecError as exc:
                self._json({"error": str(exc)}, 422)
            except (ValueError, KeyError, TypeError) as exc:
                self._json({"error": f"请求不合法：{exc}"}, 422)


    def _scenario_ids(app) -> list[str]:
        sc_dir = Path(app.data_dir) / "scenarios"
        if not sc_dir.exists():
            return []
        return sorted(p.stem for p in sc_dir.glob("*.json"))

    return Handler


def _comparison_payload(res) -> dict:
    return {
        "rows": res.rows,
        "ranking": [r["label"] for r in res.ranking],
        "pareto": [r["label"] for r in res.pareto],
        "conclusion": res.conclusion,
        "objective": res.objective,
    }


def serve(port: int = 8310, data_dir: str = "coupon_data"):
    app = Workbench(data_dir=data_dir)
    httpd = ThreadingHTTPServer(("127.0.0.1", port), make_handler(app))
    print(f"优惠券测算工作台：http://127.0.0.1:{port}（数据目录 {data_dir}，本机运行）")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        httpd.shutdown()
