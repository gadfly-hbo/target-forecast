# -*- coding: utf-8 -*-
"""S5 验收：运行封存、不可变历史、重跑一致（M20）、退货单次计损（M17）、三格式导出。"""
import csv
import json
import os

import pytest

from coupon_tool import ENGINE_VERSION, build_synthetic_spec, compare, load_spec, simulate, stress_test
from coupon_tool.exports import export_all
from coupon_tool.storage import Store


@pytest.fixture()
def store(tmp_path):
    return Store(str(tmp_path / "coupon_data"))


def test_run_roundtrip_and_deterministic_replay(store):  # M20
    spec = build_synthetic_spec()
    cmp_res = compare(spec)
    run = store.record_run(spec, cmp_res)
    assert run["engine_version"] == ENGINE_VERSION
    loaded = store.load_run(run["run_id"])
    assert loaded["run_id"] == run["run_id"]
    assert run["validation"]["errors"] == []                  # 封存真实校验结果
    runs_before = len(store.list_runs())
    replayed = store.replay_run(run["run_id"])                # 只读重放，不落盘
    assert len(store.list_runs()) == runs_before
    for orig, new in zip(run["results"]["rows"], replayed["results"]["rows"]):
        if orig["metrics"]:
            assert orig["metrics"] == new["metrics"]          # 逐位一致
    assert run["results"]["conclusion"] == replayed["results"]["conclusion"]


def test_controlled_loss_requires_max_loss():
    from coupon_tool import validate_spec
    data = build_synthetic_spec().to_dict()
    data["constraints"]["allow_controlled_loss"] = True
    result = validate_spec(load_spec(data, strict=False))
    assert any("最大损失" in e for e in result["errors"])


def test_changed_input_creates_new_run_without_overwrite(store):
    spec = build_synthetic_spec()
    run1 = store.record_run(spec, compare(spec))
    data = spec.to_dict()
    data["constraints"]["merchant_coupon_budget_cents"] = 1_000_000
    run2 = store.record_run(load_spec(data), compare(load_spec(data)))
    assert run1["run_id"] != run2["run_id"]
    assert len(store.list_runs()) == 2
    again = store.load_run(run1["run_id"])
    assert again["scenario"]["constraints"]["merchant_coupon_budget_cents"] is None  # 原运行未被覆盖


def test_m17_return_adjustment_counted_exactly_once():
    base = build_synthetic_spec()
    data = base.to_dict()
    data["cost"]["return_adj_cents"] = 50.0
    spec = load_spec(data)
    cand = {"enabled": True, "threshold_cents": 15900, "face_value_cents": 500}
    r_adj = simulate(spec, cand)
    r_zero = simulate(base, cand)
    total_orders = sum(row["expected_orders"] for row in r_adj.ledger if row["group"] != "loss")
    diff = r_zero.metrics["total_contribution_cents"] - r_adj.metrics["total_contribution_cents"]
    assert diff == pytest.approx(50.0 * total_orders, abs=1.0)   # 只扣一次
    # 账本行内也只出现一次：Σ 行退货调整 == 50 × Σ 行订单
    assert sum(row["return_adj_cents"] for row in r_adj.ledger) == pytest.approx(
        50.0 * total_orders, abs=1.0)


def test_export_all_three_formats(store, tmp_path):
    spec = build_synthetic_spec()
    cmp_res = compare(spec)
    stress = stress_test(spec, {"低响应": {"behavior.conversion.k": 0.45}})
    run = store.record_run(spec, cmp_res, stress=stress)
    out = export_all(run, out_dir=str(tmp_path / "out"))
    assert set(out) == {"markdown", "csv_candidates", "csv_ledger", "json"}

    md = open(out["markdown"], encoding="utf-8").read()
    for token in (run["run_id"], "证据状态", "回本条件", "最敏感假设", "邻近候选", "已知限制"):
        assert token in md
    assert "满159减10" in md

    with open(out["csv_candidates"], newline="", encoding="utf-8-sig") as fh:
        rows = list(csv.DictReader(fh))
    header = rows[0].keys()
    for col in ("券组合", "最终转化率", "净转化变化", "毛新增订单", "自然核销量", "加购核销量",
                "商家补贴分", "总贡献分", "增量贡献分", "净增量ROI", "约束状态"):
        assert col in header
    assert len(rows) == len(run["results"]["rows"])

    with open(out["csv_ledger"], newline="", encoding="utf-8-sig") as fh:
        ledger_rows = list(csv.DictReader(fh))
    assert len(ledger_rows) >= 10                       # 每候选多分支
    payload = json.load(open(out["json"], encoding="utf-8"))
    assert payload["run_id"] == run["run_id"]
    assert payload["engine_version"] == ENGINE_VERSION
    assert payload["results"]["rows"][0]["metrics"]                     # 完整指标随行
    assert "低响应" in json.dumps(payload["stress"]["scenarios"], ensure_ascii=False)       # 敏感性入档
