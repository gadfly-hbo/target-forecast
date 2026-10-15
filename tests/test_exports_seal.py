# -*- coding: utf-8 -*-
"""export_markdown 字节级封存（阶段5 门禁A2，先例：test_engine_fingerprint）。

三形态 sha256：full（stress+decision）/ bare（两者皆无）/ notop（无首选候选，
ranking_rows 为空——跳过首选/回本/收益/邻近四段）。run_id 在 dict 层归一为
固定串（唯一非确定性来源；created_at 不渲染）。重构 export_markdown 前后
逐 hash 必须相等。top 内部的 else 分支（breakeven/decomposition/neighbors
缺席）为已接受的残余，substring 冒烟覆盖。
"""
import hashlib
import os
import sys
import tempfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from coupon_tool.compare import compare  # noqa: E402
from coupon_tool.exports import export_markdown  # noqa: E402
from coupon_tool.storage import Store  # noqa: E402
from coupon_tool.stress import stress_test  # noqa: E402
from coupon_tool.synthetic import build_synthetic_spec  # noqa: E402

VARIANTS = {"低响应": {"behavior.conversion.k": 0.45}}
DECISION = {"choice": "满159减10", "reason": "测试", "confirmed_by": "t",
            "confirmed_at": "2026-10-15 12:00"}

EXPECTED = {
    "full": "d635f647ce946e2d181dabf11d6b0db071c55c32743dd048f1024a45a41e4eff",
    "bare": "f00bbb4204cd3199a54bed7c9b3e526a3914e15e160286066bf351403612bbc0",
    "notop": "410aa3b565ca90347ef2637d81e68f6e5f7d4e0793f2ddb5dcef184bb9fafc87",
}


def _render(form: str) -> str:
    with tempfile.TemporaryDirectory() as d:
        store = Store(d)
        spec = build_synthetic_spec()
        cmp_res = compare(spec)
        stress = stress_test(spec, VARIANTS) if form != "bare" else None
        run = store.record_run(spec, cmp_res, stress=stress)
        if form == "notop":
            run = {**run, "results": {**run["results"], "ranking_rows": []}}
        run["run_id"] = "run-SEALED"
        path = export_markdown(run, os.path.join(d, "x.md"),
                               DECISION if form == "full" else None)
        with open(path, "rb") as fh:
            return hashlib.sha256(fh.read()).hexdigest()


@pytest.mark.parametrize("form", list(EXPECTED))
def test_export_markdown_sealed(form):
    assert _render(form) == EXPECTED[form], f"{form} 段落拆分引入字节漂移"
