# -*- coding: utf-8 -*-
"""切片 6 兼容收尾：assistant_params 迁移、from-config 冻结、workspace 导入不动源目录。"""

import hashlib
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from target_forecast.plans import service, store  # noqa: E402

CONFIG = """\
caliber:
  new_customer_window_days: 365
  baseline_months: 12
  tier_scope: platform
  tier_pareto_pct: 0.78
  tier_tail_pct: 0.2
  goods_window_months: 12
  new_product_days: 90
target:
  months: 12
scenarios:
  保守: {new_customers_growth: 0.03}
  基准: {new_customers_growth: 0.10}
  挑战: {new_customers_growth: 0.18}
"""


@pytest.fixture()
def root(tmp_path):
    (tmp_path / "config.yaml").write_text(CONFIG, encoding="utf-8")
    return tmp_path


def _write_legacy_params(root, payload):
    f = root / "workspace" / "forecast" / "assistant_params.json"
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return f


def test_from_config_create_freezes_provenance(root):
    """从现有配置创建：来源记录 + 哈希冻结 + 参数取 config 值。"""
    d = service.create_plan(root, "（从现有配置创建）", source="import")
    assert d["provenance"]["source"] == "config.yaml"
    assert d["provenance"]["hash"] == service._config_hash(root)
    assert d["scenarios"]["基准"]["params"]["new_customers_growth"] == 0.10
    assert "从现有配置导入参数" in d["changes"][0]["description"]


def test_assistant_params_preview_diff_and_unknown_fields(root):
    """差异预览：同值不列；未知情景/字段只列明。"""
    d = service.create_plan(root, "目标")
    _write_legacy_params(root, {"scenarios": {
        "基准": {"new_customers_growth": 0.22, "老客客单增速": 0.05, "new_customers_growth_dup": 1},
        "不存在的档": {"new_customers_growth": 0.5},
        "挑战": {"new_customers_growth": 0.18},  # 与草稿同值 → 不产生差异项
    }})
    out = service.assistant_params_preview(root, d["plan_id"])
    assert out["exists"] is True
    items = {(i["scenario"], i["param"]): i for i in out["items"]}
    assert ("基准", "new_customers_growth") in items
    assert items[("基准", "new_customers_growth")]["old"] == 0.10
    assert items[("基准", "new_customers_growth")]["new"] == 0.22
    assert ("挑战", "new_customers_growth") not in items  # 同值
    unknown = "；".join(out["unknown_fields"])
    assert "不存在的档" in unknown and "老客客单增速" in unknown and "new_customers_growth_dup" in unknown


def test_assistant_params_merge_goes_through_update_draft(root):
    """确认并入：走唯一更新入口（修订+1、确认失效），未知字段不落盘。"""
    d = service.create_plan(root, "目标")
    pid = d["plan_id"]
    service.confirm(root, pid, "assumptions", base_revision=1)  # confirm 不增修订号
    assert service.load_draft(root, pid)["revision"] == 1
    _write_legacy_params(root, {"scenarios": {
        "基准": {"new_customers_growth": 0.22, "老客客单增速": 0.05}}})
    out = service.import_assistant_params(root, pid, base_revision=1)
    assert out["merged"] == 1  # 未知字段不计
    assert out["unknown_fields"] == ["基准.老客客单增速（未知字段）"]
    d2 = out["draft"]
    assert d2["revision"] == 2
    assert d2["scenarios"]["基准"]["params"]["new_customers_growth"] == 0.22
    assert "老客客单增速" not in d2["scenarios"]["基准"]["params"]
    # 其他情景未被覆盖
    assert d2["scenarios"]["挑战"]["params"]["new_customers_growth"] == 0.18
    # 假设确认随编辑失效（A07）
    assert service.confirmation_status(d2)["assumptions"]["confirmed"] is False
    # 修订冲突语义与手工编辑一致（有差异才走更新入口；同值并入是 no-op）
    _write_legacy_params(root, {"scenarios": {"基准": {"new_customers_growth": 0.33}}})
    with pytest.raises(store.ConflictError):
        service.import_assistant_params(root, pid, base_revision=1)


def test_assistant_params_absent_or_corrupt(root):
    d = service.create_plan(root, "目标")
    out = service.assistant_params_preview(root, d["plan_id"])
    assert out == {"exists": False, "items": [], "unknown_fields": []}
    with pytest.raises(service.ValidationError):
        service.import_assistant_params(root, d["plan_id"], base_revision=1)
    f = _write_legacy_params(root, {})
    f.write_text("{broken", encoding="utf-8")
    out = service.assistant_params_preview(root, d["plan_id"])
    assert out["exists"] and "无法解析" in out["error"]


def test_workspace_import_copies_sources_and_keeps_directory(root):
    """从工作区目录导入：源文件复制进快照、目录零改动（哈希前后一致）。"""
    import io

    import pandas as pd

    mdir = root / "workspace" / "forecast" / "metrics"
    mdir.mkdir(parents=True)
    rows = [{"月份": str(m), "新客数": 100, "新客客单": 150.0,
             "老客数": 200, "老客复购频次": 1.5, "老客客单": 180.0}
            for m in pd.period_range("2026-01", periods=12, freq="M")]
    xlsx = mdir / "私域.xlsx"
    pd.DataFrame(rows).to_excel(xlsx, index=False, engine="openpyxl")
    before = hashlib.sha256(xlsx.read_bytes()).hexdigest()
    names_before = sorted(p.name for p in (root / "workspace" / "forecast").rglob("*") if p.is_file())

    d = service.create_plan(root, "目标")
    service.import_data(root, d["plan_id"], [
        {"workspace_path": "metrics/私域.xlsx", "platform": "私域", "mode": "B", "mapping": {}},
    ], base_revision=1)

    # 输入目录零移动/零删除/零改动（v2 存储落在 workspace/forecast/v2/，属设计布局）
    assert hashlib.sha256(xlsx.read_bytes()).hexdigest() == before
    inputs_after = sorted(p.name for p in (root / "workspace" / "forecast").rglob("*")
                          if p.is_file() and "v2" not in p.parts)
    assert inputs_after == names_before
    # 快照带源文件副本
    snap_id = service.load_draft(root, d["plan_id"])["data"]["snapshot_id"]
    snap_dir = store.v2_root(root) / "snapshots" / snap_id
    copied = [p.name for p in (snap_dir / "source").rglob("*") if p.is_file()] \
        if (snap_dir / "source").is_dir() else []
    assert any("私域" in n for n in copied), f"源文件副本缺失：{list(snap_dir.iterdir())}"


def test_legacy_artifacts_listed_not_linked_to_runs(root):
    """旧 output/ 产物只读列出，标注口径不伪造版本链（无 run 身份字段）。"""
    out = root / "workspace" / "forecast" / "output"
    (out / "中间指标").mkdir(parents=True)
    (out / "目标测算报告.xlsx").write_bytes(b"PK\x03\x04fake")
    (out / "中间指标" / "月度指标_天猫.csv").write_text("month,gmv\n", encoding="utf-8-sig")
    arts = service.legacy_artifacts(root)
    names = {a["name"] for a in arts}
    assert names == {"目标测算报告.xlsx", "月度指标_天猫.csv"}
    assert all("run_id" not in a and "version" not in a for a in arts)
