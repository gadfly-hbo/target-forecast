# -*- coding: utf-8 -*-
"""plans 持久化：本地文件 + 原子写 + 损坏隔离 + 修订乐观并发。

布局（root = 仓库根）：
    workspace/forecast/v2/
      plans/<plan_id>/draft.json
      plans/<plan_id>/versions/<version_key>.json
      plans/<plan_id>/jobs/<job_id>/{job.json, result.json}
      plans/<plan_id>/runs/<run_id>/{run.json, result.json, exports/}
      plans/<plan_id>/proposals/<proposal_id>.json
      snapshots/<snapshot_id>/{snapshot.json, unified_*.json, structure_*.json, source/}
      _staging/<upload_id>/<原始文件名>

规则：所有写 = 同目录临时文件 + os.replace；损坏文件隔离为 <name>.corrupt-<ts>，绝不覆盖；
单进程内用锁串行化写（工作台为本地单用户，跨进程并发由 base_revision 乐观并发兜底）。
"""
from __future__ import annotations

import json
import os
import threading
import time
from pathlib import Path

from . import models

V2_DIR = ("workspace", "forecast", "v2")


class StoreError(Exception):
    """存储层基础异常。"""


class NotFoundError(StoreError):
    """对象不存在。"""


class CorruptError(StoreError):
    """文件损坏（已隔离原文件）。"""


class ConflictError(StoreError):
    """修订冲突：base_revision 与当前不一致。"""


_LOCK = threading.Lock()


def v2_root(root: Path) -> Path:
    return Path(root) / Path(*V2_DIR)


def write_json(path: Path, obj) -> None:
    """原子写 JSON（tmp + os.replace）；NaN 直接拒绝（httpkit 同一约束）。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(models.sanitize(obj), ensure_ascii=False, indent=2,
                         allow_nan=False).encode("utf-8")
    tmp = path.with_name(f"{path.name}.tmp-{os.getpid()}-{time.time_ns()}")
    tmp.write_bytes(payload)
    os.replace(tmp, path)


def read_json(path: Path):
    """读取 JSON；不存在 → NotFoundError；损坏 → 隔离原文件后抛 CorruptError。"""
    path = Path(path)
    if not path.is_file():
        raise NotFoundError(str(path))
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError) as e:
        quarantine = path.with_name(f"{path.name}.corrupt-{int(time.time())}")
        os.replace(path, quarantine)
        raise CorruptError(f"{path.name} 已损坏，原文件已隔离为 {quarantine.name}: {e}")


def list_dirs(parent: Path) -> list:
    parent = Path(parent)
    if not parent.is_dir():
        return []
    return sorted(p for p in parent.iterdir() if p.is_dir() and not p.name.startswith((".", "_")))


def recover_jobs(root: Path) -> int:
    """重开恢复：所有 running 状态的 job 标记为 unknown（执行结果未知），返回处理数。"""
    n = 0
    plans_dir = v2_root(root) / "plans"
    for pdir in list_dirs(plans_dir):
        for jdir in list_dirs(pdir / "jobs"):
            jpath = jdir / "job.json"
            try:
                job = read_json(jpath)
            except StoreError:
                continue
            if job.get("status") == "running":
                job["status"] = "unknown"
                job["recovered_at"] = models.now_iso()
                write_json(jpath, job)
                n += 1
    return n


def locked():
    """写操作串行化锁（with store.locked(): ...）。"""
    return _LOCK
