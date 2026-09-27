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
FORECAST_STATE = {
    "demo_used": False,
    "platforms": {"天猫": {"mode": "A"}, "私域": {"mode": "B"}},
    "scenarios": {
        "保守": {"new_customers_growth": 0.03},
        "基准": {"new_customers_growth": 0.10},
        "挑战": {"new_customers_growth": 0.10},
    },
}
FORECAST_CALC = {"consolidated": [{"scenario": "挑战", "GMV_主口径": 123456.0}]}


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
        if path == "/t/forecast/api/state":
            return FORECAST_STATE
        if path == "/t/forecast/api/calc":
            return FORECAST_CALC
        if path == "/t/forecast/api/assistant_params":
            return {"saved": True}
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
    res = svc.chat({"message": "把挑战情景新客增速调到 25%", "history": [], "tool_id": "forecast"})
    pending = res["pending_confirmation"]
    assert pending is not None
    assert pending["action"] == "forecast__set_scenario_params"
    assert pending["args"] == {"scenario": "挑战", "params": {"new_customers_growth": 0.25}}
    # 预览含旧值与新值
    assert "new_customers_growth" in pending["preview"] and "0.25" in pending["preview"]
    # 确认前零写副作用（只允许只读的 GET state 取预览旧值）
    assert not any(m == "POST" and p.endswith("assistant_params") for m, p, _ in http.calls)


def test_confirm_executes_write_once():
    svc, http, _ = _service()
    res = svc.chat({"message": "把挑战情景新客增速调到 25%", "history": [], "tool_id": "forecast"})
    call_id = res["pending_confirmation"]["call_id"]
    res2 = svc.chat({"confirm": call_id, "tool_id": "forecast"})
    posts = [b for m, p, b in http.calls if m == "POST" and p.endswith("assistant_params")]
    assert len(posts) == 1 and posts[0] == {"scenarios": {"挑战": {"new_customers_growth": 0.25}}}
    assert "已应用" in res2["reply"] and "123456" in res2["reply"]
    # call_id 一次性：重复确认必须失败
    try:
        svc.chat({"confirm": call_id, "tool_id": "forecast"})
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
        def chat(self, messages, tools):
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
                        {"name": "forecast__set_scenario_params",
                         "args": {"scenario": "挑战", "params": {"new_customers_growth": 0.25}}}]},
    ]
    http = FakeHttp()
    svc = AssistantService(build_default_registry(ROOT), EchoBackend(fixtures), http)
    res = svc.chat({"message": "帮我一起看", "history": [], "tool_id": "forecast"})
    pending = res["pending_confirmation"]
    assert pending and pending["action"] == "forecast__set_scenario_params"
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
