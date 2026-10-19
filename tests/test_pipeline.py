# -*- coding: utf-8 -*-
"""pipeline 编排层测试：四件套形状 + 防第三份拷贝守卫 + 空输入分叉。

手写最小 xlsx（不跑 demo.generate）：一个模式 A 平台 + 一个带 UV 的模式 B 平台，
顺带钉住 main_view 人/场分叉（GRILL Q5）。
"""
import ast
import sys
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from target_forecast import pipeline, server  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture(scope="module")
def cfg():
    return server.load_cfg(ROOT)


@pytest.fixture(scope="module")
def inputs(tmp_path_factory):
    """最小固定输入：模式A（天猫，4 个月明细）+ 模式B（私域，4 个月聚合带 UV）。"""
    root = tmp_path_factory.mktemp("pipeline_in")
    orders = root / "workspace" / "forecast" / "orders"
    metrics = root / "workspace" / "forecast" / "metrics"
    orders.mkdir(parents=True)
    metrics.mkdir(parents=True)
    months = ["2026-06", "2026-07", "2026-08", "2026-09"]
    rows = []
    for mi, m in enumerate(months):
        for ui in range(10):
            rows.append({"日期": pd.Timestamp(f"{m}-15"), "订单号": f"{m}-{ui}",
                         "用户ID": f"u{mi * 10 + ui}", "商品ID": f"g{ui % 3}",
                         "实付金额": 100.0 + ui})
    pd.DataFrame(rows).to_excel(orders / "天猫.xlsx", index=False)
    pd.DataFrame({"月份": months, "新客数": [100] * 4, "新客客单": [200.0] * 4,
                  "老客数": [300] * 4, "老客复购频次": [1.5] * 4, "老客客单": [150.0] * 4,
                  "UV": [10000] * 4}).to_excel(metrics / "私域.xlsx", index=False)
    # ~$ 临时文件必须被排除
    pd.DataFrame(rows).to_excel(orders / "~$天猫.xlsx", index=False)
    return root


def test_scan_inputs(inputs):
    detail, agg = pipeline.scan_inputs(inputs)
    assert list(detail) == ["天猫"] and list(agg) == ["私域"]
    # 缺目录返回 {}
    empty = inputs / "nothing"
    assert pipeline.scan_inputs(empty) == ({}, {})


def test_ingest_platforms_shape(inputs, cfg):
    detail, agg = pipeline.scan_inputs(inputs)
    platforms = pipeline.ingest_platforms(detail, agg, cfg["caliber"])
    assert list(platforms) == ["天猫", "私域"]  # detail 在前，agg 在后
    assert platforms["天猫"]["mode"] == "A" and platforms["私域"]["mode"] == "B"
    assert platforms["私域"]["structure"] is None
    assert platforms["天猫"]["structure"] is not None
    assert len(platforms["天猫"]["unified"]) == 4 and len(platforms["私域"]["unified"]) == 4


def test_run_engine_keys_and_order(inputs, cfg):
    detail, agg = pipeline.scan_inputs(inputs)
    platforms = pipeline.ingest_platforms(detail, agg, cfg["caliber"])
    caliber = {**cfg["caliber"], "target_months": cfg["target"]["months"]}
    results = pipeline.run_engine(platforms, cfg["scenarios"], caliber)
    assert list(results) == ["天猫", "私域"]
    for p, r in results.items():
        for k in ("mode", "unified", "main_view", "baseline", "person", "field",
                  "goods", "target_months"):
            assert k in r, f"{p} 缺 {k}"
    assert results["天猫"]["main_view"] == "人"   # 模式A无 UV → 人视角
    assert results["私域"]["main_view"] == "场"   # 模式B带 UV → 场视角
    assert len(results["天猫"]["target_months"]) == 12


def test_build_views_five_keys(inputs, cfg):
    detail, agg = pipeline.scan_inputs(inputs)
    platforms = pipeline.ingest_platforms(detail, agg, cfg["caliber"])
    caliber = {**cfg["caliber"], "target_months": cfg["target"]["months"]}
    results = pipeline.run_engine(platforms, cfg["scenarios"], caliber)
    views = pipeline.build_views(results)
    assert set(views) == {"consolidated", "platform_annual", "check", "goods", "baselines"}
    assert len(views["consolidated"]) == len(cfg["scenarios"]) * cfg["target"]["months"]
    assert set(views["baselines"]) == {"天猫", "私域"}


def _defs_and_imports(path: Path):
    tree = ast.parse(path.read_text(encoding="utf-8"))
    defs, imports = set(), set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            defs.add(node.name)
        elif isinstance(node, ast.Import):
            imports.update(a.name for a in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                imports.add(node.module)
            imports.update(a.name for a in node.names)  # from X import pipeline / from . import pipeline
    return defs, imports


def test_no_third_copy_guard():
    """防第三份拷贝：main.py/server.py 不再私有定义 scan；pipeline 引用在 main 与 plans 层。"""
    main_defs, main_imports = _defs_and_imports(ROOT / "main.py")
    srv_defs, srv_imports = _defs_and_imports(ROOT / "target_forecast" / "server.py")
    svc_defs, svc_imports = _defs_and_imports(ROOT / "target_forecast" / "plans" / "service.py")
    assert "_collect_inputs" not in main_defs, "main.py 仍持有扫描拷贝"
    assert "_scan" not in srv_defs, "server.py 仍持有扫描拷贝"
    assert any(i.endswith("pipeline") for i in main_imports), "main.py 未 import pipeline"
    assert any(i.endswith("pipeline") for i in svc_imports), "plans/service.py 未 import pipeline"


def test_empty_input_fork_main_exits(tmp_path, monkeypatch, cfg):
    """空输入分叉：CLI 侧 sys.exit 报错（策略不进 scan_inputs）。"""
    import main
    monkeypatch.setattr(main, "ROOT", tmp_path)
    with pytest.raises(SystemExit):
        main.run_flow(cfg, demo_flag=False)


def test_empty_input_fork_server_no_silent_demo(tmp_path, cfg):
    """空输入分叉：服务端不再静默生成演示数据（G9）——v2 方案需显式导入或载入合成示例。"""
    from target_forecast.plans import service
    d = service.create_plan(tmp_path, "目标")
    issues = service.readiness(d)
    assert any("数据" in i for i in issues), "无数据时应被就绪检查拦下，而非静默造数"
