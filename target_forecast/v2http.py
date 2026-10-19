# -*- coding: utf-8 -*-
"""v2 HTTP 适配层：把已批准 UI 与外部调用接到 plans 业务层（唯一更新入口）。

路由（壳内 /t/forecast 前缀已剥离；standalone serve 时挂 / 前缀）：

GET  /api/v2/state                                方案列表/运行汇总/引擎版本/存储状态
GET  /api/v2/plans                                方案列表
POST /api/v2/plans                                创建（{need,title?} 或 {source:"config"}）
GET  /api/v2/plans/<pid>                          草稿详情（修订/确认/就绪/提案/最近 job/运行）
POST /api/v2/plans/<pid>/patch                    update_draft {base_revision, patch}
POST /api/v2/plans/<pid>/confirm                  {kind, base_revision}
POST /api/v2/uploads                              原始字节 + X-Filename → 预览（201）
POST /api/v2/plans/<pid>/import                   {items, base_revision} → 快照+质量
GET  /api/v2/workspace-sources                    工作区旧输入扫描（含 A/B 冲突）
POST /api/v2/plans/<pid>/jobs                     开始计算（202）
GET  /api/v2/plans/<pid>/jobs/<jid>               轮询状态（done 时带结果）
POST /api/v2/plans/<pid>/jobs/<jid>/cancel        停止
POST /api/v2/plans/<pid>/runs                     保存 {job_id}（201 新建 / 200 去重）
GET  /api/v2/plans/<pid>/runs                     运行列表
GET  /api/v2/plans/<pid>/runs/<rid>               运行详情（含结果快照）
GET  /api/v2/plans/<pid>/runs/<rid>/export/<fmt>  下载导出（xlsx/csv/json）
POST /api/v2/plans/<pid>/proposals                AI 提案 dry-run（201）
POST /api/v2/plans/<pid>/proposals/<prid>/apply   采纳 {base_revision}
POST /api/v2/plans/<pid>/proposals/<prid>/discard 放弃

错误分类：400 结构 / 404 不存在 / 409 修订冲突·过期 / 422 业务校验 / 500 未预期。
"""
from __future__ import annotations

import re
from pathlib import Path

from tools_common.httpkit import Responder

from . import engine as engine_mod
from .plans import service, store
from .plans.service import StaleError, ValidationError
from .plans.store import ConflictError, CorruptError, NotFoundError

_ID = r"([A-Za-z0-9_\-]+)"


def _err(r: Responder, e: Exception) -> None:
    """异常 → 错误分类响应（业务可读、保留用户输入、指向下一步）。"""
    if isinstance(e, StaleError):
        r.json({"error": str(e), "code": "stale"}, 409)
    elif isinstance(e, ConflictError):
        r.json({"error": str(e), "code": "conflict"}, 409)
    elif isinstance(e, ValidationError):
        r.json({"error": str(e), "code": "validation", "issues": e.issues}, 422)
    elif isinstance(e, NotFoundError):
        r.json({"error": "对象不存在或已被移除", "code": "not_found"}, 404)
    elif isinstance(e, CorruptError):
        r.json({"error": str(e), "code": "corrupt"}, 500)
    else:
        r.json({"error": f"{type(e).__name__}: {e}", "code": "internal"}, 500)


def _plan_detail(root: Path, plan_id: str) -> dict:
    draft = service.load_draft(root, plan_id)
    vdir = store.v2_root(root) / "plans" / plan_id / "versions"
    versions = []
    if vdir.is_dir():
        for f in sorted(vdir.glob("*.json")):
            try:
                v = store.read_json(f)
                versions.append({"name": v["name"], "created": v["created"],
                                 "version_key": v["version_key"]})
            except store.StoreError:
                continue
    out = {"draft": draft,
           "confirmation_status": service.confirmation_status(draft),
           "readiness": service.readiness(draft),
           "content_key": service.run_content_key(draft),
           "versions": versions,
           "proposals": service.list_proposals(root, plan_id),
           "jobs": [{k: j[k] for k in ("job_id", "status", "created", "finished", "content_key")
                     if k in j} | ({"error": j["error"]} if j.get("error") else {})
                    for j in service.list_jobs(root, plan_id)[:5]],
           "runs": service.list_runs(root, plan_id)}
    snap_id = draft.get("data", {}).get("snapshot_id")
    if snap_id:
        out["snapshot"] = service.snapshot_summary(service.load_snapshot(root, snap_id))
    return out


