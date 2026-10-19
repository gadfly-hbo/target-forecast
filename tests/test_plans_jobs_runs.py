# -*- coding: utf-8 -*-
"""plans.service 计算与保存：job 状态机、保存去重、过期拦截、导出绑定与重试（A07/A09/A10/A11/A12）。"""

import io
import json
import sys
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from target_forecast import pipeline  # noqa: E402
from target_forecast.plans import service, store  # noqa: E402


@pytest.fixture()
def root(tmp_path):
    (tmp_path / "config.yaml").write_text(
        "caliber:\n  new_customer_window_days: 365\n  baseline_months: 12\n"
        "  tier_scope: platform\n  tier_pareto_pct: 0.78\n  tier_tail_pct: 0.2\n"
        "  goods_window_months: 12\n  new_product_days: 90\n"
        "target:\n  months: 12\nscenarios:\n"
        "  保守: {new_customers_growth: 0.03}\n  基准: {new_customers_growth: 0.10}\n"
        "  挑战: {new_customers_growth: 0.18}\n", encoding="utf-8")
    return tmp_path


def _agg_bytes(months=12):
    rows = []
    for i, m in enumerate(pd.period_range("2026-01", periods=months, freq="M")):
        rows.append({"月份": str(m), "新客数": 100 + i, "新客客单": 150.0,
                     "老客数": 200 + i, "老客复购频次": 1.5, "老客客单": 180.0})
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as xw:
        pd.DataFrame(rows).to_excel(xw, index=False)
    return buf.getvalue()


def _ready_plan(root):
    d = service.create_plan(root, "明年净 GMV 增长 20%", title="2027 目标")
    d = service.update_draft(root, d["plan_id"], {"goal": {"value": 12800000}},
                             base_revision=1, source="manual")
    up = service.stage_upload(root, "私域.xlsx", _agg_bytes())
    out = service.import_data(root, d["plan_id"], [
        {"upload_id": up["upload_id"], "platform": "私域", "mode": "B", "mapping": {}},
    ], base_revision=2)
    rev = out["draft"]["revision"]
    d = service.confirm(root, d["plan_id"], "data_coverage", base_revision=rev)
    d = service.confirm(root, d["plan_id"], "caliber", base_revision=rev)
    d = service.confirm(root, d["plan_id"], "assumptions", base_revision=rev)
    return d


def test_start_run_blocked_when_not_ready(root):
    d = service.create_plan(root, "目标")
    with pytest.raises(service.ValidationError) as exc:
        service.start_run(root, d["plan_id"], base_revision=1)
    assert any("确认" in i for i in exc.value.issues)


def test_run_save_export_happy_path(root):
    d = _ready_plan(root)
    job = service.start_run(root, d["plan_id"], base_revision=d["revision"], sync=True)
    assert job["status"] == "done"
    out = service.save_run(root, d["plan_id"], job["job_id"])
    assert out["duplicate"] is False
    run = out["run"]
    assert run["run_id"] == "RUN-001"
    assert run["version"] == "v1.0"
    assert run["engine_version"].startswith("forecast-engine-")
    # 三种格式导出绑定同一运行
    for fmt in ("xlsx", "csv", "json"):
        e = service.export_run(root, d["plan_id"], run["run_id"], fmt)
        assert Path(e["file"]).is_file()
        assert e["reused"] is False
        again = service.export_run(root, d["plan_id"], run["run_id"], fmt)
        assert again["reused"] is True  # 重试/重复导出不重新生成
    # JSON 快照携带运行身份
    snap = json.loads(Path(service.export_run(root, d["plan_id"], run["run_id"], "json")["file"])
                      .read_text(encoding="utf-8"))
    assert snap["run"]["run_id"] == "RUN-001"
    assert snap["run"]["version"] == "v1.0"


def test_save_dedup_same_content(root):
    d = _ready_plan(root)
    job = service.start_run(root, d["plan_id"], base_revision=d["revision"], sync=True)
    r1 = service.save_run(root, d["plan_id"], job["job_id"])
    r2 = service.save_run(root, d["plan_id"], job["job_id"])
    assert r2["duplicate"] is True
    assert r2["run"]["run_id"] == r1["run"]["run_id"]
    runs = service.list_runs(root, d["plan_id"])
    assert len(runs) == 1


