"""助手运行时：key 解析（D4 优先级）+ 后端装配 + 内部 HTTP 回环。

key 解析优先级：workspace/assistant.env（gitignored 手写覆盖）→
~/.zcode/v2/provider_config.json 的小米 provider → env WORKBENCH_LLM_*。
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import urllib.error
import urllib.request
from pathlib import Path

from .backend import BackendUnavailable, EchoBackend, OpenAiCompatBackend, PiSidecarBackend
from .fixtures import FIXTURES
from .service import AssistantService

ZCODE_PROVIDER_CONFIG = Path.home() / ".zcode" / "v2" / "provider_config.json"
MIMO_BASE_URL = "https://token-plan-cn.xiaomimimo.com/v1"
DEFAULT_MODEL = "mimo-v2.6-pro"
SIDECAR_PORT = 8321


def resolve_llm_config(root: Path) -> dict | None:
    """按优先级解析 LLM 配置；都缺则 None。"""
    env_file = Path(root) / "workspace" / "assistant.env"
    if env_file.is_file():
        cfg = _parse_env_file(env_file)
        if cfg.get("WORKBENCH_LLM_API_KEY"):
            return {"base_url": cfg.get("WORKBENCH_LLM_BASE_URL", MIMO_BASE_URL),
                    "api_key": cfg["WORKBENCH_LLM_API_KEY"],
                    "model": cfg.get("WORKBENCH_LLM_MODEL", DEFAULT_MODEL)}

    if ZCODE_PROVIDER_CONFIG.is_file():
        try:
            data = json.loads(ZCODE_PROVIDER_CONFIG.read_text(encoding="utf-8"))
            rules = data["config"]["providerConfigRules"]["providerRules"]
            xiaomi = next(r for r in rules if "米" in r.get("providerName", ""))
            key = xiaomi["config"]["access"]["apiKey"]
            if key:
                return {"base_url": MIMO_BASE_URL, "api_key": key, "model": DEFAULT_MODEL}
        except (KeyError, StopIteration, json.JSONDecodeError):
            pass

    if os.environ.get("WORKBENCH_LLM_API_KEY"):
        return {"base_url": os.environ.get("WORKBENCH_LLM_BASE_URL", MIMO_BASE_URL),
                "api_key": os.environ["WORKBENCH_LLM_API_KEY"],
                "model": os.environ.get("WORKBENCH_LLM_MODEL", DEFAULT_MODEL)}
    return None


def _parse_env_file(path: Path) -> dict:
    cfg = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, _, v = line.partition("=")
            cfg[k.strip()] = v.strip().strip('"').strip("'")
    return cfg


class LoopbackHttp:
    """对壳自身 /t/{id}/api/ 的内部 HTTP 回环（G7：与外部路径完全一致）。"""

    def __init__(self):
        self.port: int | None = None

    def bind_port(self, port: int) -> None:
        self.port = port

    def __call__(self, method: str, path: str, body: dict | None = None) -> dict:
        if self.port is None:
            raise RuntimeError("LoopbackHttp 未绑定端口")
        url = f"http://127.0.0.1:{self.port}{path}"
        data = json.dumps(body).encode("utf-8") if body is not None else None
        req = urllib.request.Request(url, data=data, method=method,
                                     headers={"Content-Type": "application/json"} if data else {})
        with urllib.request.urlopen(req, timeout=60) as resp:
            return json.loads(resp.read().decode("utf-8"))


def build_service(root: Path, registry, backend=None) -> AssistantService:
    """装配助手服务；backend 可注入（测试），否则按 sidecar→直连→回放 自动探测。"""
    if backend is None:
        forced = os.environ.get("WORKBENCH_LLM_BACKEND", "auto")
        cfg = resolve_llm_config(root)
        sidecar_url = f"http://127.0.0.1:{SIDECAR_PORT}"
        use_sidecar = forced == "pi-sidecar" or (
            forced == "auto" and PiSidecarBackend.healthy(sidecar_url))
        if use_sidecar:
            backend = PiSidecarBackend(sidecar_url)
        elif forced == "echo" or (forced == "auto" and cfg is None):
            backend = EchoBackend(FIXTURES)
        elif cfg is not None:
            backend = OpenAiCompatBackend(cfg["base_url"], cfg["api_key"], cfg["model"])
        else:
            backend = EchoBackend(FIXTURES)
    svc = AssistantService(registry, backend, LoopbackHttp())
    svc.bind_port = svc.http.bind_port  # 壳绑定端口后通知回环
    return svc


def _sidecar_dir(root: Path) -> Path:
    # root 即仓库根（workbench/__main__.py 的 ROOT=parent.parent 已回根），sidecar 在根下
    return Path(root).resolve() / "assistant-sidecar"


def maybe_start_sidecar(root: Path) -> subprocess.Popen | None:
    """node 与构建产物可用则拉起 pi sidecar（G5）；返回 None 表示降级。"""
    sidecar_dir = _sidecar_dir(root)
    entry = sidecar_dir / "dist" / "server.js"
    if not entry.is_file() or shutil.which("node") is None:
        return None
    cfg = resolve_llm_config(Path(root).resolve()) or {}
    env = {**os.environ,
           "WORKBENCH_LLM_API_KEY": cfg.get("api_key", ""),
           "WORKBENCH_LLM_BASE_URL": cfg.get("base_url", MIMO_BASE_URL),
           "WORKBENCH_LLM_MODEL": cfg.get("model", DEFAULT_MODEL)}
    try:
        proc = subprocess.Popen(["node", str(entry)], cwd=sidecar_dir, env=env,
                                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except OSError:
        return None
    # 等 /health 就绪（最长 8 秒）
    import time
    for _ in range(16):
        if PiSidecarBackend.healthy(f"http://127.0.0.1:{SIDECAR_PORT}", timeout=0.5):
            return proc
        if proc.poll() is not None:
            return None
        time.sleep(0.5)
    proc.terminate()
    return None


SETUP_HINT = (
    "未配置 LLM 后端。任选其一：\n"
    "1) 写 workspace/assistant.env：WORKBENCH_LLM_API_KEY=...（可选 BASE_URL/MODEL）；\n"
    "2) 在 ZCode 配置小米 MIMO provider（自动复用其 key）；\n"
    "3) 启动 pi-agent sidecar（assistant-sidecar/，需 node）。\n"
    "未配置时助手以回放模式运行（合成响应，非真 LLM）。"
)


def handle_chat(service: AssistantService, payload: dict) -> tuple[int, dict]:
    """壳端点处理：返回 (status, body)。回环工具错误映射为结构化 502，不断连。"""
    try:
        return 200, service.chat(payload)
    except BackendUnavailable as exc:
        return 503, {"error": str(exc), "setup_hint": SETUP_HINT}
    except KeyError as exc:
        return 400, {"error": f"无效的 confirm call_id：{exc}"}
    except urllib.error.HTTPError as exc:
        return 502, {"error": f"工具执行失败：HTTP {exc.code}"}
    except urllib.error.URLError as exc:
        return 502, {"error": f"工具执行不可达：{exc.reason}"}
