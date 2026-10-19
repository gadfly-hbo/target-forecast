# -*- coding: utf-8 -*-
"""v2 HTTP API：上传→导入→确认→计算→保存→导出全链 + 错误分类 + 幂等。

经 workbench 壳 /t/forecast/ 前缀分发（测试用 serve_background 真实回环）。
"""
import json
import sys
import urllib.error
import urllib.request
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from workbench.registry import Registry  # noqa: E402
from workbench.server import serve_background  # noqa: E402
from target_forecast import plugin  # noqa: E402

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
def api(tmp_path):
    (tmp_path / "config.yaml").write_text(CONFIG, encoding="utf-8")
    reg = Registry()
    reg.register(plugin.build_tool(tmp_path))
    httpd, base = serve_background(tmp_path, registry=reg)
    yield ApiClient(base + "/t/forecast")
    httpd.shutdown()
    httpd.server_close()


class ApiClient:
    def __init__(self, base):
        self.base = base

    def _req(self, method, path, body=None, raw=None, headers=None):
        url = self.base + path
        data = raw if raw is not None else (json.dumps(body).encode("utf-8") if body is not None else None)
        req = urllib.request.Request(url, data=data, method=method)
        if raw is not None:
            req.add_header("Content-Type", "application/octet-stream")
        for k, v in (headers or {}).items():
            req.add_header(k, v)
        try:
            with urllib.request.urlopen(req) as resp:
                ctype = resp.headers.get("Content-Type", "")
                payload = resp.read()
                if "application/json" in ctype:
                    return resp.status, json.loads(payload.decode("utf-8"))
                return resp.status, payload
        except urllib.error.HTTPError as e:
            payload = e.read()
            try:
                return e.code, json.loads(payload.decode("utf-8"))
            except Exception:  # noqa: BLE001
                return e.code, payload

    def get(self, path):
        return self._req("GET", path)

    def post(self, path, body=None, **kw):
        return self._req("POST", path, body=body, **kw)


def _agg_xlsx(months=12):
    import io

    import pandas as pd
    rows = [{"月份": str(m), "新客数": 100 + i, "新客客单": 150.0,
             "老客数": 200 + i, "老客复购频次": 1.5, "老客客单": 180.0}
            for i, m in enumerate(pd.period_range("2026-01", periods=months, freq="M"))]
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as xw:
        pd.DataFrame(rows).to_excel(xw, index=False)
    return buf.getvalue()


def _ready_plan(api):
    st, plan = api.post("/api/v2/plans", {"need": "明年净 GMV 增长 20%", "title": "2027 目标"})
    assert st == 201
    pid = plan["draft"]["plan_id"]
    st, d = api.post(f"/api/v2/plans/{pid}/patch",
                     {"base_revision": 1, "patch": {"goal": {"value": 12800000}}})
    assert st == 200
    st, up = api.post("/api/v2/uploads", raw=_agg_xlsx(),
                      headers={"X-Filename": urllib.parse.quote("私域.xlsx")})
    assert st == 201
    st, out = api.post(f"/api/v2/plans/{pid}/import",
                       {"base_revision": 2, "items": [
                           {"upload_id": up["upload_id"], "platform": "私域",
                            "mode": "B", "mapping": {}}]})
    assert st == 200, out
    rev = out["draft"]["revision"]
    for kind in ("data_coverage", "caliber", "assumptions"):
        st, _ = api.post(f"/api/v2/plans/{pid}/confirm", {"kind": kind, "base_revision": rev})
        assert st == 200
    return pid, rev


