# -*- coding: utf-8 -*-
"""CLI v2 子命令：与 HTTP 共用 plans 层同一存储（G15）。"""
import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
PY = ROOT / ".venv" / "bin" / "python"

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


def cli(root, *args):
    return subprocess.run([str(PY), "main.py", *args, "--root", str(root)],
                          capture_output=True, text=True, cwd=ROOT, timeout=120)


def _agg_xlsx(path, months=12):
    import pandas as pd
    rows = [{"月份": str(m), "新客数": 100 + i, "新客客单": 150.0,
             "老客数": 200 + i, "老客复购频次": 1.5, "老客客单": 180.0}
            for i, m in enumerate(pd.period_range("2026-01", periods=months, freq="M"))]
    path.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(rows).to_excel(path, index=False, engine="openpyxl")


def test_cli_plan_lifecycle(root):
    r = cli(root, "plan-create", "--need", "明年净 GMV 增长 20%", "--title", "2027 目标")
    assert r.returncode == 0, r.stderr
    plan_id = r.stdout.split("已创建 ")[1].split("（")[0].strip()

    r = cli(root, "plans")
    assert plan_id in r.stdout

    # CLI 写不进数据：calc 应被就绪检查拦下（与 HTTP 同一 readiness）
    r = cli(root, "plan-calc", plan_id)
    assert r.returncode != 0
    assert "准备" in r.stderr or "数据" in r.stderr


def test_cli_calc_save_export_same_store(root):
    """CLI 创建的方案 → service 层可见；CLI calc/save/export 与 HTTP 读同一份存储。"""
    sys.path.insert(0, str(ROOT))
    from target_forecast.plans import service

    r = cli(root, "plan-create", "--need", "目标", "--title", "T")
    plan_id = r.stdout.split("已创建 ")[1].split("（")[0].strip()

    # 用 service 层导入数据（等价于 HTTP 导入），再走 CLI 计算/保存/导出
    xlsx = root / "workspace" / "forecast" / "metrics" / "私域.xlsx"
    _agg_xlsx(xlsx)
    d = service.load_draft(root, plan_id)
    service.update_draft(root, plan_id, {"goal": {"value": 12800000}},
                         base_revision=d["revision"], source="cli")
    d = service.load_draft(root, plan_id)
    service.import_data(root, plan_id, [
        {"workspace_path": "metrics/私域.xlsx", "platform": "私域", "mode": "B", "mapping": {}},
    ], base_revision=d["revision"], source="cli")
    d = service.load_draft(root, plan_id)
    for kind in ("data_coverage", "caliber", "assumptions"):
        service.confirm(root, plan_id, kind, base_revision=d["revision"])

    r = cli(root, "plan-calc", plan_id)
    assert r.returncode == 0 and "done" in r.stdout, r.stderr
    r = cli(root, "plan-save", plan_id)
    assert r.returncode == 0 and "RUN-001" in r.stdout, r.stderr
    r = cli(root, "plan-export", plan_id, "RUN-001", "--format", "json")
    assert r.returncode == 0
    out = [l for l in r.stdout.splitlines() if "已导出" in l or "复用" in l][0]
    payload = json.loads(Path(out.split(": ", 1)[1]).read_text(encoding="utf-8"))
    assert payload["run"]["run_id"] == "RUN-001"
    # HTTP 侧能看到同一份运行
    runs = service.list_runs(root, plan_id)
    assert runs[0]["run_id"] == "RUN-001"
