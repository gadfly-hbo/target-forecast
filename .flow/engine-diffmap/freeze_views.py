#!/usr/bin/env python3
"""引擎 diff-map 工具（dev-flow 阶段A证据）：冻结 pipeline 全量输出 / 对照两版差异。

用法（仓库根，.venv 解释器）：
    .venv/bin/python .flow/engine-diffmap/freeze_views.py freeze <out_dir>
    .venv/bin/python .flow/engine-diffmap/freeze_views.py compare <before_dir> <after_dir>

只读 workspace/forecast 输入，不写任何业务目录。序列化用 CSV（全精度）+ JSON manifest。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from target_forecast import pipeline, server  # noqa: E402


def _dump_df(df: pd.DataFrame | None, path: Path) -> None:
    if df is None:
        path.with_suffix(".none").write_text("None", encoding="utf-8")
        return
    df.to_csv(path, index=False)


def freeze(out_dir: Path) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    cfg = server.load_cfg(ROOT)
    caliber = {**cfg["caliber"], "target_months": cfg["target"]["months"]}
    detail, agg = pipeline.scan_inputs(ROOT)
    platforms = pipeline.ingest_platforms(detail, agg, cfg["caliber"])
    results = pipeline.run_engine(platforms, cfg["scenarios"], caliber)
    views = pipeline.build_views(results)

    manifest = {"platforms": {}, "target_months": None}
    for p, r in results.items():
        d = out_dir / p
        d.mkdir(exist_ok=True)
        _dump_df(r["unified"], d / "unified.csv")
        _dump_df(r.get("structure"), d / "structure.csv")
        _dump_df(r["person"], d / "person.csv")
        _dump_df(r["field"], d / "field.csv")
        _dump_df(r["goods"], d / "goods.csv")
        (d / "baseline.json").write_text(
            json.dumps(r["baseline"], ensure_ascii=False, indent=2, default=str), encoding="utf-8")
        manifest["platforms"][p] = {"mode": r["mode"], "main_view": r["main_view"]}
    manifest["target_months"] = results[next(iter(results))]["target_months"] if results else []
    _dump_df(views["consolidated"], out_dir / "consolidated.csv")
    _dump_df(views["platform_annual"], out_dir / "platform_annual.csv")
    _dump_df(views["check"], out_dir / "check.csv")
    _dump_df(views["goods"], out_dir / "goods_view.csv")
    (out_dir / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"frozen → {out_dir}")


def _load(path: Path) -> pd.DataFrame | None:
    if path.with_suffix(".none").exists():
        return None
    if not path.exists():
        return None
    return pd.read_csv(path)


def compare(before: Path, after: Path) -> int:
    rows = []
    names = sorted({p.name for p in before.rglob("*.csv")} | {p.name for p in after.rglob("*.csv")})
    subdirs = sorted({str(p.parent.relative_to(before)) for p in before.rglob("*.csv")}
                     | {str(p.parent.relative_to(after)) for p in after.rglob("*.csv")})
    worst = 0
    for sub in subdirs:
        for name in names:
            b = _load(before / sub / name)
            a = _load(after / sub / name)
            if b is None and a is None:
                continue
            if (b is None) != (a is None):
                rows.append({"table": f"{sub}/{name}", "column": "*", "cells": -1,
                             "max_rel_delta": None, "note": "出现/消失"})
                continue
            if list(b.columns) != list(a.columns):
                rows.append({"table": f"{sub}/{name}", "column": "*columns*",
                             "cells": -1, "max_rel_delta": None,
                             "note": f"列集合变化: {list(b.columns)} → {list(a.columns)}"})
            common = [c for c in b.columns if c in a.columns]
            if len(b) != len(a):
                rows.append({"table": f"{sub}/{name}", "column": "*rows*", "cells": -1,
                             "max_rel_delta": None, "note": f"行数 {len(b)} → {len(a)}"})
            n = min(len(b), len(a))
            for c in common:
                cb, ca = b[c].iloc[:n], a[c].iloc[:n]
                if pd.api.types.is_numeric_dtype(cb) and pd.api.types.is_numeric_dtype(ca):
                    diff = (ca - cb).abs()
                    denom = cb.abs().clip(lower=1e-9)
                    rel = (diff / denom).fillna(0)
                    changed = int((diff > 1e-9).sum())
                    if changed:
                        rows.append({"table": f"{sub}/{name}", "column": c, "cells": changed,
                                     "max_rel_delta": float(rel.max()), "note": ""})
                        worst = max(worst, changed)
                else:
                    changed = int((cb.astype(str) != ca.astype(str)).sum())
                    if changed:
                        rows.append({"table": f"{sub}/{name}", "column": c, "cells": changed,
                                     "max_rel_delta": None, "note": "文本/类别变化"})
                        worst = max(worst, changed)
    rep = pd.DataFrame(rows)
    out = after / "_diff_report.csv"
    rep.to_csv(out, index=False)
    print(rep.to_string() if len(rep) else "完全一致：无数值/文本差异")
    print(f"\ndiff 报告 → {out}（变化单元格组 {len(rep)} 个）")
    return 0


if __name__ == "__main__":
    cmd = sys.argv[1]
    if cmd == "freeze":
        freeze(Path(sys.argv[2]))
    elif cmd == "compare":
        sys.exit(compare(Path(sys.argv[2]), Path(sys.argv[3])))
    else:
        sys.exit("用法: freeze <dir> | compare <before> <after>")
