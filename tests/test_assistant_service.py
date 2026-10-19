"""P3 切片 2：assistant service 编排测试（Echo 回放后端 + FakeHttp 执行层）。"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from workbench import build_default_registry  # noqa: E402
from workbench.assistant.backend import BackendUnavailable, EchoBackend  # noqa: E402
from workbench.assistant.fixtures import FIXTURES  # noqa: E402
from workbench.assistant.service import AssistantService  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent

ROI_CALC_RESULT = {
    "scenarios": {
        "基准": {"plans": [{"name": f"计划{i}", "net": 1000.0 * i} for i in range(1, 5)],
                 "totals": {"spend": 145000, "gmv": 643807.59, "net": 50807.59}}
    }
}
FORECAST_STATE = {"engine_version": "forecast-engine-1.1",
                  "plans": [{"plan_id": "plan-1"}, {"plan_id": "plan-2"}],
                  "runs": [{"run_id": "RUN-001"}]}
FORECAST_PLAN_DETAIL = {
    "draft": {"plan_id": "plan-1", "revision": 3,
              "goal": {"value": 12800000, "unit": "元"}},
    "confirmation_status": {"data_coverage": {"confirmed": True, "stale": False},
                            "caliber": {"confirmed": True, "stale": False},
                            "assumptions": {"confirmed": False, "stale": False}},
    "snapshot": {"synthetic": True,
                 "quality": {"blockers": [], "confirmable": [{"detail": "私域缺 2 个月"}], "warnings": []}},
    "runs": [{"run_id": "RUN-001", "selected": "基准", "saved": "2026-10-19T10:00:00+08:00",
              "engine_version": "forecast-engine-1.1",
              "summary": {"selected_total": 13815000.0}},
             {"run_id": "RUN-002", "selected": "挑战", "saved": "2026-10-19T11:00:00+08:00",
              "engine_version": "forecast-engine-1.1",
              "summary": {"selected_total": 14761000.0}}],
}
FORECAST_PROPOSAL = {"proposal_id": "prop-1", "scenario": "基准", "status": "pending",
                     "patches": [{"param": "new_customers_growth", "old": 0.1, "new": 0.2}]}
FORECAST_APPLY = {"draft": {"plan_id": "plan-1", "revision": 4},
                  "proposal": {"proposal_id": "prop-1", "scenario": "基准", "status": "applied"}}


ROI_STATE = {"plans": [{"name": f"计划{i}"} for i in range(1, 5)],
             "scenarios": {"基准": {"cvr_growth": 0.0, "aov_growth": 0.0}}}


class FakeHttp:
    def __init__(self):
        self.calls = []

    def __call__(self, method, path, body=None):
        self.calls.append((method, path, body))
        if path == "/t/roi/api/calc":
            return ROI_CALC_RESULT
        if path == "/t/roi/api/state":
            return ROI_STATE
        if path == "/t/forecast/api/v2/state":
            return FORECAST_STATE
        if path == "/t/forecast/api/v2/plans/plan-1":
            return FORECAST_PLAN_DETAIL
        if path == "/t/forecast/api/v2/plans/plan-1/proposals":
            return FORECAST_PROPOSAL
        if path == "/t/forecast/api/v2/plans/plan-1/proposals/prop-1/apply":
            return FORECAST_APPLY
        if path == "/t/forecast/api/v2/plans/plan-1/runs/RUN-001":
            return {"run": FORECAST_PLAN_DETAIL["runs"][0], "result": {}}
        if path == "/t/forecast/api/v2/plans/plan-1/runs/RUN-002":
            return {"run": FORECAST_PLAN_DETAIL["runs"][1], "result": {}}
        if path == "/t/roi/api/assistant_params":
            return {"saved": True}
        raise AssertionError(f"未预期的调用: {method} {path}")


def _service():
    http = FakeHttp()
    backend = EchoBackend(FIXTURES)
    svc = AssistantService(build_default_registry(ROOT), backend, http)
    return svc, http, backend


def test_read_intent_tool_result_in_reply():
    svc, http, _ = _service()
    res = svc.chat({"message": "基准情景净贡献是多少", "history": [], "tool_id": "roi"})
    assert res["reply"] == "基准情景的合计净贡献为 50807.59 元（4 个计划）。"
    assert res["pending_confirmation"] is None
    calc_calls = [b for m, p, b in http.calls if m == "POST" and p == "/t/roi/api/calc"]
    assert len(calc_calls) == 1
    assert calc_calls[0]["scenarios"] == {"基准": {}}
    assert len(calc_calls[0]["plans"]) == 4  # 省略 plans 时由演示集补全


def test_write_intent_requires_confirmation_no_side_effect():
    svc, http, _ = _service()
    res = svc.chat({"message": "把计划1的cvr调计划到 5%", "history": [], "tool_id": "roi"})
    pending = res["pending_confirmation"]
    assert pending is not None
    assert pending["action"] == "roi__set_plan_params"
    assert pending["args"] == {"plan": "计划1", "params": {"cvr": 0.05}}
    # 预览含计划与参数
    assert "计划1" in pending["preview"] and "cvr" in pending["preview"]
    # 确认前零写副作用
    assert not any(m == "POST" and p.endswith("assistant_params") for m, p, _ in http.calls)


def test_confirm_executes_write_once():
    svc, http, _ = _service()
    res = svc.chat({"message": "把计划1的cvr调计划到 5%", "history": [], "tool_id": "roi"})
    call_id = res["pending_confirmation"]["call_id"]
    res2 = svc.chat({"confirm": call_id, "tool_id": "roi"})
    posts = [b for m, p, b in http.calls if m == "POST" and p.endswith("assistant_params")]
    assert len(posts) == 1 and posts[0] == {"plans": {"计划1": {"cvr": 0.05}}}
    assert "已应用" in res2["reply"] and "1000" in res2["reply"]
    # call_id 一次性：重复确认必须失败
    try:
        svc.chat({"confirm": call_id, "tool_id": "roi"})
        raise AssertionError("重复确认未被拒绝")
    except KeyError:
        pass


def test_out_of_scope_action_refused_without_side_effect():
    svc, http, _ = _service()
    res = svc.chat({"message": "把 coupon-demo-001 的券面改成满300减60", "history": [], "tool_id": "coupon"})
    assert "不支持" in res["reply"]
    assert http.calls == []  # 零执行


def test_backend_unavailable_raises():
    class DeadBackend:
        def chat(self, messages, tools, write_names=None):
            raise BackendUnavailable("no key")

    svc = AssistantService(build_default_registry(ROOT), DeadBackend(), FakeHttp())
    try:
        svc.chat({"message": "你好", "history": [], "tool_id": "roi"})
        raise AssertionError("未抛 BackendUnavailable")
    except BackendUnavailable:
        pass


def test_co_round_read_executes_before_write_staging():
    """round-2 建议回归：同轮写调用前的只读调用先执行并在回复中标注。"""
    fixtures = [
        {"match": "一起看", "reply": "",
         "tool_calls": [{"name": "roi__calc", "args": {}},
                        {"name": "roi__set_plan_params",
                         "args": {"plan": "计划1", "params": {"cvr": 0.05}}}]},
    ]
    http = FakeHttp()
    svc = AssistantService(build_default_registry(ROOT), EchoBackend(fixtures), http)
    res = svc.chat({"message": "帮我一起看", "history": [], "tool_id": "roi"})
    pending = res["pending_confirmation"]
    assert pending and pending["action"] == "roi__set_plan_params"
    assert any(m == "POST" and p == "/t/roi/api/calc" for m, p, _ in http.calls)  # 只读先执行
    assert not any(p.endswith("assistant_params") for _, p, _ in http.calls)      # 写未执行
    assert "顺带完成只读查询" in res["reply"]


def test_zcode_key_resolution_both_layouts(tmp_path, monkeypatch):
    """key 解析：provider_config.json（mini 形态）与 v2/config.json provider 映射（macbook 形态）。"""
    from workbench.assistant import runtime

    zcode = tmp_path / ".zcode" / "v2"
    zcode.mkdir(parents=True)
    # 形态一：providerConfigRules（本机 mini）
    (zcode / "provider_config.json").write_text(json.dumps({
        "config": {"providerConfigRules": {"providerRules": [
            {"providerName": "小米", "config": {"access": {"apiKey": "KEY-RULES"},
                                               "api": {"baseUrl": "https://token-plan-cn.xiaomimimo.com/v1"}}},
        ]}}}, ensure_ascii=False), encoding="utf-8")
    found = runtime._key_from_provider_rules(zcode / "provider_config.json")
    assert found == "KEY-RULES"

    # 形态二：provider 映射（macbook，baseURL 匹配小米）
    (zcode / "config.json").write_text(json.dumps({
        "provider": {
            "other": {"options": {"apiKey": "OTHER-KEY", "baseURL": "https://example.com"}},
            "8b9198ba": {"options": {"apiKey": "KEY-MAP",
                                     "baseURL": "https://token-plan-cn.xiaomimimo.com/v1"}},
        }}, ensure_ascii=False), encoding="utf-8")
    found2 = runtime._key_from_provider_map(zcode / "config.json")
    assert found2 == "KEY-MAP"

    # 端到端：monkeypatch 候选路径后 resolve_llm_config 走通（macbook 形态优先规则在前则先命中 rules）
    monkeypatch.setattr(runtime, "ZCODE_CANDIDATE_CONFIGS", [zcode / "config.json"])
    cfg = runtime.resolve_llm_config(tmp_path)
    assert cfg == {"base_url": "https://token-plan-cn.xiaomimimo.com/v1",
                   "api_key": "KEY-MAP", "model": "mimo-v2.6-pro"}


def test_roi_set_plan_net_none_guard():
    """round-2 建议回归：基准结果缺该计划时摘要兜底而非 TypeError。"""
    fixtures = [
        {"match": "调计划", "reply": "",
         "tool_calls": [{"name": "roi__set_plan_params",
                         "args": {"plan": "计划1", "params": {"cvr": 0.05}}}]},
        {"match": "*", "when_tools": True, "reply": "{tool_result_summary}"},
    ]

    class NoPlanHttp(FakeHttp):
        def __call__(self, method, path, body=None):
            if path == "/t/roi/api/calc":
                return {"scenarios": {"基准": {"plans": [{"name": "别的计划", "net": 1.0}],
                                               "totals": {"net": 1.0}}}}
            return super().__call__(method, path, body)

    http = NoPlanHttp()
    svc = AssistantService(build_default_registry(ROOT), EchoBackend(fixtures), http)
    res = svc.chat({"message": "调计划", "history": [], "tool_id": "roi"})
    call_id = res["pending_confirmation"]["call_id"]
    res2 = svc.chat({"confirm": call_id, "tool_id": "roi"})
    assert "未找到该计划" in res2["reply"]


# ---------- 阶段5 门禁A3：_execute 四条零覆盖分支的执行测试 ----------

COUPON_STATE = {"scenarios": ["coupon-demo-001"], "runs": ["run-1", "run-2"]}


class FakeHttp3(FakeHttp):
    """补充 get_state×3 / forecast__calc / coupon__list_runs / coupon__compare 需要的路径。

    覆写 __call__ 只记录一次；父类的 fallthrough 映射内联（父类 __call__ 会重复记录）。
    """

    def __call__(self, method, path, body=None):
        self.calls.append((method, path, body))
        if path == "/t/coupon/api/state":
            return COUPON_STATE
        if path == "/t/coupon/api/runs":
            return COUPON_STATE["runs"]
        if path == "/t/coupon/api/scenario/coupon-demo-001":
            return {"scenario_id": "coupon-demo-001"}
        if path == "/t/coupon/api/compare":
            return {"rows": [{"label": "无券"}, {"label": "满159减10"}]}
        if path == "/t/roi/api/calc":
            return ROI_CALC_RESULT
        if path == "/t/roi/api/state":
            return ROI_STATE
        if path == "/t/forecast/api/v2/state":
            return FORECAST_STATE
        if path == "/t/forecast/api/v2/plans/plan-1":
            return FORECAST_PLAN_DETAIL
        if path == "/t/forecast/api/v2/plans/plan-1/proposals":
            return FORECAST_PROPOSAL
        if path == "/t/forecast/api/v2/plans/plan-1/proposals/prop-1/apply":
            return FORECAST_APPLY
        if path == "/t/forecast/api/v2/plans/plan-1/runs/RUN-001":
            return {"run": FORECAST_PLAN_DETAIL["runs"][0], "result": {}}
        if path == "/t/forecast/api/v2/plans/plan-1/runs/RUN-002":
            return {"run": FORECAST_PLAN_DETAIL["runs"][1], "result": {}}
        if path == "/t/roi/api/assistant_params":
            return {"saved": True}
        raise AssertionError(f"未预期的调用: {method} {path}")


def _svc3():
    http = FakeHttp3()
    svc = AssistantService(build_default_registry(ROOT), EchoBackend(FIXTURES), http)
    return svc, http


def test_get_state_branch_all_tools():
    svc, http = _svc3()
    assert svc._execute({"name": "coupon__get_state", "args": {}}) == "优惠券：1 个场景，2 个封存运行"
    assert svc._execute({"name": "roi__get_state", "args": {}}) == "投放 ROI：4 个演示计划（合成假设）"
    assert [p for m, p, _ in http.calls] == ["/t/coupon/api/state", "/t/roi/api/state"]


def test_forecast_get_plan_state_branch():
    """forecast 专用读动作：修订/目标/数据质量/确认/最近运行摘要（不含原始订单）。"""
    svc, http = _svc3()
    reply = svc._execute({"name": "forecast__get_plan_state", "args": {"plan_id": "plan-1"}})
    assert "r3" in reply and "12,800,000 元" in reply and "合成演示数据" in reply
    assert "已确认[数据覆盖、口径]" in reply and "质量待确认 1 项" in reply and "RUN-001" in reply
    assert [p for m, p, _ in http.calls] == ["/t/forecast/api/v2/plans/plan-1"]


def test_forecast_compare_runs_branch():
    svc, http = _svc3()
    reply = svc._execute({"name": "forecast__compare_runs",
                          "args": {"plan_id": "plan-1", "run_ids": ["RUN-001", "RUN-002"]}})
    assert "RUN-001（基准 13815000 元）" in reply and "RUN-002（挑战 14761000 元）" in reply


def test_forecast_apply_proposal_branch_write():
    """唯一写动作：经确认门执行，落工作稿（假回环返回 r4），摘要如实。"""
    svc, http = _svc3()
    out = svc.stage("forecast__apply_proposal", {"plan_id": "plan-1", "proposal_id": "prop-1"})
    assert "采纳提案" in out["preview"] and "已有运行不变" in out["preview"]
    res = svc.chat({"confirm": out["call_id"], "tool_id": "forecast"})
    assert "已采纳提案 prop-1（基准情景）" in res["reply"] and "r4" in res["reply"]
    posts = [p for m, p, _ in http.calls if m == "POST"]
    assert "/t/forecast/api/v2/plans/plan-1/proposals/prop-1/apply" in posts


def test_missing_executor_raises_no_fake_success():
    """不假成功：声明动作缺执行器必须 raise（不再返回'已执行'）。"""
    svc, _ = _svc3()
    svc._by_name["forecast__ghost"] = {"x-tool": "forecast", "x-action": "ghost", "x-write": False}
    try:
        svc._execute({"name": "forecast__ghost", "args": {}})
        raise AssertionError("缺执行器未被拒绝")
    except ValueError as e:
        assert "拒绝假成功" in str(e)


def test_forecast_propose_branch():
    """forecast v2：AI 只提案（dry-run）——先取修订号再登记提案，工作稿零改动。"""
    svc, http = _svc3()
    reply = svc._execute({"name": "forecast__propose_plan_changes",
                          "args": {"plan_id": "plan-1", "scenario": "基准",
                                   "patches": {"new_customers_growth": 0.2}, "rationale": "获客加码"}})
    assert "基准" in reply and "new_customers_growth: 0.1 → 0.2" in reply and "未生效" in reply
    posts = [b for m, p, b in http.calls if m == "POST"]
    assert posts == [{"scenario": "基准", "patches": {"new_customers_growth": 0.2},
                      "rationale": "获客加码", "base_revision": 3}]
    # 提案动作不是写门：不进 pending 确认
    assert svc._pending == {}


def test_forecast_propose_via_chat_not_gated():
    """chat 闭环：forecast 提案直接执行（非写门），回复携带差异摘要。"""
    svc, http = _svc3()
    res = svc.chat({"message": "给基准情景建议", "history": [], "tool_id": "forecast"})
    assert res["pending_confirmation"] is None
    assert "建议已生成" in res["reply"] and "new_customers_growth" in res["reply"]
    assert any(m == "POST" and p.endswith("/proposals") for m, p, _ in http.calls)


def test_coupon_list_runs_branch_dual_shape():
    svc, http = _svc3()
    assert svc._execute({"name": "coupon__list_runs", "args": {}}) == "已封存运行 2 个：run-1, run-2"
    # dict 形态容错：runs 路径返回 {"runs": [...]} 而非裸 list
    class FakeHttp3Dict(FakeHttp3):
        def __call__(self, method, path, body=None):
            self.calls.append((method, path, body))
            if path == "/t/coupon/api/runs":
                return {"runs": COUPON_STATE["runs"]}
            return FakeHttp3.__call__(self, method, path, body)
    svc2 = AssistantService(build_default_registry(ROOT), EchoBackend(FIXTURES), FakeHttp3Dict())
    assert svc2._execute({"name": "coupon__list_runs", "args": {}}).startswith("已封存运行 2 个")


def test_coupon_compare_branch():
    svc, http = _svc3()
    reply = svc._execute({"name": "coupon__compare", "args": {"scenario_id": "coupon-demo-001"}})
    assert reply == "场景 coupon-demo-001 比较完成：2 个候选（含无券基准）"
    gets = [p for m, p, _ in http.calls if m == "GET"]
    assert "/t/coupon/api/scenario/coupon-demo-001" in gets
    posts = [b for m, p, b in http.calls if m == "POST" and p == "/t/coupon/api/compare"]
    assert posts == [{"scenario": {"scenario_id": "coupon-demo-001"}}]


# ---------- Path A：orchestrated 透传与双登记防回归 ----------

class OrchestratedBackend:
    """模拟 pi-agent sidecar：已自行编排，写项带 stage_pending/call_id。"""
    def __init__(self, result):
        self.result = result
        self.calls = 0

    def chat(self, messages, tools, write_names=None):
        self.calls += 1
        return self.result


def test_orchestrated_relay_rebuilds_pending_without_restage():
    from workbench.assistant.backend import ChatResult
    svc, http = _svc3()
    svc2 = AssistantService(svc.registry, None, http)  # 同一 registry/http，backend 后换
    staged = svc2.stage("roi__set_plan_params", {"plan": "计划1", "params": {"cvr": 0.05}})
    before = dict(svc2._pending)
    result = ChatResult(
        reply="已登记，请确认", orchestrated=True,
        tool_calls=[{"name": "roi__set_plan_params", "args": staged["args"],
                     "summary": "写提案已登记", "stage_pending": True, "call_id": staged["call_id"]}])
    svc2.backend = OrchestratedBackend(result)
    res = svc2.chat({"message": "把计划1 cvr 调到 5%", "history": [], "tool_id": "roi"})
    assert res["pending_confirmation"]["call_id"] == staged["call_id"]
    assert res["pending_confirmation"]["args"] == staged["args"]
    assert "preview" in res["pending_confirmation"]
    assert res["reply"] == "已登记，请确认"
    # 防回归核心：不再执行/登记（_pending 不变，无额外 HTTP 工具调用）
    assert svc2._pending == before
    assert len(http.calls) == 0
    assert svc2.backend.calls == 1


def test_exec_read_and_stage_name_gating():
    import pytest as _pytest
    svc, _ = _svc3()
    with _pytest.raises(ValueError):
        svc.exec_read("roi__set_plan_params", {})   # 写工具不可走读执行
    with _pytest.raises(ValueError):
        svc.stage("roi__get_state", {})             # 读工具不可走写登记
    with _pytest.raises(ValueError):
        svc.exec_read("nope", {})
    out = svc.stage("roi__set_plan_params", {"plan": "计划1", "params": {"cvr": 0.2}})
    assert out["call_id"] and out["action"] == "roi__set_plan_params" and out["preview"]
    assert out["call_id"] in svc._pending


def test_orchestrated_multi_write_relays_first_cancels_rest():
    """N1：多写 run 只透传首个 pending，其余取消不留孤儿，并如实告知。"""
    from workbench.assistant.backend import ChatResult
    svc, http = _svc3()
    a = svc.stage("roi__set_plan_params", {"plan": "计划1", "params": {"cvr": 0.05}})
    b = svc.stage("roi__set_plan_params", {"plan": "计划2", "params": {"cvr": 0.1}})
    result = ChatResult(reply="已登记", orchestrated=True, tool_calls=[
        {"name": "roi__set_plan_params", "args": a["args"], "summary": "s1", "stage_pending": True,
         "call_id": a["call_id"], "preview": "p1"},
        {"name": "roi__set_plan_params", "args": b["args"], "summary": "s2", "stage_pending": True,
         "call_id": b["call_id"], "preview": "p2"}])
    svc.backend = OrchestratedBackend(result)
    res = svc.chat({"message": "两个都调", "history": [], "tool_id": "roi"})
    assert res["pending_confirmation"]["call_id"] == a["call_id"]      # 透传首个
    assert set(svc._pending) == {a["call_id"]}                          # 其余已取消，无孤儿
    assert "1 个写提案未一并提交" in res["reply"] and "请逐个提出确认" in res["reply"]


def test_exec_read_returns_raw_result():
    """摘要有损修复：exec_read 返回 {summary, result}，result 原文补齐信息。"""
    svc, _ = _svc3()
    out = svc.exec_read("roi__get_state", {})
    assert out["summary"] == "投放 ROI：4 个演示计划（合成假设）"
    assert out["result"]["plans"] == [{"name": f"计划{i}"} for i in range(1, 5)]  # 计划名终于可得
    out2 = svc.exec_read("coupon__list_runs", {})
    assert out2["result"]["runs"] == COUPON_STATE["runs"]


# ---------- (c)-resume：checkpoint_staged 透传与确认双模 ----------

def test_relay_checkpoint_staged_builds_pending_with_key():
    from workbench.assistant.backend import ChatResult
    svc, http = _svc3()
    result = ChatResult(reply="提案待确认", orchestrated=True, tool_calls=[
        {"name": "roi__set_plan_params", "args": {"plan": "计划1", "params": {"cvr": 0.05}},
         "summary": "写提案待确认", "stage_pending": True, "call_id": "cp123", "checkpoint_staged": True}])
    svc.backend = OrchestratedBackend(result)
    res = svc.chat({"message": "调参", "history": [], "tool_id": "roi"})
    assert res["pending_confirmation"]["call_id"] == "cp123"
    assert svc._pending["cp123"]["checkpoint_key"] == "cp123"
    assert "preview" in res["pending_confirmation"]
    assert len(http.calls) == 0  # 不调 /stage（检查点路径）


class _FakeResumeBackend(OrchestratedBackend):
    """支持 resume 注入的 PiSidecarBackend 替身（isinstance 检查走 duck 类型）。"""


def test_confirm_via_resume_ok_passthrough():
    from workbench.assistant.backend import PiSidecarBackend as _PSB
    svc, http = _svc3()
    svc._pending["cp1"] = {"name": "roi__set_plan_params", "args": {"plan": "P"}, "checkpoint_key": "cp1"}
    executed = {}

    class B(_PSB):
        def chat(self, messages, tools, write_names=None):
            raise AssertionError("不应走 chat")

        def resume(self, call_id):
            executed["call_id"] = call_id
            return "ok", {"reply": "已重算完成", "tool_calls": [
                {"name": "roi__set_plan_params", "args": {"plan": "P"}, "summary": "净贡献 100.00 元"}]}

    svc.backend = B()
    res = svc._confirm("cp1")
    assert res["reply"] == "已重算完成"
    assert executed["call_id"] == "cp1"
    assert "cp1" not in svc._pending


def test_confirm_via_resume_definite_failure_degrades_once():
    from workbench.assistant.backend import PiSidecarBackend as _PSB
    svc, http = _svc3()
    svc._pending["cp2"] = {"name": "coupon__list_runs", "args": {}, "checkpoint_key": "cp2"}
    # 用只读工具当"写"来观察降级执行——改为正确写工具但 http 记录调用
    svc._pending["cp2"] = {"name": "roi__set_plan_params", "args": {"plan": "计划1", "params": {}},
                           "checkpoint_key": "cp2"}
    calls_before = len(http.calls)

    class B(_PSB):
        def chat(self, messages, tools, write_names=None):
            from workbench.assistant.backend import ChatResult
            return ChatResult(reply="降级措辞")

        def resume(self, call_id):
            raise BackendUnavailable("/resume 失败（未执行）：HTTP 404")

    svc.backend = B()
    res = svc._confirm("cp2")
    assert res["reply"] == "降级措辞"
    assert len(http.calls) > calls_before  # 降级路径执行了写舞步（http 回环）
    assert "cp2" not in svc._pending


def test_confirm_via_resume_maybe_executed_does_not_reexecute():
    from workbench.assistant.backend import PiSidecarBackend as _PSB
    svc, http = _svc3()
    svc._pending["cp3"] = {"name": "roi__set_plan_params", "args": {"plan": "P"}, "checkpoint_key": "cp3"}
    calls_before = len(http.calls)

    class B(_PSB):
        def resume(self, call_id):
            return "maybe_executed", {"error": "终稿轮失败"}

    svc.backend = B()
    res = svc._confirm("cp3")
    assert "可能已执行" in res["reply"]
    assert len(http.calls) == calls_before  # 不降级执行
    assert "cp3" not in svc._pending


def test_confirm_via_resume_timeout_puts_back_and_skips():
    from workbench.assistant.backend import PiSidecarBackend as _PSB, _ResumeTimeout
    svc, http = _svc3()
    svc._pending["cp4"] = {"name": "roi__set_plan_params", "args": {"plan": "P"}, "checkpoint_key": "cp4"}
    calls_before = len(http.calls)

    class B(_PSB):
        def resume(self, call_id):
            raise _ResumeTimeout("timed out")

    svc.backend = B()
    res = svc._confirm("cp4")
    assert "恢复超时" in res["reply"] and "状态未知" in res["reply"]
    assert len(http.calls) == calls_before            # 不执行
    assert svc._pending["cp4"]["checkpoint_key"] == "cp4"  # 未弹出，可再确认重试
