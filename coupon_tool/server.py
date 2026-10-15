# -*- coding: utf-8 -*-
"""本地工作台服务：标准库 http.server + JSON API + 静态页（无框架、离线可用）。

路由逻辑以 route_get/route_post 模块级函数实现（单一事实源）：独立 server 的
do_GET/do_POST 与 workbench 壳的插件分发共用同一函数；path 为含 query string 的
请求路径（壳分发时已剥离 /t/coupon 前缀）。

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

import re
import threading
from pathlib import Path

from tools_common.httpkit import Responder, make_dispatch_handler, serve_quiet

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

    def __init__(self, data_dir: str = "workspace/coupon", out_dir: str = "workspace/coupon/output",
                 templates_dir: str = "templates"):
        self.data_dir = data_dir
        self.out_dir = out_dir
        self.templates_dir = templates_dir
        self.store = Store(data_dir)
        self.lock = threading.Lock()


def _scenario_ids(app: Workbench) -> list[str]:
    sc_dir = Path(app.data_dir) / "scenarios"
    if not sc_dir.exists():
        return []
    return sorted(p.stem for p in sc_dir.glob("*.json"))


def _comparison_payload(res) -> dict:
    return {
        "rows": res.rows,
        "ranking": [r["label"] for r in res.ranking],
        "pareto": [r["label"] for r in res.pareto],
        "conclusion": res.conclusion,
        "objective": res.objective,
    }


def _load_spec_or_422(r, body):
    """compare/stress/run 共用的 load_spec 短路助手；失败时已回 422（带前缀）并返回 None。

    注意只有这三条路由用；scenario/save 的 load_spec 走外层 catch（无前缀），勿统一。
    """
    try:
        return load_spec(body.get("scenario", {}))
    except SpecError as exc:
        r.json({"error": f"场景不合法：{exc}"}, 422)
        return None


# ---------- GET handlers（正则 handler 额外接收 match 对象） ----------

def _g_index(app, r):
    r.static("index.html")


def _g_css(app, r):
    r.static("style.css")


def _g_js(app, r):
    r.static("app.js")


def _g_state(app, r):
    with app.lock:
        r.json({
            "engine_version": ENGINE_VERSION,
            "data_dir": app.data_dir,
            "out_dir": app.out_dir,
            "scenarios": _scenario_ids(app),
            "runs": app.store.list_runs(),
            "boundary": "本机运行：数据与测算全部在本机完成，不上传明细订单",
        })


def _g_scenario(app, r, m):
    try:
        with app.lock:
            spec = app.store.load_spec(m.group(1))
        r.json(spec.to_dict())
    except (FileNotFoundError, SpecError) as exc:
        r.json({"error": str(exc)}, 404)


def _g_review_list(app, r):
    with app.lock:
        rv_dir = Path(app.data_dir) / "reviews"
        ids = sorted(p.stem for p in rv_dir.glob("*.json")) if rv_dir.exists() else []
    r.json({"reviewed_runs": ids})


def _g_runs(app, r):
    with app.lock:
        r.json(app.store.list_runs())


def _g_run_detail(app, r, m):
    try:
        with app.lock:
            run = app.store.load_run(m.group(1))
        r.json(run)
    except FileNotFoundError:
        r.json({"error": "run not found"}, 404)


def _g_export(app, r, m):
    run_id, kind = m.group(1), m.group(2)
    fname = {"markdown": f"{run_id}_决策摘要.md",
             "csv_candidates": f"{run_id}_候选表.csv",
             "csv_ledger": f"{run_id}_分支账本.csv",
             "json": f"{run_id}_运行记录.json"}[kind]
    fpath = Path(app.out_dir) / fname
    if not fpath.is_file():
        r.json({"error": f"导出文件不存在：{fname}（先运行 /api/run）"}, 404)
        return
    ctype = {"markdown": "text/markdown", "json": "application/json"}.get(kind, "text/csv")
    r.send(200, fpath.read_bytes(), ctype + "; charset=utf-8")


def _g_templates(app, r):
    with app.lock:
        files = generate_templates(app.templates_dir)
    r.json({"files": files, "dir": app.templates_dir})


GET_EXACT = {
    "/": _g_index, "/index.html": _g_index,
    "/style.css": _g_css,
    "/app.js": _g_js,
    "/api/state": _g_state,
    "/api/review/list": _g_review_list,
    "/api/runs": _g_runs,
    "/api/templates": _g_templates,
}

GET_PATTERNS = [  # 顺序即匹配语义，保持现状
    (re.compile(r"/api/scenario/([^/]+)"), _g_scenario),
    (re.compile(r"/api/run/([^/]+)"), _g_run_detail),
    (re.compile(r"/api/export/([^/]+)/(markdown|csv_candidates|csv_ledger|json)"), _g_export),
]


def route_get(app: Workbench, h, path: str) -> bool:
    """处理 GET；返回 False 表示未命中（调用方回 404）。"""
    handler, m = GET_EXACT.get(path), None
    if handler is None:
        for pattern, fn in GET_PATTERNS:
            m = pattern.fullmatch(path)
            if m:
                handler = fn
                break
    if handler is None:
        return False
    r = Responder(h, STATIC_DIR)
    handler(app, r, m) if m is not None else handler(app, r)
    return True


# ---------- POST handlers（body 各自读取；dispatch 层不预读） ----------

def _h_demo(app, r):
    spec = build_synthetic_spec()
    with app.lock:
        app.store.save_spec(spec)
    r.json({"scenario_id": spec.scenario_id,
            "validation": validate_spec(spec),
            "scenario": spec.to_dict()})


def _h_scenario_save(app, r):
    body = r.read_body()
    spec = load_spec(body.get("scenario", {}))  # SpecError 走外层（无前缀）
    with app.lock:
        fpath = app.store.save_spec(spec)
    r.json({"saved": fpath, "scenario_id": spec.scenario_id,
            "validation": validate_spec(spec)})


def _h_import(app, r):
    body = r.read_body()
    mode = body.get("mode", "buckets")
    meta = {"source": body.get("meta", {}).get("source", "workbench"),
            "snapshot_id": body.get("meta", {}).get("snapshot_id", "workbench-import"),
            **body.get("meta", {})}
    rows = body.get("rows", [])
    with app.lock:
        snap = (import_buckets if mode == "buckets" else import_orders)(rows, meta=meta)
    r.json({
        "issues": snap.issues,
        "row_count": snap.row_count,
        "baskets": [{"amount_cents": b.amount_cents, "weight": round(b.weight, 6),
                     "margin_rate": b.margin_rate, "label": b.label,
                     "bucket_min_cents": b.bucket_min_cents,
                     "bucket_max_cents": b.bucket_max_cents} for b in snap.baskets],
    })


def _h_compare(app, r):
    body = r.read_body()
    spec = _load_spec_or_422(r, body)
    if spec is None:
        return
    res = compare(spec)
    r.json(_comparison_payload(res))


def _h_stress(app, r):
    body = r.read_body()
    spec = _load_spec_or_422(r, body)
    if spec is None:
        return
    variants = body.get("variants") or {}
    if not variants:
        r.json({"error": "无情景变体：敏感性范围必须显式指定（不内置 ±20%）"}, 422)
        return
    res = stress_test(spec, variants)
    r.json({"baseline": res.baseline, "scenarios": res.scenarios,
            "sensitive_params": res.sensitive_params})


def _h_run(app, r):
    body = r.read_body()
    spec = _load_spec_or_422(r, body)
    if spec is None:
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
    r.json({"run_id": run["run_id"], "exports": paths,
            "conclusion": cmp_res.conclusion})


def _h_review(app, r):
    body = r.read_body()
    run_id = body.get("run_id")
    if not run_id:
        r.json({"error": "缺少 run_id"}, 422)
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
        r.json({"error": str(exc)}, 422)
        return
    r.json({"review": review,
            "deviation_categories": DEVIATION_CATEGORIES})


def _h_decision(app, r):
    body = r.read_body()
    run_id = body.get("run_id")
    if not run_id:
        r.json({"error": "缺少 run_id"}, 422)
        return
    with app.lock:
        fpath = app.store.save_decision(run_id, body)
    r.json({"saved": fpath})


POST_ROUTES = {
    "/api/demo": _h_demo,
    "/api/scenario/save": _h_scenario_save,
    "/api/import": _h_import,
    "/api/compare": _h_compare,
    "/api/stress": _h_stress,
    "/api/run": _h_run,
    "/api/review": _h_review,
    "/api/decision": _h_decision,
}


def route_post(app: Workbench, h, path: str) -> bool:
    """处理 POST；返回 False 表示未命中（调用方回 404）。

    外层异常映射：SpecError → 422 str(exc)；ValueError/KeyError/TypeError/OverflowError
    → 422 "请求不合法：{exc}"（OverflowError 覆盖 float() 强转溢出——q_table.q、
    new_basket.weight、/api/import 行等不经 _int_cents 的路径）；
    FileNotFoundError 仅 /api/review 内层捕获。
    """
    handler = POST_ROUTES.get(path)
    if handler is None:
        return False
    r = Responder(h, STATIC_DIR)
    try:
        handler(app, r)
    except SpecError as exc:
        r.json({"error": str(exc)}, 422)
    except (ValueError, KeyError, TypeError, OverflowError) as exc:
        r.json({"error": f"请求不合法：{exc}"}, 422)
    return True


def make_handler(app: Workbench):
    def handle_get(h, path):
        return route_get(app, h, path)

    def handle_post(h, path):
        return route_post(app, h, path)

    return make_dispatch_handler(handle_get, handle_post)


def serve(port: int = 8310, data_dir: str = "workspace/coupon"):
    app = Workbench(data_dir=data_dir)
    serve_quiet(make_handler(app), port,
                f"优惠券测算工作台：http://127.0.0.1:{port}（数据目录 {data_dir}，本机运行）")
