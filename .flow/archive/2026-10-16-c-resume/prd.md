# PRD：(c)-resume 检查点重放

> 规格源：`.flow/proposal.md`。红队：`.flow/red-team.md`（GO；实证 T1-T7 + A1 致命修正 + A2-A5 强制修正 + R1-R7 硬约束，全部采纳）。

## Solution（机制按红队实证修正）

### sidecar 侧（server.ts）

1. **写工具授权拒绝**：`createAssistant` 的 authorize 对 `kind:'tool' && effect==='write'` 返回 **false**（读/模型/发布放行）→ run 以 `blocked/AUTHORITY_REQUIRED` 结束（写效果永不发生在未确认 run 内，P3）。
2. **检查点 stash（A1 修正）**：`saveCheckpoint` 回调按规则留存——"最后一条 assistant 含未确认 calls 且无 toolFailed 结果的**第一份 ready**"（跳过 tool-admitted 与 toolFailed ready）；以 `call_id`（该未确认调用的 id）为键存模块级 stash（含 checkpoint JSON + 提案信息）。stash 上限与 checkpoint 2MB 守卫（R6）：超限不 stash，退化为 c-simple 响应。
3. **/chat blocked 响应改 200**（次级修正）：`{reply: 检查点 assistant text 前缀 + 固定确认文案, tool_calls:[{name,args,summary:"写提案待确认",stage_pending:true,call_id,preview?}], orchestrated:true, checkpoint_staged:true}`——preview 由 Python 侧 `_preview` 生成（现状 stage 端点职责并入：blocked 路径不调 /stage，Python 见 `checkpoint_staged` 直接用响应内 args 建 pending）。
4. **新端点 POST /resume {call_id}**（A2 修正）：**只收 call_id**，从自有 stash 取 checkpoint（不信任任何回传 blob）；弹出（一次性）。构造 runAgent：`{taskId: 与 /chat 同派生, prompt:'', checkpoint, tools: 同一定义集+同写名册, limits: 同一常量, saveCheckpoint: 同 stash 逻辑, signal: 140s}`（R1/R2/A4 不变量）。
5. **两身份 execute**：/chat 路径写闭包**永不执行**（authorize 先拒）；/resume 路径构造时：**首个未确认写**闭包代理壳新端点 `/api/assistant/exec_write`（带 call_id），**其余写**闭包返回良性工具结果"已取消（请逐个确认）"（A3/R5）；读工具闭包照旧代理 exec_read（重放批内可能含读）。
6. 响应：`{reply: 终稿, tool_calls: collect 透传, orchestrated:true}`。

### Python 侧

7. **`/api/assistant/exec_write` 端点**：`AssistantService.exec_write(call_id, name, args)`——名门禁（仅 x-write）；**call_id 一次性弹出 `_pending`** 后执行既有 `_exec_*` 写执行器（四段舞步+中文摘要原样复用），返回 `{summary, result}`。与 `_confirm` 的执行语义同构（写一次测试复用思路）。
8. **`_relay_orchestrated` 扩展**：见 `checkpoint_staged:true` 的 tool_call → 建 `_pending[call_id] = {name, args, checkpoint_key: call_id}`（不再调 /stage）；`pending_confirmation` 形状不变（前端零改动）。
9. **`_confirm` 双模分支（A5）**：条目含 `checkpoint_key` → 调 sidecar `POST /resume {call_id}`：成功 → 透传 `{reply, tool_calls}`（写已由 exec_write 执行）；**明确失败（连接拒绝/非 2xx/4xx stash 失效）→ 降级现行路径**（弹出 _pending + `_execute` + 3 消息措辞）；**超时不自动降级执行**（保守报错"恢复超时，请重试或检查参数是否已变更"）。条目无 checkpoint_key（Echo/直连）→ 现行路径逐字节不变。
10. **PiSidecarBackend**：`resume(call_id)` 方法（POST /resume，错误分类：连接错误/HTTPError→明确失败；timeout→超时类）。

## 硬约束（沿用 proposal 1-6 + 红队强制项）

A1 stash 规则 / A2 call_id-only / A3 多写良性取消 / A4 构造字节一致（不变量+防回归测试）/ R1 prompt:'' / R2 saveCheckpoint 同带、禁 parallel / R6 2MB 守卫 / A5 降级判据。Echo 套件与前端零改动；真实冒烟走完整链。

