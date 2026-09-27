"""LLM 后端抽象：Echo 回放 / OpenAI 兼容直连 / 自动探测。

后端协议：chat(messages, tools) -> {"reply": str, "tool_calls": [{name, args}]}
- messages: OpenAI chat messages 列表（可含 role=tool 的结果回灌）
- 后端不可用时 raise BackendUnavailable（壳层转 503 + 配置指引）
"""
from __future__ import annotations

import json
import urllib.error
import urllib.request
from dataclasses import dataclass, field


class BackendUnavailable(RuntimeError):
    """无可用 LLM 后端（缺 key / sidecar 不可达）。"""


@dataclass
class ChatResult:
    reply: str = ""
    tool_calls: list[dict] = field(default_factory=list)


class EchoBackend:
    """回放后端：按预录脚本响应。reply 支持 {tool_result_summary} 占位符——
    由最后一条 role=tool 消息的执行摘要替换，使闭环可断言。仅测试/离线使用。"""

    def __init__(self, fixtures: list[dict]):
        # fixtures: [{"match": str, "reply": str, "tool_calls": [...], "when_tools": bool}]
        self.fixtures = fixtures
        self.calls = 0  # 测试可断言调用次数

    def chat(self, messages: list[dict], tools: list[dict]) -> ChatResult:
        self.calls += 1
        has_tools = any(m.get("role") == "tool" for m in messages)
        last_user = next((m["content"] for m in reversed(messages) if m.get("role") == "user"), "")
        # 后定义的 fixture 优先：允许具体匹配覆盖 "*" 兜底
        for fx in reversed(self.fixtures):
            if bool(fx.get("when_tools")) != has_tools:
                continue
            match = fx.get("match", "*")
            if match == "*" or match in last_user:
                summary = ""
                if has_tools:
                    last_tool = next(m for m in reversed(messages) if m.get("role") == "tool")
                    summary = last_tool.get("content", "")
                return ChatResult(
                    reply=fx.get("reply", "").replace("{tool_result_summary}", summary),
                    tool_calls=[{"name": tc["name"], "args": tc.get("args") or {}}
                                for tc in fx.get("tool_calls") or []],
                )
        return ChatResult(reply="（回放后端无匹配脚本）")


class PiSidecarBackend:
    """pi-ai Node sidecar 代理（8321）：真身是 @earendil-works/pi-ai 驱动的小米 MIMO。"""

    def __init__(self, base_url: str = "http://127.0.0.1:8321", timeout: int = 150):
        self.url = base_url.rstrip("/")
        self.timeout = timeout

    @staticmethod
    def healthy(base_url: str = "http://127.0.0.1:8321", timeout: float = 1.5) -> bool:
        try:
            with urllib.request.urlopen(base_url.rstrip("/") + "/health", timeout=timeout) as r:
                return r.status == 200
        except Exception:  # noqa: BLE001 —— 探测只问可达性
            return False

    def chat(self, messages: list[dict], tools: list[dict]) -> ChatResult:
        body = json.dumps({"messages": messages, "tools": tools}).encode("utf-8")
        req = urllib.request.Request(self.url + "/chat", data=body,
                                     headers={"Content-Type": "application/json"}, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                data = json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            if exc.code == 503:
                raise BackendUnavailable(f"pi sidecar 未配置 key：{exc.read().decode('utf-8', 'ignore')[:200]}") from exc
            raise BackendUnavailable(f"pi sidecar 调用失败：HTTP {exc.code}") from exc
        except Exception as exc:  # noqa: BLE001
            raise BackendUnavailable(f"pi sidecar 不可达：{exc}") from exc
        return ChatResult(reply=data.get("reply") or "",
                          tool_calls=[{"name": tc["name"], "args": tc.get("args") or {}}
                                      for tc in data.get("tool_calls") or []])


class OpenAiCompatBackend:
    """OpenAI 兼容 chat/completions 直连（stdlib urllib，无新增依赖）。"""

    def __init__(self, base_url: str, api_key: str, model: str, timeout: int = 120):
        self.url = base_url.rstrip("/") + "/chat/completions"
        self.api_key = api_key
        self.model = model
        self.timeout = timeout

    def chat(self, messages: list[dict], tools: list[dict]) -> ChatResult:
        body = {"model": self.model, "messages": messages}
        if tools:
            body["tools"] = tools
        req = urllib.request.Request(
            self.url, data=json.dumps(body).encode("utf-8"),
            headers={"Content-Type": "application/json", "Authorization": f"Bearer {self.api_key}"},
            method="POST")
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                data = json.loads(resp.read().decode("utf-8"))
        except Exception as exc:  # noqa: BLE001 —— 网络/鉴权错误统一转后端不可用
            raise BackendUnavailable(f"LLM 请求失败：{exc}") from exc
        msg = data["choices"][0]["message"]
        return ChatResult(
            reply=msg.get("content") or "",
            tool_calls=[{"name": tc["function"]["name"],
                         "args": json.loads(tc["function"].get("arguments") or "{}")}
                        for tc in msg.get("tool_calls") or []],
        )