def test_stale_save_rejected_old_run_untouched(root):
    d = _ready_plan(root)
    job = service.start_run(root, d["plan_id"], base_revision=d["revision"], sync=True)
    r1 = service.save_run(root, d["plan_id"], job["job_id"])
    # 工作稿修改 → 旧 job 结果过期，禁止保存
    service.update_draft(root, d["plan_id"],
                         {"scenarios": {"基准": {"params": {"new_customers_growth": 0.2}}}},
                         base_revision=d["revision"], source="manual")
    with pytest.raises(service.StaleError):
        service.save_run(root, d["plan_id"], job["job_id"])
    # 旧运行与其导出不受影响（A11）
    run = service.get_run(root, d["plan_id"], "RUN-001")
    assert run["content_key"] == r1["run"]["content_key"]
    e = service.export_run(root, d["plan_id"], "RUN-001", "json")
    assert Path(e["file"]).is_file()


def test_new_version_on_changed_content(root):
    d = _ready_plan(root)
    job1 = service.start_run(root, d["plan_id"], base_revision=d["revision"], sync=True)
    service.save_run(root, d["plan_id"], job1["job_id"])
    d = service.load_draft(root, d["plan_id"])
    service.update_draft(root, d["plan_id"], {"goal": {"value": 15000000}},
                         base_revision=d["revision"], source="manual")
    d = service.confirm(root, d["plan_id"], "assumptions",
                        base_revision=service.load_draft(root, d["plan_id"])["revision"])
    # 假设仍确认（goal 不在失效域）……assumptions 哈希未变 → 确认保持
    job2 = service.start_run(root, d["plan_id"], base_revision=d["revision"], sync=True)
    r2 = service.save_run(root, d["plan_id"], job2["job_id"])
    assert r2["run"]["run_id"] == "RUN-002"
    assert r2["run"]["version"] == "v2.0"


def test_failed_and_cancelled_jobs_leave_no_partial(root, monkeypatch):
    d = _ready_plan(root)

    def boom(*a, **k):
        raise RuntimeError("引擎故障演示")
    monkeypatch.setattr(pipeline, "run_engine", boom)
    job = service.start_run(root, d["plan_id"], base_revision=d["revision"], sync=True)
    assert job["status"] == "failed"
    assert "引擎故障演示" in job["error"]["message"]
    # 失败不产生半结果，也不让保存
    with pytest.raises(service.ValidationError):
        service.save_run(root, d["plan_id"], job["job_id"])
    assert service.list_runs(root, d["plan_id"]) == []
    monkeypatch.undo()

    from target_forecast.pipeline import JobCancelled
    def cancel(*a, **k):
        raise JobCancelled()
    monkeypatch.setattr(pipeline, "run_engine", cancel)
    job2 = service.start_run(root, d["plan_id"], base_revision=d["revision"], sync=True)
    assert job2["status"] == "cancelled"


def test_running_job_recovers_as_unknown(root):
    d = _ready_plan(root)
    jdir = store.v2_root(root) / "plans" / d["plan_id"] / "jobs" / "job-fake01"
    store.write_json(jdir / "job.json",
                     {"job_id": "job-fake01", "plan_id": d["plan_id"], "status": "running",
                      "content_key": "x", "created": "2026-10-19T00:00:00+08:00"})
    n = store.recover_jobs(root)
    assert n == 1
    assert store.read_json(jdir / "job.json")["status"] == "unknown"


def test_export_failure_marks_retryable_run_untouched(root, monkeypatch):
    d = _ready_plan(root)
    job = service.start_run(root, d["plan_id"], base_revision=d["revision"], sync=True)
    service.save_run(root, d["plan_id"], job["job_id"])
    from target_forecast import report
    def boom(*a, **k):
        raise OSError("磁盘写入失败演示")
    monkeypatch.setattr(report, "write_report", boom)
    with pytest.raises(OSError):
        service.export_run(root, d["plan_id"], "RUN-001", "xlsx")
    monkeypatch.undo()
    # 重试成功；运行仍在，未重新计算
    e = service.export_run(root, d["plan_id"], "RUN-001", "xlsx")
    assert Path(e["file"]).is_file()
    assert service.get_run(root, d["plan_id"], "RUN-001")["run_id"] == "RUN-001"
