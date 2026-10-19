# -*- coding: utf-8 -*-
"""plans.service 提案周期：dry-run 提案、采纳、放弃、过期、幂等（A04/A05/A06）。"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from target_forecast.plans import service, store  # noqa: E402


@pytest.fixture()
def root(tmp_path):
    (tmp_path / "config.yaml").write_text(
        "caliber:\n  baseline_months: 12\ntarget:\n  months: 12\nscenarios:\n"
        "  基准: {new_customers_growth: 0.10}\n", encoding="utf-8")
    return tmp_path


def _plan(root):
    return service.create_plan(root, "目标")


def test_propose_change_returns_diff_and_persists(root):
    d = _plan(root)
    p = service.propose_change(root, d["plan_id"], "基准",
                               {"new_customers_growth": 0.2}, "获客计划上调", base_revision=1)
    assert p["status"] == "pending"
    assert p["base_revision"] == 1
    assert p["patches"] == [{"param": "new_customers_growth", "old": 0.10, "new": 0.2}]
    assert "assumptions" in p["impact"]["invalidates"]
    # 提案持久化，刷新后可见
    assert service.list_proposals(root, d["plan_id"])[0]["proposal_id"] == p["proposal_id"]


def test_propose_on_stale_revision_rejected(root):
    d = _plan(root)
    service.update_draft(root, d["plan_id"], {"title": "T"}, base_revision=1, source="manual")
    with pytest.raises(store.ConflictError):
        service.propose_change(root, d["plan_id"], "基准",
                               {"new_customers_growth": 0.2}, "r", base_revision=1)


def test_apply_proposal_same_entry_as_manual(root):
    d = _plan(root)
    p = service.propose_change(root, d["plan_id"], "基准",
                               {"new_customers_growth": 0.2}, "上调", base_revision=1)
    out = service.apply_proposal(root, d["plan_id"], p["proposal_id"], base_revision=1)
    draft = out["draft"]
    # 手动视图立即读到同一份修改（A04）
    assert draft["scenarios"]["基准"]["params"]["new_customers_growth"] == 0.2
    assert draft["revision"] == 2
    assert draft["changes"][0]["source"] == "ai"
    assert out["proposal"]["status"] == "applied"


def test_apply_proposal_idempotent_no_duplicate_effect(root):
    d = _plan(root)
    p = service.propose_change(root, d["plan_id"], "基准",
                               {"new_customers_growth": 0.2}, "上调", base_revision=1)
    service.apply_proposal(root, d["plan_id"], p["proposal_id"], base_revision=1)
    # 重复确认/重复采纳：不重复写、不产生第二次修订
    again = service.apply_proposal(root, d["plan_id"], p["proposal_id"], base_revision=1)
    assert again["proposal"]["status"] == "applied"
    assert again["draft"]["revision"] == 2


def test_draft_change_expires_pending_proposal(root):
    d = _plan(root)
    p = service.propose_change(root, d["plan_id"], "基准",
                               {"new_customers_growth": 0.2}, "上调", base_revision=1)
    # 提案生成后手动修改 → 旧提案过期，采纳被拒且零变更（A06）
    service.update_draft(root, d["plan_id"],
                         {"scenarios": {"基准": {"params": {"old_freq_growth": 0.05}}}},
                         base_revision=1, source="manual")
    with pytest.raises(service.StaleError):
        service.apply_proposal(root, d["plan_id"], p["proposal_id"], base_revision=2)
    assert service.load_draft(root, d["plan_id"])["scenarios"]["基准"]["params"]["new_customers_growth"] == 0.10
    assert service.list_proposals(root, d["plan_id"])[0]["status"] == "expired"


def test_discard_proposal_zero_change(root):
    d = _plan(root)
    p = service.propose_change(root, d["plan_id"], "基准",
                               {"new_customers_growth": 0.2}, "上调", base_revision=1)
    out = service.discard_proposal(root, d["plan_id"], p["proposal_id"])
    assert out["status"] == "discarded"
    d2 = service.load_draft(root, d["plan_id"])
    assert d2["revision"] == 1  # 零变更
    with pytest.raises(service.StaleError):
        service.apply_proposal(root, d["plan_id"], p["proposal_id"], base_revision=1)


def test_propose_validates_params(root):
    d = _plan(root)
    with pytest.raises(service.ValidationError):
        service.propose_change(root, d["plan_id"], "基准", {"bad_key": 0.2}, "x", base_revision=1)
    with pytest.raises(service.ValidationError):
        service.propose_change(root, d["plan_id"], "基准",
                               {"new_customers_growth": 99}, "x", base_revision=1)
