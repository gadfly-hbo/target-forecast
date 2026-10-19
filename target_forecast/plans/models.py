# -*- coding: utf-8 -*-
"""plans 域模型助手：内容键、NaN 清洗、ID 与时间。

领域对象的 JSON 形状见 service.py 各操作；本模块只放跨对象共用的纯函数。
内容键规范（G11）：canonical JSON（ensure_ascii=False, sort_keys, 紧凑分隔符，
NaN/Inf 一律归一为 None，浮点不取整）→ sha256 hex 前 16 位。
"""
from __future__ import annotations

import hashlib
import json
import math
import secrets
from datetime import datetime, timezone, timedelta

import numpy as np
import pandas as pd

_CST = timezone(timedelta(hours=8))


def now_iso() -> str:
    return datetime.now(_CST).isoformat(timespec="seconds")


def new_id(prefix: str) -> str:
    return f"{prefix}-{secrets.token_hex(3)}"


def short_id() -> str:
    return secrets.token_hex(3)


def today_stamp() -> str:
    return datetime.now(_CST).strftime("%Y%m%d")


def sanitize(obj):
    """递归清洗为 allow_nan=False 可序列化的纯 Python 对象：NaN/Inf→None，numpy→原生，Period→str。"""
    if isinstance(obj, dict):
        return {str(k): sanitize(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [sanitize(v) for v in obj]
    if isinstance(obj, pd.Period):
        return str(obj)
    if isinstance(obj, (pd.Timestamp, datetime)):
        return obj.isoformat()
    if isinstance(obj, (np.integer,)):
        return int(obj)
    if isinstance(obj, (np.floating, float)):
        f = float(obj)
        return f if math.isfinite(f) else None
    if isinstance(obj, (np.bool_,)):
        return bool(obj)
    if obj is pd.NA or obj is pd.NaT:
        return None
    return obj


def _canonical(obj) -> str:
    return json.dumps(sanitize(obj), ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"), allow_nan=False)


def content_key(obj) -> str:
    """对象内容的稳定身份：键序无关、NaN 视为 None。"""
    return hashlib.sha256(_canonical(obj).encode("utf-8")).hexdigest()[:16]


def frame_records(df: pd.DataFrame | None) -> list | None:
    """DataFrame → 清洗后的 records（None 透传）。"""
    if df is None:
        return None
    return sanitize(df.astype(object).where(df.notna(), None).to_dict(orient="records"))
