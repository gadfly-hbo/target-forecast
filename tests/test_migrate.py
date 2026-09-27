"""workspace/ 数据布局迁移：plan/apply 纯函数测试（全部 tmp_path，不碰真实数据）。"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from workbench import migrate  # noqa: E402


def _mk(root: Path, rel: str, content: str = "x") -> Path:
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding="utf-8")
    return p


def test_empty_root_noop(tmp_path):
    plan = migrate.plan(tmp_path)
    assert plan.moves == [] and plan.conflicts == []
    rep = migrate.apply(tmp_path)
    assert rep.moved == 0 and rep.conflicts == []


def test_moves_all_sources(tmp_path):
    _mk(tmp_path, "data/orders/天猫.xlsx", "a")
    _mk(tmp_path, "data/metrics/私域.xlsx", "b")
    _mk(tmp_path, "coupon_data/scenarios/s1.json", "c")
    _mk(tmp_path, "output/coupon/r1.md", "d")
    _mk(tmp_path, "output/目标测算报告.xlsx", "e")
    _mk(tmp_path, "output/中间指标/月度指标_天猫.csv", "f")

    rep = migrate.apply(tmp_path)

    assert rep.moved == 6 and rep.conflicts == []
    assert (tmp_path / "workspace/forecast/orders/天猫.xlsx").read_text() == "a"
    assert (tmp_path / "workspace/forecast/metrics/私域.xlsx").read_text() == "b"
    assert (tmp_path / "workspace/coupon/scenarios/s1.json").read_text() == "c"
    # output/coupon 必须先于 output 处理，落到 coupon 侧而不是 forecast 侧
    assert (tmp_path / "workspace/coupon/output/r1.md").read_text() == "d"
    assert (tmp_path / "workspace/forecast/output/目标测算报告.xlsx").read_text() == "e"
    assert (tmp_path / "workspace/forecast/output/中间指标/月度指标_天猫.csv").read_text() == "f"
    # 源已清空移除
    assert not (tmp_path / "data").exists()
    assert not (tmp_path / "coupon_data").exists()
    assert not (tmp_path / "output").exists()


def test_conflict_skipped_and_reported(tmp_path):
    _mk(tmp_path, "data/orders/天猫.xlsx", "new-version")
    _mk(tmp_path, "workspace/forecast/orders/天猫.xlsx", "old-version")

    rep = migrate.apply(tmp_path)

    assert rep.moved == 0 and len(rep.conflicts) == 1
    src, dst = rep.conflicts[0]
    assert str(src).endswith("data/orders/天猫.xlsx") and str(dst).endswith("workspace/forecast/orders/天猫.xlsx")
    # 两侧文件都原样保留，不覆盖
    assert (tmp_path / "data/orders/天猫.xlsx").read_text() == "new-version"
    assert (tmp_path / "workspace/forecast/orders/天猫.xlsx").read_text() == "old-version"


def test_identical_target_deduped(tmp_path):
    _mk(tmp_path, "coupon_data/scenarios/s1.json", "same")
    _mk(tmp_path, "workspace/coupon/scenarios/s1.json", "same")

    rep = migrate.apply(tmp_path)

    assert rep.moved == 0 and rep.conflicts == [] and rep.dedup == 1
    assert not (tmp_path / "coupon_data").exists()  # 源作为重复被清除
    assert (tmp_path / "workspace/coupon/scenarios/s1.json").read_text() == "same"


def test_already_migrated_noop(tmp_path):
    _mk(tmp_path, "workspace/forecast/orders/天猫.xlsx", "a")
    rep = migrate.apply(tmp_path)
    assert rep.moved == 0 and rep.conflicts == []
    assert (tmp_path / "workspace/forecast/orders/天猫.xlsx").read_text() == "a"


def test_partial_conflict_keeps_nonempty_source_dirs(tmp_path):
    _mk(tmp_path, "data/orders/冲突.xlsx", "mine")
    _mk(tmp_path, "data/orders/正常.xlsx", "ok")
    _mk(tmp_path, "workspace/forecast/orders/冲突.xlsx", "theirs")

    rep = migrate.apply(tmp_path)

    assert rep.moved == 1 and len(rep.conflicts) == 1
    assert (tmp_path / "workspace/forecast/orders/正常.xlsx").read_text() == "ok"
    # 冲突源目录非空，保留
    assert (tmp_path / "data/orders/冲突.xlsx").read_text() == "mine"


def test_apply_idempotent(tmp_path):
    _mk(tmp_path, "data/orders/天猫.xlsx", "a")
    migrate.apply(tmp_path)
    rep2 = migrate.apply(tmp_path)
    assert rep2.moved == 0 and rep2.conflicts == [] and rep2.dedup == 0


def test_target_is_directory_reported_as_conflict(tmp_path):
    """目标位置是目录而非文件：按冲突跳过，不得 read_bytes 崩溃（review round 1）。"""
    _mk(tmp_path, "data/orders/天猫.xlsx", "file-content")
    d = tmp_path / "workspace/forecast/orders/天猫.xlsx"
    d.mkdir(parents=True)

    rep = migrate.apply(tmp_path)

    assert rep.moved == 0 and len(rep.conflicts) == 1
    assert (tmp_path / "data/orders/天猫.xlsx").read_text() == "file-content"
    assert d.is_dir()