def test_full_chain_http(api):
    pid, rev = _ready_plan(api)
    st, job = api.post(f"/api/v2/plans/{pid}/jobs", {"base_revision": rev})
    assert st == 202
    jid = job["job_id"]
    # 轮询直到完成
    for _ in range(200):
        st, j = api.get(f"/api/v2/plans/{pid}/jobs/{jid}")
        if j["status"] != "running":
            break
    assert j["status"] == "done"
    assert j["result"]["views"]["consolidated"]
    st, saved = api.post(f"/api/v2/plans/{pid}/runs", {"job_id": jid})
    assert st == 201
    assert saved["run"]["run_id"] == "RUN-001"
    # 重复保存去重（A10）
    st, dup = api.post(f"/api/v2/plans/{pid}/runs", {"job_id": jid})
    assert st == 200 and dup["duplicate"] is True
    # 导出绑定运行（A12）
    st, meta = api.get(f"/api/v2/plans/{pid}/runs/RUN-001/export/json")
    assert st == 200 and meta["run"]["run_id"] == "RUN-001"
    # 方案详情可追溯到同一运行
    st, detail = api.get(f"/api/v2/plans/{pid}")
    assert detail["runs"][0]["run_id"] == "RUN-001"
    assert detail["confirmation_status"]["assumptions"]["confirmed"] is True


def test_patch_conflict_409(api):
    st, plan = api.post("/api/v2/plans", {"need": "目标"})
    pid = plan["draft"]["plan_id"]
    api.post(f"/api/v2/plans/{pid}/patch", {"base_revision": 1, "patch": {"title": "A"}})
    st, out = api.post(f"/api/v2/plans/{pid}/patch", {"base_revision": 1, "patch": {"title": "B"}})
    assert st == 409
    assert "error" in out


def test_calc_blocked_422_when_not_ready(api):
    st, plan = api.post("/api/v2/plans", {"need": "目标"})
    st, out = api.post(f"/api/v2/plans/{plan['draft']['plan_id']}/jobs", {"base_revision": 1})
    assert st == 422
    assert out["issues"]


def test_stale_save_409(api):
    pid, rev = _ready_plan(api)
    st, job = api.post(f"/api/v2/plans/{pid}/jobs", {"base_revision": rev})
    jid = job["job_id"]
    for _ in range(200):
        st, j = api.get(f"/api/v2/plans/{pid}/jobs/{jid}")
        if j["status"] != "running":
            break
    # 计算完成后修改工作稿 → 保存被拒（A07）
    st, d = api.get(f"/api/v2/plans/{pid}")
    st, out = api.post(f"/api/v2/plans/{pid}/patch",
                       {"base_revision": d["draft"]["revision"],
                        "patch": {"scenarios": {"基准": {"params": {"new_customers_growth": 0.2}}}}})
    assert st == 200
    st, out = api.post(f"/api/v2/plans/{pid}/runs", {"job_id": jid})
    assert st == 409


def test_upload_rejects_non_xlsx(api):
    st, out = api.post("/api/v2/uploads", raw=b"not excel", headers={"X-Filename": "a.csv"})
    assert st == 422


def test_unknown_ids_404(api):
    st, _ = api.get("/api/v2/plans/plan-20990101-000000")
    assert st == 404


def test_proposal_flow_http(api):
    pid, rev = _ready_plan(api)
    st, p = api.post(f"/api/v2/plans/{pid}/proposals",
                     {"scenario": "基准", "patches": {"new_customers_growth": 0.22},
                      "rationale": "获客加码", "base_revision": rev})
    assert st == 201
    assert p["status"] == "pending"
    st, out = api.post(f"/api/v2/plans/{pid}/proposals/{p['proposal_id']}/apply",
                       {"base_revision": rev})
    assert st == 200
    assert out["draft"]["scenarios"]["基准"]["params"]["new_customers_growth"] == 0.22
    # 确认失效（A07）
    assert out["confirmation_status"]["assumptions"]["confirmed"] is False
    # 重复采纳幂等
    st, again = api.post(f"/api/v2/plans/{pid}/proposals/{p['proposal_id']}/apply",
                         {"base_revision": rev})
    assert st == 200 and again["draft"]["revision"] == out["draft"]["revision"]


def test_state_endpoint(api):
    st, s = api.get("/api/v2/state")
    assert st == 200
    assert s["engine_version"].startswith("forecast-engine-")
    assert s["plans"] == []
