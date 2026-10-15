# Red-Team: Path A 全托管迁移（runAgent + 代理 execute + 确认门改造）

> fresh-context 子代理（agent-52），2026-10-15。证据基：target-forecast 的 sidecar/service/backend/runtime/tools/fixtures/server.py/app.js/两测试文件/启动脚本；pi-agent-runtime@0.4.3（b07057f，dist 已构建）的 AGENT-RUNTIME.md/src/{index,types,pi-adapter,budget,testing}.ts/examples/offline.ts。注意：INTEGRATION.md 在该仓不存在。

## Verdict: **GO**（附 4 项先决条件）

### Kill-Assumptions（排序）

**1. 确认门三选一其实已被 SDK 源码裁决——(a) 结构性不可行，(c) 是标准认可的形态**
- (a)（authorize 长轮询）：Authorization 回调虽可阻塞（有限模式 controlled() 无逐调用截止，index.ts:86-89），但 run 级 `wallTimeMs` 在轮询期间持续计时（index.ts:157,173）；run 全程持有 BudgetStore lease（release 仅在 finally，index.ts:272-275），挂起的 run 让任务永久 TASK_BUSY（budget.ts:17）；致命伤：写意图在一次模型调用后才存在，同步 /chat 响应既不能等到用户确认再返回、又没有别的通道渲染确认 UI——(a) 偷偷需要 (b) 的前端轮询还叠加预算悬挂。且用户拒绝时 `status:'blocked'` 无文本载荷（types.ts:241-243），模型回复丢失。
- `shouldYield`/BUSINESS_WAIT **不是效果前门**：beforeToolCall 存 'tool-admitted' 检查点后放行执行（pi-adapter.ts:599-607），shouldYield 在 afterToolCall（:608-611）——工具已执行后才咨询。
- **(c) 不是"工具循环入 sidecar"的退让，而是 P1/P3 认可的形态**（AGENT-RUNTIME.md:25,63——效果控制在可信宿主，写效果前需用户授权，浏览器确认即 P3 授权）：读工具经代理真执行（循环真在 sidecar）；写提案是真实工具调用，其 execute() 只登记 pending 记录（良性、可授权的效果）并返回结果供模型推理；确认后的效果执行留在 Python（`_exec_*_set_*` 是多次 HTTP 舞步+中文摘要，(c) 原样复用，其他变体要 TS 移植或新端点）。
- SDK 还启用了第四选项：(c)-resume——blocked run 的 saveCheckpoint 已捕获 'tool-admitted' 检查点（pi-adapter.ts:574,666-667），确认后带 checkpoint 恢复可免模型调用重放提案并执行——同步前端下的 (b) 语义。
- **先决**：动工前在 (c)-simple 与 (c)-resume 之间拍板。

**2. taskId/BudgetStore 只有一条窄路**：模块级共享一个 `createMemoryBudgetStore` + 一个 AuditSink，跨所有 per-request createRuntime；进程生命期一个稳定 taskId；**显式 `cumulative:'unlimited'`**（P4，JuanerAI 先例）+ modelTimeoutMs/toolTimeoutMs/controlTimeoutMs/maxOutputTokens；整 run 界限由 sidecar 每请求 AbortSignal 提供（uncapped 模式故意无全 run 截止，AGENT-RUNTIME.md:84）。反例全部踩雷：稳定 taskId+有限 limits → activeMs 累计（budget.ts:52）本地助手永久 BUDGET_EXHAUSTED；per-request limits → CONFIGURATION_CHANGED（budget.ts:16，hash 覆盖工具**定义**，index.ts:158-161——定义必须字节稳定，execute 闭包不在 hash 内可 per-request）；默认 per-runtime store = "new Runtime 逃额度"反模式。

**3. ChatResult.tool_calls 语义分叉**：runAgent 下 sidecar 自己执行工具、RunResult 只回文本——sidecar 要自行重建 {reply, tool_calls}；若 pi 路径流经 service.py 同一 chat() 循环，sidecar 已登记的写会被 Python **二次登记**（重复确认提示/双重执行隐患）。Echo 路径要求循环保留（fixtures 驱动 tool_calls + {tool_result_summary}）。**先决**：ChatResult 加判别字段（如 already-orchestrated），Day 1 在类型上区分；工具摘要留侧（TS 移植 vs workbench 摘要端点）一并拍板。杀设计准则：单一无判别的 ChatResult.tool_calls 覆盖两后端 = 杀设计。

**4. MIMO system 通道战训必须显式延续**：SDK 下 BaseRequest.system 会走原生 system 通道（pi-adapter.ts:244-245）——正是 token-plan 端点忽略的通道；丢了指令集**所有合成测试照样绿**（fake transport 尊重 system）。钉死：sidecar 侧继续把 system 并入 prompt 首条 user；可选评估 thinkingProtocol:'mimo-chat'（0.4.2+）。

**5. 本机无 key——验证封顶于合成+构建+启动+503**：runtime.py:53-74 读 workspace/assistant.env → ~/.zcode/v2/* → 环境变量，三者皆空；启动脚本不装 key。真实冒烟要么问用户要 key 位置（注释暗示 mac mini 有 ~/.zcode/v2/provider_config.json），要么标"延期+用户签核"。缓解：node --test（Node 24 内建，零新依赖）+ SDK ./testing 假 transport 覆盖门变体/blocked 映射/无 key 503。

### Well-Reasoned

- 打包已验证：node v24.21.0 满足 engines；runtime 仓 0.4.3 干净且 dist 构建好；exports map + NodeNext 解析无碍；file: 路径为 `file:../../pi-agent-runtime`；无兄弟仓的机器降级 Echo 不破工作台（sidecar dist/node_modules 均本机构建）。
- 降级链构造性成立：maybe_start_sidecar 要求 dist/server.js；build_service 三级探测；503-no-key 在 /chat handler 里需重实现。
- **多轮历史轻量解**：无需 createSessionRuntime——AgentRequest.checkpoint.messages 是宿主持有的 ModelMessage[] 历史，driveCheckpoint 以其播种（pi-adapter.ts:592,666-667）；sidecar 可把历史作为不透明 checkpoint 令牌携带（或 Python 拍平进 prompt，同现状）。0.4.0 重契约（storage/acquireWriter/reconcile）买的是本产品不用的能力。
- per-request 工具实例合法：config hash 排除 execute（index.ts:33,161），闭包捕 workbench URL 可以，定义字节稳定即可。
- 审计设计相称：JSONL 同步 append 在 controlTimeoutMs 内；workspace/ 已 gitignore。
- 线程检查：ThreadingHTTPServer 下挂起的 chat 不会堵 confirm 端点——(a) 死于预算/UI 语义而非死锁。

### 未及评估

npm file: 在此 npm 版本下的 lockfile 行为（5 分钟实测：sidecar 内 `npm install && npm run build && node -e "import('pi-agent-runtime')..."`）；macbook 是否有 0.4.3 兄弟仓（file: 锁不住链接目录内容，"0.4.3 精确"实为"机器上是什么就是什么"）；真实 MIMO 在 SDK transport 下的行为（system 通道/reasoning_content，待 key）；harness 循环在 uncapped 下无内部轮数上限——sidecar AbortSignal 是唯一整 run 界限。

**GO 条件**：①动工前按证据拍板门变体（(c)-simple vs (c)-resume）；②钉 item-2 预算设计；③钉 item-3 ChatResult 判别；④显式延续 MIMO system 合并。最廉第一步：一个 node --test 合成脚本一次解决 item 1/2 与无 key 503，零新依赖。
