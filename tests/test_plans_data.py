# -*- coding: utf-8 -*-
"""plans.service 数据导入：上传两阶段、质量三级、快照身份与冻结口径（A02/A03）。"""

import io
import sys
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from target_forecast.plans import service, store  # noqa: E402


@pytest.fixture()
def root(tmp_path):
    (tmp_path / "config.yaml").write_text(
        "caliber:\n  new_customer_window_days: 365\n  baseline_months: 12\n"
        "  tier_scope: platform\n  tier_pareto_pct: 0.78\n  tier_tail_pct: 0.2\n"
        "  goods_window_months: 12\n  new_product_days: 90\n"
        "target:\n  months: 12\nscenarios:\n  基准: {new_customers_growth: 0.10}\n",
        encoding="utf-8")
    return tmp_path


def _xlsx_bytes(df: pd.DataFrame) -> bytes:
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as xw:
        df.to_excel(xw, index=False)
    return buf.getvalue()


def _agg_df(months=12, platform_note=""):
    rows = []
    for i, m in enumerate(pd.period_range("2026-01", periods=months, freq="M")):
        rows.append({"月份": str(m), "新客数": 100 + i, "新客客单": 150.0,
                     "老客数": 200 + i, "老客复购频次": 1.5, "老客客单": 180.0})
    return pd.DataFrame(rows)


def test_stage_upload_preview_and_mode_suggest(root):
    up = service.stage_upload(root, "私域.xlsx", _xlsx_bytes(_agg_df()))
    assert up["rows"] == 12
    assert "月份" in up["columns"]
    assert up["suggested_mode"] == "B"
    assert len(up["preview"]) == 5


def test_import_mode_b_happy_path_and_dedup(root):
    d = service.create_plan(root, "目标")
    up = service.stage_upload(root, "私域.xlsx", _xlsx_bytes(_agg_df()))
    out = service.import_data(root, d["plan_id"], [
        {"upload_id": up["upload_id"], "platform": "私域", "mode": "B", "mapping": {}},
    ], base_revision=1)
    draft, snap = out["draft"], out["snapshot"]
    assert draft["revision"] == 2
    assert draft["data"]["snapshot_id"] == snap["snapshot_id"]
    assert snap["platforms"]["私域"]["mode"] == "B"
    assert snap["caliber_frozen"]["new_customer_window_days"] == 365
    # 源文件字节副本入快照（不可变复查）
    assert snap["sources"][0]["name"] == "私域.xlsx"
    assert (store.v2_root(root) / "snapshots" / snap["snapshot_id"]
            / "source" / "私域.xlsx").is_file()
    # 同内容重复导入 → 同一个快照身份（去重）
    up2 = service.stage_upload(root, "私域.xlsx", _xlsx_bytes(_agg_df()))
    out2 = service.import_data(root, d["plan_id"], [
        {"upload_id": up2["upload_id"], "platform": "私域", "mode": "B", "mapping": {}},
    ], base_revision=2)
    assert out2["snapshot"]["snapshot_id"] == snap["snapshot_id"]


def test_import_duplicate_month_blocker_located(root):
    d = service.create_plan(root, "目标")
    df = _agg_df()
    df.loc[1, "月份"] = "2026-01"  # 重复月份
    up = service.stage_upload(root, "私域.xlsx", _xlsx_bytes(df))
    with pytest.raises(service.ValidationError) as exc:
        service.import_data(root, d["plan_id"], [
            {"upload_id": up["upload_id"], "platform": "私域", "mode": "B", "mapping": {}},
        ], base_revision=1)
    msg = str(exc.value)
    assert "私域" in msg and "2026-01" in msg and "第 2、3 行" in msg  # 定位到平台/月份/行


def test_import_detail_negative_amount_blocker_located(root):
    d = service.create_plan(root, "目标")
    df = pd.DataFrame([
        {"日期": "2026-01-05", "订单号": "O1", "用户ID": "U1", "商品ID": "S1", "实付金额": 100.0},
        {"日期": "2026-01-06", "订单号": "O2", "用户ID": "U2", "商品ID": "S2", "实付金额": -8.0},
    ])
    up = service.stage_upload(root, "天猫.xlsx", _xlsx_bytes(df))
    with pytest.raises(service.ValidationError) as exc:
        service.import_data(root, d["plan_id"], [
            {"upload_id": up["upload_id"], "platform": "天猫", "mode": "A", "mapping": {}},
        ], base_revision=1)
    msg = str(exc.value)
    assert "天猫" in msg and "实付金额" in msg and "第 3 行" in msg
    assert "净额" in msg  # G7：说明处置方式


