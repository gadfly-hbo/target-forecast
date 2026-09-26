# -*- coding: utf-8 -*-
"""S4 验收：数据导入与质量检查（提案 §3.3–3.5、M15/M16、模板往返、缺 N 降级）。"""
import csv
import os

import pytest

from coupon_tool import load_spec, simulate, validate_spec
from coupon_tool.ingest import (DataSnapshot, check_cost_overlap, check_reach_overlap,
                                generate_templates, import_buckets, import_orders,
                                read_csv_file, read_xlsx_file, snapshot_to_baseline)


def _write_csv(tmp_path, name, header, rows):
    path = tmp_path / name
    with open(path, "w", newline="", encoding="utf-8-sig") as fh:
        writer = csv.writer(fh)
        writer.writerow(header)
        writer.writerows(rows)
    return str(path)


BUCKET_HEADER = ["bucket_min_cents", "bucket_max_cents", "avg_amount_cents", "orders", "avg_margin_rate"]


def test_csv_bucket_import_normalizes_weights(tmp_path):
    path = _write_csv(tmp_path, "buckets.csv", BUCKET_HEADER, [
        [6000, 8999, 7500, 200, 0.30],
        [9000, 12999, 11000, 300, 0.30],
        [13000, 19999, 16000, 500, 0.28],
    ])
    snap = import_buckets(read_csv_file(path), meta={"source": "csv", "snapshot_id": "t1"})
    assert snap.issues == []
    total = sum(b.weight for b in snap.baskets)
    assert total == pytest.approx(1.0)
    assert [b.amount_cents for b in snap.baskets] == [7500, 11000, 16000]


def test_bucket_weights_must_sum_to_one_in_weight_mode(tmp_path):
    path = _write_csv(tmp_path, "w.csv", ["bucket_min_cents", "bucket_max_cents",
                                          "avg_amount_cents", "weight"], [
        [None, None, 6000, 0.5], [None, None, 9000, 0.6],
    ])
    snap = import_buckets(read_csv_file(path), meta={"snapshot_id": "t2"})
    assert any(i["level"] == "error" and "权重" in i["message"] for i in snap.issues)


def test_orders_import_dup_and_nonpositive_blocked(tmp_path):
    header = ["order_id", "amount_cents", "margin_cents", "refunded"]
    path = _write_csv(tmp_path, "orders.csv", header, [
        ["o1", 9900, 3000, 0],
        ["o1", 9900, 3000, 0],          # 重复订单
        ["o2", 0, 0, 0],                # A ≤ 0
        ["o3", 12800, 3900, 1],         # 退款单，meta 未说明退款处理
    ])
    snap = import_orders(read_csv_file(path), meta={"snapshot_id": "t3"})
    codes = {(i["level"], i["code"]) for i in snap.issues}
    assert ("error", "duplicate_order") in codes
    assert ("error", "nonpositive_amount") in codes
    assert ("warning", "refund_unspecified") in codes


def test_non_integer_cents_and_currency_suspect(tmp_path):
    path = _write_csv(tmp_path, "bad.csv", BUCKET_HEADER, [
        [None, None, 99.5, 10, 0.3],     # 非整数分
        [None, None, 45, 10, 0.3],       # 均值 < 1 元，疑似填了“元”
    ])
    snap = import_buckets(read_csv_file(path), meta={"snapshot_id": "t4"})
    codes = {i["code"] for i in snap.issues}
    assert "non_integer_cents" in codes
    assert "currency_unit_suspect" in codes


def test_m15_threshold_straddling_bucket_yields_limitation(tmp_path):
    path = _write_csv(tmp_path, "straddle.csv", BUCKET_HEADER, [
        [10000, 15000, 12000, 400, 0.30],   # 桶横跨 129 元门槛
        [15001, 20000, 18000, 600, 0.30],
    ])
    snap = import_buckets(read_csv_file(path), meta={"snapshot_id": "t5"})
    assert snap.issues == []
    from coupon_tool.synthetic import synthetic_spec_dict
    data = synthetic_spec_dict()
    data["baseline"].update(snapshot_to_baseline(snap, visitors=100000, conversion_rate=0.08))
    spec = load_spec(data)
    res = simulate(spec, {"enabled": True, "threshold_cents": 12900, "face_value_cents": 500})
    assert any("穿过粗桶" in lim for lim in res.limitations)
    from coupon_tool import compare
    row = next(r for r in compare(load_spec(data)).rows if r["label"] != "无券"
               and r["candidate"]["threshold_cents"] == 12900)
    assert any("穿过粗桶" in w for w in row["warnings"])   # G3 决议：行级 validation 警示


def test_m16_margin_includes_fulfillment_plus_fee_blocked():
    from coupon_tool.synthetic import synthetic_spec_dict
    data = synthetic_spec_dict()
    data["cost"]["margin_includes_fulfillment"] = True
    data["cost"]["fixed_fee_cents"] = 200
    with pytest.raises(Exception) as ei:
        load_spec(data)
    assert "重复扣减" in str(ei.value)
    assert check_cost_overlap(margin_includes_fulfillment=True,
                              fixed_fee_cents=200, fee_rate=0.0)


def test_reach_overlap_warning():
    assert check_reach_overlap(audience_already_reached=True, reach_base=0.6)
    assert not check_reach_overlap(audience_already_reached=False, reach_base=0.6)
    assert not check_reach_overlap(audience_already_reached=True, reach_base=1.0)


def test_missing_n_degrades_to_per_unit():
    from coupon_tool.synthetic import synthetic_spec_dict
    data = synthetic_spec_dict()
    data["baseline"]["visitors"] = None
    spec = load_spec(data)
    assert any("每观察单位" in w for w in validate_spec(spec)["warnings"])
    m = simulate(spec, {"enabled": True, "threshold_cents": 15900,
                        "face_value_cents": 500}).metrics
    assert 0 < m["orders"] < 1.5            # 单位口径：每观察单位期望订单
    assert any("每观察单位" in lim for lim in
               simulate(spec, {"enabled": True, "threshold_cents": 15900,
                               "face_value_cents": 500}).limitations)


def test_xlsx_template_roundtrip(tmp_path):
    out = tmp_path / "tpl"
    out.mkdir()
    generate_templates(str(out))
    files = sorted(os.listdir(out))
    assert any("分桶" in f for f in files) and any("明细" in f for f in files)
    bucket_file = next(f for f in files if "分桶" in f)
    headers, rows = read_xlsx_file(os.path.join(out, bucket_file), sheet="分桶数据")
    assert "avg_amount_cents" in headers
    assert rows[0]["avg_amount_cents"] == 12000    # 示例行首桶均值
    snap = import_buckets(rows, meta={"snapshot_id": "tpl"})
    assert sum(b.weight for b in snap.baskets) == pytest.approx(1.0)
