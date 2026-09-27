# -*- coding: utf-8 -*-
"""本地存储（提案 §10.3，G2/G11 决议：纯 JSON 文件快照）：场景、不可变运行记录、复盘与决策。

变更输入产生新运行，不覆盖旧结果；run_id = UTC 时间戳 + 配置内容摘要。
"""
from __future__ import annotations

import copy
import hashlib
import json
import os
from datetime import datetime, timezone

from .spec import ENGINE_VERSION, ScenarioSpec, load_spec, validate_spec
from .compare import ComparisonResult, compare


def _canonical(obj) -> str:
    return json.dumps(obj, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def _content_digest(obj) -> str:
    return hashlib.sha256(_canonical(obj).encode("utf-8")).hexdigest()[:12]


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class Store:
    """workspace/coupon/ 下的 JSON 文件存储。"""

    def __init__(self, root: str = "workspace/coupon"):
        self.root = root
        for sub in ("scenarios", "runs", "reviews", "decisions", "profiles"):
            os.makedirs(os.path.join(root, sub), exist_ok=True)

    # ---------- 场景 ----------

    def save_spec(self, spec: ScenarioSpec, name: str | None = None) -> str:
        name = name or spec.scenario_id
        path = os.path.join(self.root, "scenarios", f"{name}.json")
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(spec.to_dict(), fh, ensure_ascii=False, indent=2)
        return path

    def load_spec(self, name: str) -> ScenarioSpec:
        path = os.path.join(self.root, "scenarios", f"{name}.json")
        return load_spec(json.load(open(path, encoding="utf-8")))

    # ---------- 运行 ----------

    def record_run(self, spec: ScenarioSpec, comparison: ComparisonResult,
                   stress=None) -> dict:
        """封存一次运行：输入快照 + 完整配置 + 引擎版本 + 结果 + 校验。"""
        results = {
            "rows": comparison.rows,
            "ranking": [r["label"] for r in comparison.ranking],
            "ranking_rows": comparison.ranking,
            "pareto": [r["label"] for r in comparison.pareto],
            "conclusion": comparison.conclusion,
            "objective": comparison.objective,
        }
        scenario_dict = spec.to_dict()
        digest = _content_digest({"scenario": scenario_dict, "engine": ENGINE_VERSION,
                                  "candidates": scenario_dict.get("candidates", [])})
        ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%f")
        run = {
            "run_id": f"run-{ts}-{digest}",
            "created_at": _now_iso(),
            "engine_version": ENGINE_VERSION,
            "scenario_id": spec.scenario_id,
            "scenario": scenario_dict,
            "results": results,
            "stress": _stress_payload(stress) if stress else None,
            "validation": validate_spec(spec),
        }
        path = os.path.join(self.root, "runs", f"{run['run_id']}.json")
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(run, fh, ensure_ascii=False, indent=2)
        return run

    def load_run(self, run_id: str) -> dict:
        path = os.path.join(self.root, "runs", f"{run_id}.json")
        return json.load(open(path, encoding="utf-8"))

    def list_runs(self) -> list[dict]:
        runs_dir = os.path.join(self.root, "runs")
        out = []
        for fname in sorted(os.listdir(runs_dir), reverse=True):
            if not fname.endswith(".json"):
                continue
            run = json.load(open(os.path.join(runs_dir, fname), encoding="utf-8"))
            out.append({"run_id": run["run_id"], "created_at": run["created_at"],
                        "scenario_id": run["scenario_id"],
                        "conclusion": run["results"]["conclusion"]["type"]})
        return out

    def replay_run(self, run_id: str) -> dict:
        """只读重放：同输入同引擎版本重算（不落盘），结果必须与封存值逐位一致（M20）。"""
        run = self.load_run(run_id)
        spec = load_spec(copy.deepcopy(run["scenario"]))
        cmp_res = compare(spec)
        replayed = dict(run)
        replayed["results"] = {
            "rows": cmp_res.rows,
            "ranking": [r["label"] for r in cmp_res.ranking],
            "ranking_rows": cmp_res.ranking,
            "pareto": [r["label"] for r in cmp_res.pareto],
            "conclusion": cmp_res.conclusion,
            "objective": cmp_res.objective,
        }
        return replayed

    # ---------- 决策 / 复盘（文件占位，S8 填充语义） ----------

    def save_decision(self, run_id: str, decision: dict) -> str:
        path = os.path.join(self.root, "decisions", f"{run_id}.json")
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(decision, fh, ensure_ascii=False, indent=2)
        return path

    def save_review(self, run_id: str, review: dict) -> str:
        path = os.path.join(self.root, "reviews", f"{run_id}.json")
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(review, fh, ensure_ascii=False, indent=2)
        return path


def _stress_payload(stress) -> dict:
    return {
        "baseline": stress.baseline,
        "scenarios": stress.scenarios,
        "sensitive_params": stress.sensitive_params,
        "single_factor": stress.single_factor,
    }