def test_import_same_platform_twice_rejected(root):
    d = service.create_plan(root, "目标")
    up1 = service.stage_upload(root, "a.xlsx", _xlsx_bytes(_agg_df()))
    up2 = service.stage_upload(root, "b.xlsx", _xlsx_bytes(_agg_df()))
    with pytest.raises(service.ValidationError) as exc:
        service.import_data(root, d["plan_id"], [
            {"upload_id": up1["upload_id"], "platform": "私域", "mode": "B", "mapping": {}},
            {"upload_id": up2["upload_id"], "platform": "私域", "mode": "B", "mapping": {}},
        ], base_revision=1)
    assert "私域" in str(exc.value)


def test_import_with_field_mapping(root):
    d = service.create_plan(root, "目标")
    df = _agg_df().rename(columns={"新客数": "新客人数"})
    up = service.stage_upload(root, "私域.xlsx", _xlsx_bytes(df))
    out = service.import_data(root, d["plan_id"], [
        {"upload_id": up["upload_id"], "platform": "私域", "mode": "B",
         "mapping": {"新客数": "新客人数"}},
    ], base_revision=1)
    snap = out["snapshot"]
    assert snap["platforms"]["私域"]["mapping"] == {"新客数": "新客人数"}
    unified = snap["platforms"]["私域"]
    assert unified["months"] == 12


def test_import_short_history_is_confirmable_not_blocker(root):
    d = service.create_plan(root, "目标")
    up = service.stage_upload(root, "私域.xlsx", _xlsx_bytes(_agg_df(months=6)))
    out = service.import_data(root, d["plan_id"], [
        {"upload_id": up["upload_id"], "platform": "私域", "mode": "B", "mapping": {}},
    ], base_revision=1)
    kinds = [i["kind"] for i in out["snapshot"]["quality"]["confirmable"]]
    assert "short_history" in kinds
    assert out["snapshot"]["platforms"]["私域"]["months"] == 6


def test_workspace_sources_and_import(root):
    orders = root / "workspace" / "forecast" / "orders"
    metrics = root / "workspace" / "forecast" / "metrics"
    orders.mkdir(parents=True)
    metrics.mkdir(parents=True)
    _write = lambda p, df: pd.DataFrame(df).to_excel(p, index=False, engine="openpyxl")
    _write(metrics / "私域.xlsx", _agg_df())
    _write(metrics / "天猫.xlsx", _agg_df())
    detail = pd.DataFrame([{"日期": "2026-01-05", "订单号": "O1", "用户ID": "U1",
                            "商品ID": "S1", "实付金额": 100.0}])
    _write(orders / "天猫.xlsx", detail)
    src = service.workspace_sources(root)
    assert src["conflicts"] == ["天猫"]
    assert src["orders"] == ["orders/天猫.xlsx"] and "metrics/私域.xlsx" in src["metrics"]
    d = service.create_plan(root, "目标")
    out = service.import_data(root, d["plan_id"], [
        {"workspace_path": "orders/天猫.xlsx", "platform": "天猫", "mode": "A", "mapping": {}},
        {"workspace_path": "metrics/私域.xlsx", "platform": "私域", "mode": "B", "mapping": {}},
    ], base_revision=1)
    assert set(out["snapshot"]["platforms"]) == {"天猫", "私域"}
    # 路径逃逸拒绝
    with pytest.raises(service.ValidationError):
        service.import_data(root, d["plan_id"], [
            {"workspace_path": "../../etc/passwd", "platform": "X", "mode": "B", "mapping": {}},
        ], base_revision=2)


def test_import_new_data_new_snapshot_old_untouched(root):
    d = service.create_plan(root, "目标")
    up1 = service.stage_upload(root, "私域.xlsx", _xlsx_bytes(_agg_df()))
    out1 = service.import_data(root, d["plan_id"], [
        {"upload_id": up1["upload_id"], "platform": "私域", "mode": "B", "mapping": {}},
    ], base_revision=1)
    df2 = _agg_df()
    df2.loc[0, "新客数"] = 555
    up2 = service.stage_upload(root, "私域.xlsx", _xlsx_bytes(df2))
    out2 = service.import_data(root, d["plan_id"], [
        {"upload_id": up2["upload_id"], "platform": "私域", "mode": "B", "mapping": {}},
    ], base_revision=2)
    assert out2["snapshot"]["snapshot_id"] != out1["snapshot"]["snapshot_id"]
    # 旧快照原样保留
    old = store.read_json(store.v2_root(root) / "snapshots"
                          / out1["snapshot"]["snapshot_id"] / "snapshot.json")
    assert old["snapshot_id"] == out1["snapshot"]["snapshot_id"]
