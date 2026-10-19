# -*- coding: utf-8 -*-
"""plans.store / plans.models：原子写、损坏隔离、内容键、NaN 清洗。"""

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from target_forecast.plans import models, store  # noqa: E402


def test_atomic_write_and_read_roundtrip(tmp_path):
    p = tmp_path / "a" / "draft.json"
    store.write_json(p, {"标题": "经营目标", "n": 1.5})
    assert json.loads(p.read_text(encoding="utf-8")) == {"标题": "经营目标", "n": 1.5}
    assert store.read_json(p) == {"标题": "经营目标", "n": 1.5}
    # 原子写不留临时文件
    assert list((tmp_path / "a").glob("*.tmp-*")) == []


def test_corrupt_file_quarantined_not_overwritten(tmp_path):
    p = tmp_path / "draft.json"
    p.write_text("{损坏的JSON", encoding="utf-8")
    with pytest.raises(store.CorruptError):
        store.read_json(p)
    quarantined = list(tmp_path.glob("draft.json.corrupt-*"))
    assert len(quarantined) == 1
    assert quarantined[0].read_text(encoding="utf-8") == "{损坏的JSON"  # 原内容保留
    assert not p.exists()  # 原位置清空，后续可重建


def test_read_missing_raises_not_found(tmp_path):
    with pytest.raises(store.NotFoundError):
        store.read_json(tmp_path / "none.json")


def test_content_key_stable_and_order_independent():
    a = {"x": 1, "y": {"b": 2, "a": [1, 2, 3]}}
    b = {"y": {"a": [1, 2, 3], "b": 2}, "x": 1}
    assert models.content_key(a) == models.content_key(b)
    assert models.content_key(a) != models.content_key({"x": 1, "y": {"b": 2, "a": [1, 2, 4]}})


def test_content_key_nan_safe():
    k1 = models.content_key({"v": float("nan")})
    k2 = models.content_key({"v": None})
    assert k1 == k2  # NaN 与 None 视为同一内容（G11）


def test_sanitize_numpy_and_nan():
    import numpy as np
    import pandas as pd
    out = models.sanitize({"a": np.float64(1.5), "b": np.int64(3), "c": np.nan,
                           "d": pd.Period("2027-01", "M"), "e": [np.float32("nan")]})
    assert out == {"a": 1.5, "b": 3, "c": None, "d": "2027-01", "e": [None]}
    # 必须能被 allow_nan=False 的 json 序列化（httpkit 约束）
    json.dumps(out, ensure_ascii=False, allow_nan=False)
