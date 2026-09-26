# -*- coding: utf-8 -*-
"""S6 验收：CLI 端到端——demo 一条命令复现黄金场景并产出三格式导出；console 重跑已保存场景。"""
import json
import os

import pytest

from coupon_tool import cli
from coupon_tool.storage import Store


def _run_cli(tmp_path, *args):
    data_dir = str(tmp_path / "coupon_data")
    out_dir = str(tmp_path / "out")
    cli.main(["demo", "--data-dir", data_dir, "--out", out_dir, *args])
    return data_dir, out_dir


def test_demo_end_to_end_matches_golden(tmp_path):
    data_dir, out_dir = _run_cli(tmp_path)
    files = os.listdir(out_dir)
    assert any(f.endswith("_决策摘要.md") for f in files)
    assert any(f.endswith("_候选表.csv") for f in files)
    assert any(f.endswith("_运行记录.json") for f in files)
    run_files = [f for f in files if f.endswith("_运行记录.json")]
    payload = json.load(open(os.path.join(out_dir, run_files[0]), encoding="utf-8"))
    # 关键数值与黄金一致（满159减10：ΔΠ=+8,769.87 元）
    row = next(r for r in payload["results"]["rows"] if r["label"] == "满159减10")
    assert abs(row["metrics"]["incremental_contribution_cents"] - 876_987) <= 100
    assert payload["scenario"]["evidence_status"] == "synthetic_assumptions"
    # 敏感性与结论入档
    assert payload["stress"]["scenarios"]
    assert payload["results"]["conclusion"]["type"] in ("needs_validation", "feasible")
    # 运行已封存且场景已保存
    assert len(Store(data_dir).list_runs()) == 1


def test_demo_deterministic_rerun(tmp_path):  # M20 CLI 面
    data_dir, out_dir = _run_cli(tmp_path)
    _ = cli.main  # noqa
    first = Store(data_dir).list_runs()[0]["run_id"]
    payload1 = Store(data_dir).load_run(first)
    cli.main(["demo", "--data-dir", data_dir, "--out", str(tmp_path / "out2")])
    runs = Store(data_dir).list_runs()
    assert len(runs) == 2                                   # 新运行，不覆盖
    payload2 = Store(data_dir).load_run(next(r["run_id"] for r in runs if r["run_id"] != first))
    m1 = {r["label"]: r["metrics"] for r in payload1["results"]["rows"]}
    m2 = {r["label"]: r["metrics"] for r in payload2["results"]["rows"]}
    assert m1 == m2                                          # 同输入同结果


def test_console_runs_saved_scenario(tmp_path):
    data_dir, _ = _run_cli(tmp_path)                        # demo 保存了场景
    out2 = str(tmp_path / "console_out")
    cli.main(["console", "--scenario", "coupon-demo-001", "--data-dir", data_dir, "--out", out2])
    assert any(f.endswith("_运行记录.json") for f in os.listdir(out2))
    assert len(Store(data_dir).list_runs()) == 2


def test_templates_command(tmp_path):
    tpl_dir = str(tmp_path / "tpl")
    cli.main(["templates", "--out", tpl_dir])
    files = os.listdir(tpl_dir)
    assert any("分桶" in f for f in files) and any("明细" in f for f in files)
