# -*- coding: utf-8 -*-
"""plans.service 草稿周期：创建/修订/确认失效/持久化重开。"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from target_forecast.plans import service, store  # noqa: E402


@pytest.fixture()
def root(tmp_path):
    (tmp_path / "config.yaml").write_text(
        "caliber:\n  baseline_months: 12\ntarget:\n  months: 12\nscenarios:\n"
        "  保守: {new_customers_growth: 0.03}\n  基准: {new_customers_growth: 0.10}\n"
        "  挑战: {new_customers_growth: 0.18}\n", encoding="utf-8")
    return tmp_path


def test_create_plan_from_config_with_provenance(root):
    d = service.create_plan(root, "明年净 GMV 增长 20%", title="2027 目标")
    assert d["revision"] == 1
    assert d["need"] == "明年净 GMV 增长 20%"
    assert d["scenarios"]["基准"]["params"]["new_customers_growth"] == 0.10
    assert d["scenarios"]["基准"]["source_type"] == "import"
    assert d["provenance"]["source"] == "config.yaml"
    assert d["confirmations"] == {"data_coverage": None, "caliber": None, "assumptions": None}
    # 重开可读（持久化）
    again = service.load_draft(root, d["plan_id"])
    assert again == d


def test_create_plan_blank_without_config(root, monkeypatch):
    monkeypatch.setattr(service, "_load_config", lambda r: None)
    d = service.create_plan(root, "只做会员复购")
    assert d["scenarios"]["基准"]["params"]["new_customers_growth"] == 0.0
    assert d["provenance"] is None


def test_update_draft_bumps_revision_and_logs(root):
    d = service.create_plan(root, "目标")
    d2 = service.update_draft(root, d["plan_id"], {"title": "新标题"},
                              base_revision=1, source="manual")
    assert d2["revision"] == 2
    assert d2["title"] == "新标题"
    assert d2["changes"][0]["source"] == "manual"
    assert d2["changes"][0]["revision"] == 2


def test_update_draft_conflict_on_stale_revision(root):
    d = service.create_plan(root, "目标")
    service.update_draft(root, d["plan_id"], {"title": "A"}, base_revision=1, source="manual")
    with pytest.raises(store.ConflictError):
        service.update_draft(root, d["plan_id"], {"title": "B"}, base_revision=1, source="ai")


def test_update_draft_rejects_unknown_and_bad_params(root):
    d = service.create_plan(root, "目标")
    with pytest.raises(service.ValidationError):
        service.update_draft(root, d["plan_id"], {"scenarios": {"基准": {"params": {"不存在": 1}}}},
                             base_revision=1, source="manual")
    with pytest.raises(service.ValidationError):
        service.update_draft(root, d["plan_id"],
                             {"scenarios": {"基准": {"params": {"new_customers_growth": 99}}}},
                             base_revision=1, source="manual")


def test_confirm_and_invalidation_by_domain(root):
    d = service.create_plan(root, "目标")
    d = service.confirm(root, d["plan_id"], "assumptions", base_revision=1)
    status = service.confirmation_status(d)
    assert status["assumptions"]["confirmed"] is True
    # 确认不改内容、不增修订；标题变更不失效假设确认（不属于任何失效域）
    assert d["revision"] == 1
    d = service.update_draft(root, d["plan_id"], {"title": "改标题"}, base_revision=1, source="manual")
    assert service.confirmation_status(d)["assumptions"]["confirmed"] is True
    # 假设变更 → 假设确认失效；口径确认不受影响
    d = service.confirm(root, d["plan_id"], "caliber", base_revision=2)
    d = service.update_draft(root, d["plan_id"],
                             {"scenarios": {"基准": {"params": {"new_customers_growth": 0.2}}}},
                             base_revision=2, source="manual")
    st = service.confirmation_status(d)
    assert st["assumptions"]["confirmed"] is False and st["assumptions"]["stale"] is True
    assert st["caliber"]["confirmed"] is True


def test_readiness_issues(root):
    d = service.create_plan(root, "")  # 空描述
    issues = service.readiness(d)
    assert any("说明" in i for i in issues)
    assert any("目标金额" in i for i in issues)
    assert any("数据" in i for i in issues)
    assert any("确认" in i for i in issues)
