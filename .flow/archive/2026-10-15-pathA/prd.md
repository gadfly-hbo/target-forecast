# PRD：Path A 助手全托管迁移 pi-agent-runtime

> 规格源：`.flow/proposal.md`。红队：`.flow/red-team.md`（GO，4 先决全采纳）。四先决在本文钉死；GRILL 只补残余开放面。

## Solution（架构钉死）

sidecar `/chat` 重写为 `pi-agent-runtime@0.4.3`（`file:../../pi-agent-runtime`）：

1. **运行时装配**（模块级单例）：共享 `createMemoryBudgetStore` + JSONL AuditSink（`workspace/assistant/audit.jsonl`，同步 append）+ 稳定 taskId（进程生命期，如 `workbench-assistant`）+ **`cumulative:'unlimited'`**（P4）+ modelTimeoutMs/toolTimeoutMs/controlTimeoutMs/maxOutputTokens；`createPiTransport`（openai-completions，MIMO env 三件套沿用 WORKBENCH_LLM_*）；per-request `createRuntime`（闭包捕 per-请求工具）。
2. **工具模型**（红队先决①，选 **(c)-simple**，(c)-resume 留增强）：
   - 读工具（get_state/calc/list_runs/compare…）：`execute()` HTTP 代理到 workbench API，原文 JSON 回模型（1 MiB 上限内）；中文摘要问题见开放面 1
   - 写工具（set_plan_params/set_scenario_params/modify_scenario）：`execute()` 只向 workbench `POST /api/assistant/stage`（新端点）登记 pending（良性效果，Authorization 放行），返回"已登记待确认"给模型；**确认后的效果执行留在 Python 既有 `_exec_*` 写执行器**（多次 HTTP 舞步+中文摘要原样复用）——P1/P3 认可形态，确认门 UX 零变化
   - 工具定义（name/description/parameters）从三工具 plugin manifest 生成且**字节稳定**；execute 闭包 per-request（hash 不含 execute）
3. **ChatResult 判别**（先决③）：`ChatResult` 加 `orchestrated: bool`（Echo=False 走既有循环；Pi 路径=True，service.py 不再执行/登记其 tool_calls，仅透传摘要给前端）；sidecar /chat 响应 `{reply, tool_calls:[{name,args,summary,stage_pending}], orchestrated:true}`——`stage_pending` 标记写提案已登记，前端确认流复用既有 pending_confirmation 渲染
4. **MIMO system 合并**（先决④）：sidecar 继续把 system 并入 prompt 首条 user（不用 BaseRequest.system）；thinkingProtocol 不启用（reasoning:false 现状）
5. **历史**：Python 拍平进 prompt（同现状语义），不用 checkpoint 播种（(c)-resume 启用时再引入）
6. **降级链**：无 key /chat→503（带指引文案）；无 node/dist→不启动 sidecar→直连/Echo 探测链不变；EchoBackend 与全部 service 测试零改动

## 硬约束（沿用 proposal 1-6）

标准 v0.3 全规则；不修改 pi-agent-runtime 仓；确认门语义不弱化（写效果前必须有用户确认）；无新 Python 依赖、Node 零新增 dep（node:test 内建）；pytest 全绿；真实冒烟按 P6——**key 已配置（见 Testing Decisions），真实冒烟按 P6 有界执行**。

## 开放面（GRILL 处理）

1. 工具结果中文摘要归属：execute() 回原文 JSON（模型自己消化，上下文膨胀）vs 代理层调 workbench 摘要端点（新端点 or 复用 assistant stage 响应）vs 摘要下沉到 stage/执行端点统一返回
2. `/api/assistant/stage` 端点形状：复用 service.py 现有 pending 登记（call_id/preview 生成）还是 sidecar 自带 call_id 透传
3. runAgent 的 prompt 组装：Python messages → prompt 的拍平格式（保历史语义，含 tool 结果回灌格式）
4. limits 数值与 AbortSignal 映射（TIMEOUT_MS 120s 沿用？controlTimeoutMs 取值）
5. node --test 合成测试的范围（门变体/blocked 映射/503/双登记防回归）与放置（assistant-sidecar/test/）
6. audit.jsonl 轮转/上限（长期运行膨胀）
7. 前端 app.js 需要的最小改动（orchestrated 响应的渲染路径确认）

## Testing Decisions

