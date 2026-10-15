# 提案（讨论稿）：助手全托管迁移 pi-agent-runtime（Path A）

> 来源：2026-10-15 会话——用户问 pi-sdk 接入情况 → 调查发现 sidecar 直接 import `@earendil-works/pi-ai@0.86.1`（违反全局 AGENTS.md 的 pi-agent-runtime 接入标准规则 1）→ 用户指令"全部切换成 pi-agent-runtime" → 三路径分析 → **用户拍板 Path A 全托管迁移，走 /dev-flow 完整流程**。

## 一句话目标

`assistant-sidecar` 从直接 import pi-ai 改为完全构建于 `pi-agent-runtime@0.4.3`（本地 `~/Dev/Projects/pi-agent-runtime`，file: 链接）公开面之上：**工具循环移入 sidecar（`runAgent` + `execute()` 经 HTTP 代理回 workbench API）**，写操作确认门改造为符合标准 P3 的机制，产品代码零 pi-ai import。

## 调查证据（2026-10-15，已核实）

### 现状架构

- `assistant-sidecar/src/server.ts`（157 行）：`POST /chat` 收 OpenAI 格式 `{messages, tools}` → 转 pi Context（system 并入首条 user——MIMO token-plan 端点实测约束，server.ts:8-9）→ `streamSimple`（pi-ai/api/openai-completions）单次补全 → 返回 `{reply, tool_calls}` **提案**，不执行工具。
- `workbench/assistant/service.py`：Python 宿主执行工具——`chat()` 单次后端调用 → 读工具立即经 HTTP 回环执行（`_execute` + `_EXECUTORS` 表）→ **写工具（set_plan_params/set_scenario_params/modify_scenario）先返回 `pending_confirmation`（call_id+preview）→ 用户浏览器确认 → 下一轮 chat 确认执行**；工具结果摘要（中文）回灌模型。
- `backend.py`：`PiSidecarBackend`(8321 代理) / `OpenAiCompatBackend`(直连) / `EchoBackend`(回放，测试) 三链自动探测。
- 测试资产：`test_assistant_service.py`（Echo 驱动，钉确认门/写一次/回放语义，12+4 条）、`test_assistant_http.py`（真 socket 回环，含落盘断言）、`fixtures.py`。

### pi-agent-runtime@0.4.3 关键事实

- 公开面：`createRuntime`（五必要输入：Model+`createPiTransport`、Authorization、BudgetStore、AuditSink、Tools）、`runWorker/runText/runAgent`、`createSessionRuntime`（0.4.0 原生 Harness）、`./testing`（createRecorder/createReplay 合成回放）。
- `runAgent`：SDK 托管工具循环，Tool.execute 创建时固定；`RunResult<string>` 只回最终文本；Authorization 在**每次模型/工具效果前**回调；BudgetStore 同任务唯一 lease（内存版 `createMemoryBudgetStore` 可用）；AuditSink.append 须持久化确认（宿主责任）。
- 标准（docs/AGENT-RUNTIME.md v0.3）约束：产品代码禁止 import pi-ai/pi-agent-core；效果执行前授权（P3）；审计失败停止运行；真实 Provider 验证单独授权、有界进行（P6）。
- 包未发 npm：本仓库用 `file:../pi-agent-runtime` 链接 + 自有 lockfile 固定（标准规则 2）。

## 目标架构（Path A 骨架，细节留给红队/GRILL）

- sidecar `/chat` 内部改为 `createRuntime({...}).runAgent({taskId, prompt(含历史), tools, limits})`：
  - **读工具**（get_state/calc/list_runs/compare）：`execute()` 经 HTTP 代理到 workbench API（localhost），结果回模型继续循环
  - **写工具**：确认门机制待定（见开放问题 1）
  - Authorization：读放行、写按确认门策略
  - BudgetStore：`createMemoryBudgetStore`（sidecar 进程内）；AuditSink：JSONL 落盘 `workspace/assistant/audit.jsonl`（标准：持久化确认）
- Python `service.py` 职责收缩：传输层 + 确认门 UX + 工具结果摘要仍在哪一侧待定
- 依赖：`file:../pi-agent-runtime`（0.4.3 精确），移除 `@earendil-works/pi-ai` 直接依赖

## 硬约束（不可推翻）

1. 遵守 pi-agent-runtime 标准 v0.3 全部规则（五必要输入、P1-P6、效果前授权、审计持久化、失败停止）；**不修改 pi-agent-runtime 仓库**（只消费 0.4.3 公开面）。
2. 写操作确认门语义**不得弱化**：任何写效果执行前必须有有效用户确认（现状 pending_confirmation → confirm → 执行一次）。
3. 无 sidecar/无 key 时降级链（Echo 回放测试、503+配置指引）保持可用；`test_assistant_service` 的确认门/写一次/回放断言语义保持或显式迁移。
4. 无新增 Python 依赖；Node 侧仅 pi-agent-runtime（file:）+ 既有 devDeps；全程 `pytest` 绿。
5. 保留用户已有改动（开工时工作区干净，baseline_dirty=[]）。
6. 真实 Provider 冒烟按 P6 单独有界执行（需 WORKBENCH_LLM_API_KEY，见开放问题 6）。

## 开放问题

1. **确认门机制**（本 flow 核心设计决策）：
   - (a) Authorization 回调长轮询 workbench 确认状态（chat 请求悬挂至用户确认/超时）
   - (b) 异步作业模型：chat 启动 run 返回 job_id，前端轮询，确认后恢复——REST+前端改造最大
   - (c) 两阶段元工具：写操作建模为"提案工具"（execute 只注册 pending_confirmation 并返回"等待确认"，run 结束），用户确认后由 Python 走既有写执行器——最贴近现 UX，确认后效果仍在宿主
2. 历史上下文传递：runAgent 收 `prompt`（+system?）——多轮历史由 Python 拼进 prompt 还是侧car 维护（BaseRequest 字段待核）。
3. 工具结果中文摘要（现由 Python `_summarize_*` 生成）留在哪侧：execute() 返回原文 JSON 给模型 vs 代理层转换。
4. taskId 策略：标准要求稳定任务 ID（不可每请求随机）；sidecar 单用户本地场景的 taskId/budget 生命周期。
5. EchoBackend/ fixtures 与 runAgent 协议的兼容：service.py 的 chat() 签名与后端协议是否需要变（Echo 不经 sidecar，应零改动；PiSidecarBackend 协议可能变）。
6. 真实冒烟条件：`WORKBENCH_LLM_API_KEY` 是否已在启动脚本/环境（启动测算工作台.command）配置。
7. 超时/取消：现 sidecar TIMEOUT_MS 120s + Python 150s；runAgent 的 limits/AbortSignal 如何映射。
