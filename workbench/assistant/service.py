"""助手编排：一轮「LLM → tool 执行 → 结果回灌 → 回复」闭环。

- 只读 action 直接执行（内部 HTTP 回环，G7）
- 写 action（x-write）走两步确认门（G2）：pending_confirmation -> {confirm: call_id}
- 上下文注入裁剪（G3）：system 只带轻量元信息，全量数值经 tool 现取
- 会话内存态（G4）：pending 表随进程，刷新即新会话
"""
from __future__ import annotations

import uuid

from . import tools as tools_mod

SYSTEM_PROMPT = (
    "你是测算工作台的助手。工作台有三个测算工具：目标测算（forecast，人货场三视角 GMV 目标）、"
    "优惠券测算（coupon，满减券情景比较）、投放 ROI（roi，投放计划盈亏）。\n"
    "用户当前在「{tool_name}」工具中。你可以调用工具读取状态与执行测算；"
    "涉及修改参数的调用会经用户确认后才生效。回答使用中文、简洁、带关键数字。\n"
    "你的一切数据都来自工具调用，不要编造数值。"
)


class AssistantService:
    def __init__(self, registry, backend, http_call):
        """http_call: (method, path, body|None) -> dict —— 内部 HTTP 回环（壳的 /t/{id}/api/）。"""
        self.registry = registry
        self.backend = backend
        self.http = http_call
        self.tools = tools_mod.build_tools(registry)
        self._by_name = {t["function"]["name"]: t["function"] for t in self.tools}
        self._pending: dict[str, dict] = {}

    # ---------- 入口 ----------

    MAX_ROUNDS = 4  # 单轮反馈上限：防 LLM 连环 tool_call 失控（自主多步属 P3 之后）

    def chat(self, payload: dict) -> dict:
        if payload.get("confirm"):
            return self._confirm(payload["confirm"])
        if payload.get("cancel"):
            tc = self._pending.pop(payload["cancel"], None)
            return {"reply": "已取消该变更。" if tc else "该变更不存在或已处理。",
                    "tool_calls": [], "pending_confirmation": None}
        tool_id = payload.get("tool_id") or ""
        tool = self.registry.get(tool_id)
        messages = [
            {"role": "system", "content": SYSTEM_PROMPT.format(tool_name=tool["name"] if tool else tool_id)},
            *(payload.get("history") or []),
            {"role": "user", "content": payload.get("message", "")},
        ]
        result = self.backend.chat(messages, tools_mod.to_openai(self.tools))
        executed: list[tuple[dict, str]] = []

        for _ in range(self.MAX_ROUNDS):
            known = [tc for tc in result.tool_calls if tc["name"] in self._by_name]
            unknown = [tc for tc in result.tool_calls if tc["name"] not in self._by_name]

            if unknown and not known:
                return self._refuse(messages, result)

            writes = [tc for tc in known if self._by_name[tc["name"]]["x-write"]]
            if writes:
                # 同轮只读调用先执行，写操作进确认门；丢弃项计数如实告知
                reads = [(tc, self._execute(tc)) for tc in known
                         if not self._by_name[tc["name"]]["x-write"]]
                executed.extend(reads)
                dropped = len(writes) - 1 + len(unknown)
                return self._stage_write(result.reply, writes[0], dropped=dropped,
                                          executed=[s for _, s in reads])

            if not known:
                return {"reply": result.reply, "tool_calls": [{**tc, "summary": s} for tc, s in executed],
                        "pending_confirmation": None}

            summaries = [(tc, self._execute(tc)) for tc in known]
            executed.extend(summaries)
            messages = self._feed(messages, result, summaries)
            result = self.backend.chat(messages, tools_mod.to_openai(self.tools))

        return {"reply": result.reply or executed[-1][1], "tool_calls": [{**tc, "summary": s} for tc, s in executed],
                "pending_confirmation": None}

    # ---------- 两步确认（G2） ----------

    def _stage_write(self, reply: str, tc: dict, dropped: int = 0, executed: list | None = None) -> dict:
        call_id = uuid.uuid4().hex[:12]
        self._pending[call_id] = tc
        note = f"（另有 {dropped} 个调用未一并提交）" if dropped else ""
        done = " ".join(executed or [])
        return {
            "reply": (reply or "好的，请确认以下参数变更：") + note + (f" 已顺带完成只读查询：{done}" if done else ""),
            "tool_calls": [],
            "pending_confirmation": {
                "call_id": call_id,
                "action": tc["name"],
                "args": tc["args"],
                "preview": self._preview(tc),
            },
        }

    def _confirm(self, call_id: str) -> dict:
        tc = self._pending.pop(call_id)  # 一次性；重复确认 KeyError
        summary = self._execute(tc)
        messages = [
            {"role": "system", "content": "用户已确认参数变更，请简述结果。"},
            {"role": "user", "content": f"已确认执行 {tc['name']}，请简述结果。"},
            {"role": "tool", "name": tc["name"], "content": summary},
        ]
        final = self.backend.chat(messages, [])
        return {"reply": final.reply or summary, "tool_calls": [{**tc, "summary": summary}],
                "pending_confirmation": None}

    def _preview(self, tc: dict) -> str:
        name, args = tc["name"], tc["args"]
        try:
            if name == "forecast__set_scenario_params":
                state = self.http("GET", "/t/forecast/api/state", None)
                old = (state.get("scenarios") or {}).get(args["scenario"], {})
                lines = [f"{k}: {old.get(k, '—')} → {v}" for k, v in args["params"].items()]
                return f"目标测算「{args['scenario']}」情景：" + "；".join(lines)
            if name == "roi__set_plan_params":
                return f"投放计划「{args['plan']}」参数：" + "；".join(f"{k} → {v}" for k, v in args["params"].items())
        except Exception:  # noqa: BLE001 —— 预览失败不阻断确认门
            pass
        return f"{name} {args}"

    # ---------- 执行 ----------

    def _refuse(self, messages: list, result) -> dict:
        # 未知能力：把「不支持」作为 tool 结果回灌，让后端组织拒答话术
        fed = messages + [
            {"role": "assistant", "content": result.reply or ""},
            *[ {"role": "tool", "name": tc["name"], "content": "未知工具：不在工作台能力清单内"}
               for tc in result.tool_calls ],
        ]
        final = self.backend.chat(fed, [])
        return {"reply": final.reply or "抱歉，这个操作超出我当前的能力范围。", "tool_calls": [], "pending_confirmation": None}

    def _feed(self, messages: list, result, summaries: list) -> list:
        """结果回灌：assistant 的 tool_calls 带稳定 id 与 JSON 参数，tool 消息带 tool_call_id。"""
        import json as _json
        call_ids = {id(tc): f"call_{uuid.uuid4().hex[:8]}" for tc, _ in summaries}
        return messages + [
            {"role": "assistant", "content": result.reply or "",
             "tool_calls": [{"id": call_ids[id(tc)], "type": "function",
                             "function": {"name": tc["name"], "arguments": _json.dumps(tc["args"], ensure_ascii=False)}}
                            for tc, _ in summaries]},
            *[ {"role": "tool", "tool_call_id": call_ids[id(tc)], "name": tc["name"], "content": s}
               for tc, s in summaries ],
        ]

    def _execute(self, tc: dict) -> str:
        name, args = tc["name"], (tc["args"] or {})
        tool = self._by_name[name]["x-tool"]
        action = self._by_name[name]["x-action"]
        if action == "get_state":
            return _summarize_state(tool, self.http("GET", f"/t/{tool}/api/state", None))
        if name == "forecast__calc":
            data = self.http("POST", "/t/forecast/api/calc", {"scenarios": args.get("scenarios") or {}})
            nets = {r["scenario"]: round(sum(x["GMV_主口径"] for x in data["consolidated"] if x["scenario"] == r["scenario"]), 0)
                    for r in data["consolidated"]}
            return "全渠道年化GMV（按情景）：" + "；".join(f"{k} {v:.0f} 元" for k, v in nets.items())
        if name == "forecast__set_scenario_params":
            sc, params = args["scenario"], args["params"]
            self.http("POST", "/t/forecast/api/assistant_params", {"scenarios": {sc: params}})
            state = self.http("GET", "/t/forecast/api/state", None)
            saved = self.http("GET", "/t/forecast/api/assistant_params", None)
            merged = {n: {**p, **(saved.get("scenarios") or {}).get(n, {})} for n, p in state["scenarios"].items()}
            data = self.http("POST", "/t/forecast/api/calc", {"scenarios": merged})
            gmv = sum(x["GMV_主口径"] for x in data["consolidated"] if x["scenario"] == sc)
            return f"挑战情景已保存并重算：年化GMV {gmv:.0f} 元".replace("挑战", sc)
        if name == "roi__calc":
            body = {k: args[k] for k in ("plans", "scenarios") if k in args}
            if "plans" not in body:  # 省略 plans 时用演示计划集
                body["plans"] = self.http("GET", "/t/roi/api/state", None)["plans"]
            if "scenarios" not in body:
                body["scenarios"] = self.http("GET", "/t/roi/api/state", None)["scenarios"]
            data = self.http("POST", "/t/roi/api/calc", body)
            return _summarize_roi_calc(data, args)
        if name == "roi__set_plan_params":
            plan, params = args["plan"], args["params"]
            self.http("POST", "/t/roi/api/assistant_params", {"plans": {plan: params}})
            state = self.http("GET", "/t/roi/api/state", None)
            saved = self.http("GET", "/t/roi/api/assistant_params", None)
            plans = []
            for p in state["plans"]:
                patch = (saved.get("plans") or {}).get(p["name"], {})
                plans.append({**p, **patch})
            data = self.http("POST", "/t/roi/api/calc", {"plans": plans, "scenarios": state["scenarios"]})
            base = data["scenarios"].get("基准", {})
            net = next((p["net"] for p in base.get("plans", []) if p["name"] == plan), None)
            if net is None:
                return f"计划「{plan}」参数已保存，但基准结果中未找到该计划"
            return f"计划「{plan}」参数已保存，基准情景净贡献 {net:.2f} 元"
        if name == "coupon__list_runs":
            data = self.http("GET", "/t/coupon/api/runs", None)
            runs = data if isinstance(data, list) else data.get("runs", [])
            return f"已封存运行 {len(runs)} 个" + (f"：{', '.join(r[:8] for r in runs[:3])}" if runs else "")
        if name == "coupon__compare":
            spec = self.http("GET", f"/t/coupon/api/scenario/{args['scenario_id']}", None)
            data = self.http("POST", "/t/coupon/api/compare", {"scenario": spec})
            labels = [r["label"] for r in data.get("rows", [])]
            return f"场景 {args['scenario_id']} 比较完成：{len(labels)} 个候选（含无券基准）"
        return f"已执行 {name}"


def _summarize_state(tool: str, data: dict) -> str:
    if tool == "forecast":
        plats = data.get("platforms", {})
        mode_a = sum(1 for v in plats.values() if v.get("mode") == "A")
        demo = "演示" if data.get("demo_used") else "正式"
        return f"目标测算：{len(plats)} 平台（明细{mode_a}/聚合{len(plats)-mode_a}），{demo}数据"
    if tool == "coupon":
        return f"优惠券：{len(data.get('scenarios', []))} 个场景，{len(data.get('runs', []))} 个封存运行"
    if tool == "roi":
        return f"投放 ROI：{len(data.get('plans', []))} 个演示计划（合成假设）"
    return f"{tool} 状态已读取"


def _summarize_roi_calc(data: dict, args: dict) -> str:
    scenarios = data.get("scenarios", {})
    name = next(iter(args.get("scenarios") or ["基准"]), "基准")
    sc = scenarios.get(name) or next(iter(scenarios.values()), {})
    totals = sc.get("totals", {})
    n = len(sc.get("plans", []))
    # 裸数字摘要：reply 模板自带上下文语（"合计净贡献为 {summary}"）
    return f"{totals.get('net', 0):.2f} 元（{n} 个计划）"