- **node --test 合成套件**（SDK ./testing 假 transport）：读工具代理循环、写工具 stage-不执行、Authorization 拒绝→blocked、无 key 503、双登记防回归（stub backend orchestrated=True 不触发 Python 循环）
- pytest：全部既有 assistant 测试零改动绿（Echo 不经 sidecar）；`test_assistant_http` 的回环落盘断言绿；全量 223+
- 构建/启动：`npm install && npm run build`（file: 依赖实测）；boot + /health + 无 key 503
- 真实冒烟：**已解除阻塞**——key 找到于 ~/.pi/agent/auth.json [xiaomi-token-plan-cn]（用户指引"从 pi-agent 里找"），已写 workspace/assistant.env（0600、gitignored）；按 P6 有界执行（一次读问题 + 一次写提案+确认链）

## Out of Scope

- (c)-resume checkpoint 重放（后续增强）；createSessionRuntime/原生 Harness；thinkingProtocol:'mimo-chat'；Echo 协议改动；pi-agent-runtime 仓任何修改

---

## GRILL 决议（第 1 轮 author-blind 子代理 6 包全按推荐采纳；第 2 轮零新增——converged after 2 rounds）

1. **读工具摘要**：新端点 `POST /api/assistant/exec_read {name,args}` → Python 复用 `AssistantService._execute`（含全部中文摘要）→ 返回 `{summary}`。唯一保行为等价选项；业务逻辑零 TS 移植；前端 `tc.summary` 保真。摘要有损为既有缺口（记后续增强：响应加 `result` 原文），不入本 diff。
2. **stage 端点 + orchestrated 回落**：`POST /api/assistant/stage {tool_id,name,args}` 复用 `_stage_write` 登记段（Python 生成 call_id/uuid + `_pending` + `_preview` 回环取旧值）→ 返回 `{call_id,action,args,preview}`；sidecar 写工具 execute() 返回 `{staged:true,call_id,preview}` 给模型。**双端点名门禁**：/stage 只收 x-write、/exec_read 只收非 x-write（击穿=违反确认门硬约束）。service.py 见 `stage_pending` 用自身 `_pending[call_id]` 重建 `pending_confirmation`（不二次登记）→ **app.js 零改动**（确认框只消费 pending_confirmation，app.js:128-141）。
3. **【阻塞前置】workbench URL 传递**：sidecar 现不知 workbench 地址且 `maybe_start_sidecar` 在 httpd 绑定前启动（server.py:100-107；测试 port 0）——调整 serve() 顺序：先建 httpd + `bind_port` 再拉 sidecar，env 传 `WORKBENCH_SHELL_URL=http://127.0.0.1:{port}`（maybe_start_sidecar 加参数）。
4. **prompt 拍平**：/chat 线协议不动（OpenAI 形 messages+tools）；**tool 定义保留 x-write 私有标志**发给 sidecar（映射 SDK `Tool.effect`）；拍平格式=「system 首段 + 角色行历史（用户：/助手：/工具 X 返回：…仅确认路径）+ 当前 user」；run 内多轮由 SDK 原生 toolResult 承载。
5. **limits 五元组**（uncapped 恰好五键，多则 INVALID_REQUEST）：modelTimeoutMs=120000 / toolTimeoutMs=120000 / controlTimeoutMs=10000 / maxOutputTokens=8192（**整 run 共享**——即新轮数界，MAX_ROUNDS=4 在 orchestrated 路径自然消失，语义变化明示）/ 整 run `AbortSignal.timeout(140000)`（< Python 150s socket）。**并发串行化**：sidecar 模块级 promise 队列（同 taskId lease 唯一，并发第二请求会 TASK_BUSY）。
6. **audit 轮转**：仅启动时检查 `workspace/assistant/audit.jsonl` >5MiB → 删旧 .1、改名留一（run 中绝不轮转——AUDIT_FAILED 杀 run）。
7. **测试缝**：server.ts 抽 `handleChat`/拍平/装配为可注入导出 + `if (process.argv[1] === fileURLToPath(import.meta.url))` 入口守卫（dist/server.js 仍为启动入口）；假 transport 用**手写脚本式**（./testing 的 replay 逐字节匹配 prompt 全文，格式一改全红——不用；SDK 示例先例 offline.ts，toolCall 用 kind:'tool'）；node --test 套件=PRD 五例+响应契约断言（orchestrated:true+summary 形状）；**双登记防回归放 pytest**（stub 后端 orchestrated=True → service.py 不调 _execute/_stage_write、响应含重建 pending_confirmation）。

UI-GATE skipped — 前端 app.js 零改动、确认 UX 逐字节保持（包 2 决议），无新用户可见 UI 面。
