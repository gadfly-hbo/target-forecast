# 提案（讨论稿）：(c)-resume 检查点重放——写确认后在授权循环内恢复执行

> 来源：Path A 迁移交接卡的第四项暂缓项，用户指令"第四项暂缓做掉"开专项 flow。
> 前置：Path A（c-simple）已全量落地并真实验证（`c6f2985..f9c34bc`，产物归档 `.flow/archive/2026-10-15-pathA/`）。

## 一句话目标

写操作确认后，通过 SDK 的**检查点恢复**在授权的 runAgent 循环内继续执行（免重新提案的模型调用、完整上下文续算），替代当前"Python 执行写 + 3 消息短 prompt 请模型措辞"的确认路径——同时保 Echo 回放双模与前端零改动。

## 现状（已验证的 (c)-simple）

- sidecar `/chat`：runAgent 托管循环；**写工具 execute() 只调壳 `/api/assistant/stage` 登记 pending**（良性效果），模型收到"已登记待确认"后组确认话术；run 正常结束，`orchestrated:true` 响应带 `stage_pending/call_id`
- Python `_confirm(call_id)`：**在 Python 侧执行真实写效果**（`_exec_*_set_*` 四段 HTTP 舞步 + 中文摘要）→ 组 3 消息（system+user+tool）→ `backend.chat` 请模型措辞 → 返回
- 确认门语义（P3）：写效果仅在用户确认后发生——已由 pytest（Echo 双登记防回归、写一次、call_id 一次性）+ 真实冒烟钉住

## 目标架构（Path A 红队对 (c)-resume 的裁定原话）

> "on an AUTHORITY_REQUIRED-blocked run, the sidecar's saveCheckpoint has captured a 'tool-admitted' checkpoint; resume with {checkpoint, no prompt} replays the proposed call without a model call and executes it once authorized — variant (b) semantics with a synchronous frontend. That's the only variant in which the write executes inside the loop without holding a run open across think-time."

要点：
1. **写工具授权拒绝 → blocked + 检查点**：sidecar 的 Authorization 对写工具返回 false → run 以 `AUTHORITY_REQUIRED` blocked 结束；`beforeToolCall` 已保存 'tool-admitted' 检查点（宿主 `saveCheckpoint` 回调捕获，pi-adapter.ts:599-607 证据）——**此机制的精确行为需本 flow 调查核实**（blocked 与 checkpoint 的先后、index.ts 的 authorize 时序、checkpoint 是否含待重放工具调用）
2. **/chat 响应携带检查点**：blocked 时响应含 `{blocked:true, checkpoint}`，Python `_relay_orchestrated` 把不透明 checkpoint 令牌存入 `_pending[call_id]["checkpoint"]`（服务端持有，前端零改动）
3. **确认即恢复**：`_confirm` 见 checkpoint → 调 sidecar 新端点 `/resume {checkpoint}` → SDK 以 `{checkpoint}` 重放工具调用（免模型调用）→ **写工具 execute() 此时代理壳新端点 `/api/assistant/exec_write`**（名门禁 x-write）执行真实写效果（复用 `_exec_*` 写执行器）→ 循环继续，模型以完整上下文措辞最终回复
4. **双模保留**：`_pending` 无 checkpoint（Echo/直连/旧 sidecar）→ 走现行 `_confirm` 路径——Echo 测试与降级链零改动
5. `runAgent` 基础路径是否支持 checkpoint 输入：types.ts `AgentRequest.checkpoint?: ConversationCheckpoint` 存在，index.ts 冻结请求时克隆 checkpoint——**无需 createSessionRuntime 0.4.0 重契约**（待调查确认 base 路径的 driveCheckpoint 可达性）

## 硬约束（不可推翻）

1. pi-agent-runtime 标准 v0.3 全规则；不修改 pi-agent-runtime 仓（只消费 0.4.3 公开面）。
2. **确认门语义不弱化**：写效果执行前必须有用户确认（确认即 P3 授权）；exec_write 端点名门禁（仅 x-write，且仅恢复路径可达——调查如何绑定 call_id 一次性）。
3. **Echo 双模与既有测试零改动**：`_confirm` 无 checkpoint 分支行为逐字节不变；`test_confirm_executes_write_once` 等 Echo 套件全绿。
4. 前端 app.js 零改动（pending_confirmation 形状不变，checkpoint 令牌留在服务端）。
5. 无新 Python 依赖；Node 零新增 dep；全量 pytest 绿 + node --test 绿。
6. 真实 MIMO 有界冒烟（key 已在 workspace/assistant.env）：写提案→blocked→确认→恢复→效果执行→完整上下文最终回复。

## 开放问题（调查重点）

1. **SDK 检查点机制实证**：authorize 拒绝的 blocked run 是否真的已通过 saveCheckpoint 落下 'tool-admitted' 检查点？checkpoint 的结构（ConversationCheckpoint 字段）能否序列化为不透明令牌往返（/chat 响应 → Python _pending → /resume 请求）？resume 是否真的免模型调用重放工具？
2. **execute 的两种身份**：同一写工具定义在 /chat（拒绝/stage）与 /resume（执行）下行为不同——per-request 工具构造如何携带"本次已授权 + call_id"？exec_write 如何校验 call_id 一次性（防重放）？
3. blocked 响应的模型文本：RunResult blocked 无文本载荷（types.ts:241-243）——确认话术由谁生成？（现状：stage 路径模型自己组"请确认"；blocked 路径是否退化为固定文案→前端确认框已有 preview 兜底，reply 可为固定提示）
4. shouldYield/BUSINESS_WAIT 替代路径：若 authorize-blocked 不带检查点，改用 shouldYield 后 stage→waiting+checkpoint 是否更贴合？（写工具 stage 后 yield，恢复时……但效果仍未发生——需调查两路取舍）
5. 确认后 sidecar 不可达（重启丢失内存态）：降级为现行 Python 执行路径？检查点令牌失效的兜底文案。
6. 多写提案（N1 修复后只透传首个）：恢复路径天然单写——其余取消语义保持。
