"""P3 切片 1：插件 actions 声明与 tools 生成器。"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from workbench import build_default_registry  # noqa: E402
from workbench.assistant import tools  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent

EXPECTED_ACTIONS = {
    # forecast v2（G2 双轨）：读+提案 dry-run 不落草稿；唯一写动作 apply_proposal 走确认门
    "forecast": {"get_plan_state", "compare_runs", "propose_plan_changes", "apply_proposal"},
    "coupon": {"get_state", "list_runs", "compare"},
    "roi": {"get_state", "calc", "set_plan_params"},
}
WRITE_ACTIONS = {"forecast__apply_proposal", "roi__set_plan_params"}


def _registry():
    return build_default_registry(ROOT)


def test_all_tools_declare_expected_actions():
    reg = _registry()
    for tool_id, expected in EXPECTED_ACTIONS.items():
        tool = reg.get(tool_id)
        assert tool is not None, tool_id
        declared = {a["id"] for a in tool.get("actions") or []}
        assert expected <= declared, f"{tool_id} 缺 action: {expected - declared}"


def test_action_schemas_are_valid_json_schema():
    reg = _registry()
    for tool_id in EXPECTED_ACTIONS:
        for a in reg.get(tool_id)["actions"]:
            params = a["parameters"]
            assert params["type"] == "object", f"{tool_id}.{a['id']} 参数须为 object"
            assert isinstance(params.get("properties"), dict)
            # 可序列化（LLM tool 定义必须 JSON 干净）
            json.dumps(a, ensure_ascii=False)
            assert a["description"].strip(), f"{tool_id}.{a['id']} 缺描述"


def test_write_actions_flagged():
    reg = _registry()
    flagged = set()
    for tool_id in EXPECTED_ACTIONS:
        for a in reg.get(tool_id)["actions"]:
            if a.get("write"):
                flagged.add(f"{tool_id}__{a['id']}")
    assert flagged == WRITE_ACTIONS


def test_build_tools_namespaced_with_write_marks():
    built = tools.build_tools(_registry())
    names = {t["function"]["name"] for t in built}
    assert "forecast__propose_plan_changes" in names and "roi__set_plan_params" in names and "coupon__compare" in names
    by_name = {t["function"]["name"]: t for t in built}
    assert by_name["roi__set_plan_params"]["function"]["x-write"] is True
    assert by_name["forecast__get_plan_state"]["function"]["x-write"] is False
    # forecast 提案非写门（dry-run）；唯一写动作 apply_proposal 走确认门；scenario 枚举
    assert by_name["forecast__propose_plan_changes"]["function"]["x-write"] is False
    assert by_name["forecast__apply_proposal"]["function"]["x-write"] is True
    sc = by_name["forecast__propose_plan_changes"]["function"]["parameters"]["properties"]["scenario"]
    assert sc["enum"] == ["保守", "基准", "挑战"]


def test_to_openai_strips_extension_fields():
    built = tools.build_tools(_registry())
    oai = tools.to_openai(built)
    for t in oai:
        assert not any(k.startswith("x-") for k in t["function"])
        assert set(t) == {"type", "function"}