def route_get(root: Path, h, path: str) -> bool:
    """处理 /api/v2/* 的 GET；未命中返回 False。"""
    if not path.startswith("/api/v2/"):
        return False
    r = Responder(h)
    try:
        p = path.split("?")[0]
        if p == "/api/v2/state":
            r.json({"engine_version": engine_mod.ENGINE_VERSION,
                    "plans": service.list_plans(root),
                    "runs": service.list_runs(root)[:20]})
        elif p == "/api/v2/plans":
            r.json({"plans": service.list_plans(root)})
        elif p == "/api/v2/workspace-sources":
            r.json(service.workspace_sources(root))
        elif p == "/api/v2/assistant-params-legacy":
            from urllib.parse import parse_qs
            q = parse_qs(path.split("?", 1)[1] if "?" in path else "")
            pid = (q.get("plan_id") or [""])[0]
            if not pid:
                r.json({"error": "缺少 plan_id", "code": "validation"}, 422)
                return True
            r.json(service.assistant_params_preview(root, pid))
        elif p == "/api/v2/legacy-artifacts":
            r.json({"artifacts": service.legacy_artifacts(root)})
        elif m := re.fullmatch(r"/api/v2/legacy-artifacts/(.+)", p):
            import urllib.parse
            rel = urllib.parse.unquote(m.group(1))
            if ".." in Path(rel).parts:
                r.json({"error": "非法路径", "code": "validation"}, 422)
                return True
            f = Path(root) / "workspace" / "forecast" / "output" / rel
            if not f.is_file():
                r.json({"error": "旧版产物不存在", "code": "not_found"}, 404)
                return True
            import mimetypes
            ctype = mimetypes.guess_type(str(f))[0] or "application/octet-stream"
            ascii_fallback = f"legacy{f.suffix}"
            r.h.send_response(200)
            r.h.send_header("Content-Type", ctype)
            r.h.send_header("Content-Length", str(f.stat().st_size))
            r.h.send_header("Content-Disposition",
                            f"attachment; filename=\"{ascii_fallback}\"; "
                            f"filename*=UTF-8''{urllib.parse.quote(f.name)}")
            r.h.send_header("Cache-Control", "no-store")
            r.h.end_headers()
            r.h.wfile.write(f.read_bytes())
        elif m := re.fullmatch(rf"/api/v2/plans/{_ID}", p):
            r.json(_plan_detail(root, m.group(1)))
        elif m := re.fullmatch(rf"/api/v2/plans/{_ID}/proposals", p):
            r.json({"proposals": service.list_proposals(root, m.group(1))})
        elif m := re.fullmatch(rf"/api/v2/plans/{_ID}/jobs/{_ID}", p):
            r.json(service.get_job(root, m.group(1), m.group(2)))
        elif m := re.fullmatch(rf"/api/v2/plans/{_ID}/runs", p):
            r.json({"runs": service.list_runs(root, m.group(1))})
        elif m := re.fullmatch(rf"/api/v2/plans/{_ID}/runs/{_ID}", p):
            run = service.get_run(root, m.group(1), m.group(2))
            r.json({"run": run, "result": service.get_run_result(root, m.group(1), m.group(2))})
        elif m := re.fullmatch(rf"/api/v2/plans/{_ID}/runs/{_ID}/export/([a-z]+)", p):
            import urllib.parse
            out = service.export_run(root, m.group(1), m.group(2), m.group(3))
            f = Path(out["file"])
            ctype = {"xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                     "csv": "application/zip", "json": "application/json; charset=utf-8"}[m.group(3)]
            ascii_fallback = f"export_{m.group(2)}.{f.suffix.lstrip('.')}"
            r.h.send_response(200)
            r.h.send_header("Content-Type", ctype)
            r.h.send_header("Content-Length", str(f.stat().st_size))
            # 中文文件名按 RFC 5987 编码（latin-1 头不能直接放中文）
            r.h.send_header("Content-Disposition",
                            f"attachment; filename=\"{ascii_fallback}\"; "
                            f"filename*=UTF-8''{urllib.parse.quote(f.name)}")
            r.h.send_header("Cache-Control", "no-store")
            r.h.end_headers()
            r.h.wfile.write(f.read_bytes())
        else:
            return False
    except Exception as e:  # noqa: BLE001 —— 错误分类后如实回给页面
        _err(r, e)
    return True


def route_post(root: Path, h, path: str) -> bool:
    """处理 /api/v2/* 的 POST；未命中返回 False。"""
    if not path.startswith("/api/v2/"):
        return False
    r = Responder(h)
    try:
        p = path.split("?")[0]
        if p == "/api/v2/plans":
            body = r.read_body()
            if body.get("source") == "config":
                draft = service.create_plan(root, body.get("need", ""), body.get("title"),
                                            source="import")
            else:
                draft = service.create_plan(root, body.get("need", ""), body.get("title"))
            r.json(_plan_detail(root, draft["plan_id"]), 201)
        elif p == "/api/v2/uploads":
            import urllib.parse
            filename = urllib.parse.unquote(h.headers.get("X-Filename", "upload.xlsx"))
            out = service.stage_upload(root, filename, r.read_raw_body())
            r.json(out, 201)
        elif m := re.fullmatch(rf"/api/v2/plans/{_ID}/patch", p):
            body = r.read_body()
            service.update_draft(root, m.group(1), body.get("patch") or {},
                                 base_revision=int(body.get("base_revision")),
                                 source=body.get("source") or "manual",
                                 description=body.get("description"))
            r.json(_plan_detail(root, m.group(1)))
        elif m := re.fullmatch(rf"/api/v2/plans/{_ID}/confirm", p):
            body = r.read_body()
            service.confirm(root, m.group(1), str(body.get("kind")),
                            base_revision=int(body.get("base_revision")))
            r.json(_plan_detail(root, m.group(1)))
        elif m := re.fullmatch(rf"/api/v2/plans/{_ID}/import", p):
            body = r.read_body()
            out = service.import_data(root, m.group(1), body.get("items") or [],
                                      base_revision=int(body.get("base_revision")))
            r.json({**_plan_detail(root, m.group(1)), "snapshot": out["snapshot"]})
        elif m := re.fullmatch(rf"/api/v2/plans/{_ID}/import-synthetic", p):
            body = r.read_body()
            out = service.import_synthetic(root, m.group(1),
                                           base_revision=int(body.get("base_revision")))
            r.json({**_plan_detail(root, m.group(1)), "snapshot": out["snapshot"]})
        elif m := re.fullmatch(rf"/api/v2/plans/{_ID}/import-assistant-params", p):
            body = r.read_body()
            out = service.import_assistant_params(root, m.group(1),
                                                  base_revision=int(body.get("base_revision")))
            r.json({**_plan_detail(root, m.group(1)),
                    "merged": out["merged"], "unknown_fields": out["unknown_fields"]})
        elif m := re.fullmatch(rf"/api/v2/plans/{_ID}/jobs", p):
            body = r.read_body()
            job = service.start_run(root, m.group(1),
                                    base_revision=int(body.get("base_revision")))
            job.pop("result", None)
            r.json(job, 202)
        elif m := re.fullmatch(rf"/api/v2/plans/{_ID}/jobs/{_ID}/cancel", p):
            r.json(service.cancel_job(root, m.group(1), m.group(2)))
        elif m := re.fullmatch(rf"/api/v2/plans/{_ID}/runs", p):
            body = r.read_body()
            out = service.save_run(root, m.group(1), str(body.get("job_id")))
            r.json(out, 200 if out["duplicate"] else 201)
        elif m := re.fullmatch(rf"/api/v2/plans/{_ID}/proposals", p):
            body = r.read_body()
            proposal = service.propose_change(root, m.group(1), str(body.get("scenario")),
                                              body.get("patches") or {},
                                              body.get("rationale", ""),
                                              base_revision=int(body.get("base_revision")))
            r.json(proposal, 201)
        elif m := re.fullmatch(rf"/api/v2/plans/{_ID}/proposals/{_ID}/apply", p):
            body = r.read_body()
            out = service.apply_proposal(root, m.group(1), m.group(2),
                                         base_revision=int(body.get("base_revision")))
            r.json({**_plan_detail(root, m.group(1)), "proposal": out["proposal"]})
        elif m := re.fullmatch(rf"/api/v2/plans/{_ID}/proposals/{_ID}/discard", p):
            proposal = service.discard_proposal(root, m.group(1), m.group(2))
            r.json({"proposal": proposal})
        else:
            return False
    except Exception as e:  # noqa: BLE001
        _err(r, e)
    return True