## Testing Decisions

- **node --test 移植红队 T1-T3/T5/T7 要点**：blocked+三份检查点序、ready 恢复免模型重放+写恰一次、构造不一致→CONFIGURATION_CHANGED 防回归、双写批次一执行一良性取消、伪造 blob 不被信任（/resume 只认 stash）。
- **pytest**：exec_write 名门禁+call_id 一次性；_relay_orchestrated 的 checkpoint_staged 分支；_confirm 双模（FakeSidecar 明确失败→降级恰一次；超时→不执行；成功→透传）；Echo 既有套件零改动绿。
- **真实 MIMO 有界冒烟**：写提案→blocked(200)→pending_confirmation→确认→/resume→exec_write 执行→落盘→完整上下文终稿；audit 含 tool.finished 写记录。

## Out of Scope

- createSessionRuntime/0.4.0 session 契约；checkpoint 持久化到磁盘（重启丢 stash→降级路径覆盖，红队 R7 接受）；固定确认文案的产品措辞打磨（preview 兜底）；长会话 2MB 逼近监控（守卫+降级已覆盖）

---

## GRILL 决议（第 1 轮 author-blind 5 包全采纳；第 2 轮零新增——converged）

- **代码已裁定开放点 5**：早前已确认的读**绝不重放**（pi-adapter.ts:569-577 `slice(0, assistantIndex)` 恢复为上下文；已确认结果经 observedTools→restoredResults 短路，execute 不触发）；与写同批未执行的读会在恢复时重新走 exec_read。
- **包 1 stash**：模块级 `Map<call_id,{checkpoint,createdAt,proposal}>`，call_id 由 sidecar `crypto.randomUUID().slice(0,12)` 新铸（非模型 id）；**覆盖语义**——saveCheckpoint 维护单一 candidate，每收到合格 ready（state==='ready' ∧ 最后一条 assistant 有未配对 calls ∧ 无 toolFailed）就覆盖（"只存第一份永不覆盖"在多批 run 会错存读批）；blocked 收场才落 Map。多写批只按首个未确认写建一条 stash + 只发一个 pending 条目（防 Python 多 pending→第二写降级真执行违背 A3）。上限 8 条 FIFO + 逐条 2MiB 守卫（validation.ts:86 对齐），超限不 stash、条目无 checkpoint_staged → Python 建**无** checkpoint_key pending = 退化 c-simple 的落地。随进程内存无 TTL（R7）。
- **包 2 blocked 响应**：200；`checkpoint_staged` 放 **tool_call 条目内**（ChatResult 零结构改动透传）；reply = 检查点内 assistant text 前缀 + "\n\n以上参数变更尚未生效，请在下方确认后执行，取消可放弃。"；preview 由 Python `_preview` 生成（args 已在响应内，同构 _stage_write）。
- **包 3 /resume 三路分类（收紧 A5）**：200→透传；404 stash-miss→明确失败降级；500 `{executed:false}`（CONFIGURATION_CHANGED/STATE_FAILED 等执行前失败，T5 证实零执行）→降级；500 `{executed:true}`（exec_write 已执行、终稿轮失败——真实可达）→**不降级**报"写入可能已执行，请检查当前参数"；超时→不执行且**把已弹出的 _pending 放回**（否则重试撞 KeyError，放回后重确认→404→降级，仍以新用户确认为前提）。sidecar exec_write 闭包返回后置 run 级 executed flag 随失败响应携带。backend.resume 返回 tagged（'ok'|'definite'|'timeout'|'maybe_executed'）；**TimeoutError 必须排在 Exception 前**（backend.py 现状吞一切）。
- **包 4 测试移植**：/tmp 脚本只作参考（绝对路径 import/globalThis 跨 test/绕过 sidecar 层三不可用）；移植进 assistant-sidecar/test/checkpoint.test.ts 沿用 scriptTransport+startShell（加 exec_write 记录器）+createAssistant 注入，单 test 串完整链；**既有"授权拒绝映射 502"测试断言翻转为 blocked 200**（node 侧允许改，Echo 零改动约束仅 pytest）。
- **包 5 提交序**：①sidecar（stash/blocked 200//resume + node 测试，自洽）②Python（exec_write/透传/双模降级 + pytest）③冒烟记录+归档；每个功能 commit 上 pytest 全量绿。
