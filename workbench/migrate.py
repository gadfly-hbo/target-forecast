"""workspace/ 数据布局迁移：plan/apply 分离，冲突跳过不覆盖。

映射（源相对仓库根 → 目标）：
    data/orders     → workspace/forecast/orders
    data/metrics    → workspace/forecast/metrics
    coupon_data     → workspace/coupon（子目录平移）
    output/coupon   → workspace/coupon/output
    output          → workspace/forecast/output

output/coupon 必须先于 output 处理（见 _DIR_MAP 顺序），否则优惠券导出会
落入 forecast 侧。冲突粒度为文件级（GRILL G1）：目标已存在且内容不同 → 跳过
并报告；内容相同 → 视为重复，清源（保证幂等，G2/apply 可重复执行）。
"""
from __future__ import annotations

import shutil
from dataclasses import dataclass, field
from pathlib import Path

_DIR_MAP = [
    ("data/orders", "workspace/forecast/orders"),
    ("data/metrics", "workspace/forecast/metrics"),
    ("coupon_data", "workspace/coupon"),
    ("output/coupon", "workspace/coupon/output"),
    ("output", "workspace/forecast/output"),
]


@dataclass
class Plan:
    moves: list[tuple[Path, Path]] = field(default_factory=list)       # (src, dst) 待移动
    dedups: list[Path] = field(default_factory=list)                   # 目标同内容重复，apply 时清源
    conflicts: list[tuple[Path, Path]] = field(default_factory=list)   # 目标已存在内容不同，跳过
    sources: list[Path] = field(default_factory=list)                  # 参与映射的源目录（apply 后清理空目录）


@dataclass
class Report:
    moved: int = 0
    dedup: int = 0
    conflicts: list[tuple[Path, Path]] = field(default_factory=list)
    removed_dirs: list[Path] = field(default_factory=list)


def plan(root: Path) -> Plan:
    root = Path(root)
    p = Plan()
    claimed: set[Path] = set()
    for src_rel, dst_rel in _DIR_MAP:
        src = root / src_rel
        if not src.exists():
            continue
        p.sources.append(src)
        files = [src] if src.is_file() else sorted(f for f in src.rglob("*") if f.is_file())
        for f in files:
            if f in claimed:
                continue
            claimed.add(f)
            dst = root / dst_rel / f.relative_to(src)
            if not dst.exists():
                p.moves.append((f, dst))
            elif dst.is_dir():
                # 目标位置被目录占用：无法比对或覆盖，按冲突跳过（review round 1）
                p.conflicts.append((f, dst))
            elif f.read_bytes() == dst.read_bytes():
                p.dedups.append(f)
            else:
                p.conflicts.append((f, dst))
    return p


def apply(root: Path) -> Report:
    root = Path(root)
    p = plan(root)
    rep = Report(conflicts=p.conflicts)

    for src, dst in p.moves:
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(src), str(dst))
        rep.moved += 1

    for src in p.dedups:
        src.unlink()
        rep.dedup += 1

    # 自底向上删除搬空的源目录（仅删空，冲突遗留的非空目录保留，GRILL G2）
    removed: set[Path] = set()

    def _rmdir_empty(d: Path) -> None:
        try:
            d.rmdir()
        except OSError:
            return
        removed.add(d)
        if d.parent != root and d.parent != d:
            _rmdir_empty(d.parent)

    for src in p.sources:
        if not src.is_dir() or not src.exists():
            continue
        for d in sorted((x for x in src.rglob("*") if x.is_dir()), key=lambda x: len(x.parts), reverse=True):
            _rmdir_empty(d)
        _rmdir_empty(src)
    rep.removed_dirs = sorted(removed)
    return rep
