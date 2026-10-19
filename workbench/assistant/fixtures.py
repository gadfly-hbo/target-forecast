"""Echo 回放 fixtures（GRILL G6）：合成响应，非 LLM 输出。

when_tools=False 匹配首轮（用户原话）；when_tools=True 匹配 tool 结果回灌后
的第二轮。reply 的 {tool_result_summary} 由执行摘要替换。
"""
from __future__ import annotations

FIXTURES = [
    # ① 解读类：问 roi 基准净贡献
    {
        "match": "净贡献",
        "reply": "",
        "tool_calls": [{"name": "roi__calc", "args": {"scenarios": {"基准": {}}}}],
    },
    {
        "match": "*",
        "when_tools": True,
        "reply": "基准情景的合计净贡献为 {tool_result_summary}。",
    },
    # ② 调参类：roi 计划调参（写操作，走确认门）
    {
        "match": "调计划",
        "reply": "好的，请确认以下参数变更。",
        "tool_calls": [{"name": "roi__set_plan_params",
                        "args": {"plan": "计划1", "params": {"cvr": 0.05}}}],
    },
    {
        "match": "已确认",
        "when_tools": True,
        "reply": "已应用。{tool_result_summary}",
    },
    # ④ 提案类：forecast 提案 dry-run（G2 双轨：非写门、直接执行、不落草稿，采纳在工作区发起）
    {
        "match": "给基准情景建议",
        "reply": "",
        "tool_calls": [{"name": "forecast__propose_plan_changes",
                        "args": {"plan_id": "plan-1", "scenario": "基准",
                                 "patches": {"new_customers_growth": 0.2},
                                 "rationale": "获客加码"}}],
    },
    {
        "match": "给基准情景建议",
        "when_tools": True,
        "reply": "建议已生成：{tool_result_summary}",
    },
    # ③ 越界类：要求改优惠券场景（不存在的 action）
    {
        "match": "券面",
        "reply": "",
        "tool_calls": [{"name": "coupon__modify_scenario",
                        "args": {"scenario_id": "coupon-demo-001"}}],
    },
    {
        "match": "券面",
        "when_tools": True,
        "reply": "抱歉，我暂不支持修改优惠券场景本身，可以为你比较已保存场景的候选方案。",
    },
]
