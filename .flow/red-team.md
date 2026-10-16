# Red-Team: (c)-resume 检查点重放（fresh-context 子代理，2026-10-16，实证 T1-T7 脚本在 /tmp/rt-redteam/）

> 过程注记：红队子代理首次因 429 五小时配额中断，恢复后完成——非降级模式，为 fresh-context 标准红队。

## 实证结论（全部跑通 node --test）

| # | 提案依赖的机制 | 实测裁定 | 证据 |
|---|---|---|---|
| 1 | authorize 拒绝的 run 留下可恢复的 'tool-admitted' 检查点 | **半真——检查点存在但该状态不可恢复**。blocked run 结束为 `blocked/AUTHORITY_REQUIRED`；saveCheckpoint 依次收到 3 份：`ready`(含待执行工具调用、无结果) → `tool-admitted(inFlightToolId)` → `ready`(带 `toolFailed:true` 结果)。恢复用 'tool-admitted' → `failed/STATE_FAILED`；末份 toolFailed ready 同样 STATE_FAILED；**只有第一份 ready（pending 调用未确认）可恢复** | T1/T2/T2b/T3；validation.ts:119（tool-admitted 一律拒绝）、pi-adapter.ts:575（toolFailed 确认→STATE_FAILED）、index.ts:231（authorize 在 execute 前）、pi-adapter.ts:599-607（beforeToolCall 先存再执行——顺序与提案引用一致） |
| 2 | checkpoint 可作不透明 JSON 令牌往返；resume 免模型调用重放 | **真**。纯 JSON 深相等往返通过；恢复重放步零模型调用（pi-adapter.ts:627-631 直接复用 assistant 内容），随后恰 1 次模型调用措辞终稿；写工具以原始 args 恰好执行 1 次 | T1/T3 |
| 3 | base createRuntime().runAgent 支持 checkpoint（无需 0.4.0 session 契约） | **真**。pi-adapter.ts:160-162 按 `checkpoint||saveCheckpoint||shouldYield` 分派 driveCheckpoint，base 路径完全可达；index.ts:122 仅要求 validateCheckpoint 通过 | T3（全程未用 createSessionRuntime） |
| 4 | shouldYield/BUSINESS_WAIT 替代路径 | **不合身，关闭开放问题 4**。afterToolCall 在工具执行之后才 waiting——效果发生在等待前，无法实现"确认后才执行"；退化为 c-simple | 代码路径推断（无歧义） |

**实证硬约束（实现必须遵守）**：
- **R1** 恢复请求 `prompt` 必须为空串 `''`（非缺省）：pending + 非空 prompt → INVALID_REQUEST（pi-adapter.ts:574，T6）
- **R2** 带 checkpoint 必须同时带 saveCheckpoint 回调；`toolExecution:'parallel'` 禁用（validation.ts:79-80）
- **R3** checkpoint 无签名/完整性校验：手造同 taskId 的 ready 检查点（call_evil）被照单执行（T4）——validateCheckpoint 只查结构/taskId 匹配/调用-结果配对
- **R4** 同 taskId 恢复时 limits（或工具定义/model）任一字节不同 → CONFIGURATION_CHANGED（T5；budget.ts:16）；/chat→/resume 顺序不触发 TASK_BUSY；configuration digest 不含 execute 闭包与 system（index.ts:33,158-162）——两身份 execute 成立
- **R5** 多写重放：检查点里最后一条 assistant 的**所有**未确认调用都会重放执行（T7 两笔全执行）
- **R6** checkpoint ≤ 2MB（validation.ts:86）；messages 含全部历史与 exec_read 完整 result 载荷
- **R7** sidecar 重启：预算台账落盘且启动丢弃 owner、digest 为内容哈希——同 taskId 恢复不受预算阻碍；但内存检查点 stash 丢失 → Python 降级路径是必须项

## Top Kill-Assumptions

**A1（最高）**：按直觉 stash "tool-admitted 那份"或"最后一份"——恢复 100% 失败且形态为 STATE_FAILED 不易归因。修复：按"最后一条 assistant 有未确认 calls 且无 toolFailed 结果的**第一份 ready**"留存。
**A2**：/resume 若接受请求体 checkpoint blob——任何本机进程可用伪造 ready 检查点绕过 /stage 预览驱动任意写参数（preview 与实际 args 解耦）。修复：/resume 只带 call_id，sidecar 从自有 stash 取（Python 令牌仅作查询键）。
**A3**：多写整批重放——第二个写若因 call_id 已被弹出而报错：首个写已生效、run 以 TOOL_FAILED 收场（用户看到失败实际已写）。修复：/resume 构造 execute 时只给首个写绑 call_id，其余写闭包返回良性"已取消（请逐个确认）"结果。
**A4**：/resume "顺手"换 limits/裁剪 tools/write_actions 排序不一致 → CONFIGURATION_CHANGED 全挂。立为不变量 + 防回归断言。
**A5**：/resume 超时但 sidecar 已完成写 → Python 降级再执行一遍（幂等设值型双执行良性但须知）。降级判据=明确失败（连接拒绝/非 2xx）；超时保守返回错误不自动降级执行。

## 次级（实现清单）

- blocked 的 RunResult 无文本载荷 → 回复取检查点内 assistant 消息 text 前缀 + 固定确认文案，前端 preview 兜底
- **/chat blocked 必须以 200 携带 {blocked, proposal} 返回**——否则 PiSidecarBackend 把非 503 一律抛 BackendUnavailable（backend.py:85-86；现状 server.ts 会 502）
- 140s RUN_SIGNAL + toolTimeout 120s 罩住写舞步+终稿轮；舞步中途超时留"参数已存未重算"中间态（与现行失败面等价，降级路径可覆盖）
- 恢复 run 的审计含 tool.admitted/tool.finished 真实写记录——比今天（写在 Python、sidecar 审计不可见）更好
- "免模型调用"仅指重放步；终稿仍 1 次模型调用（与现行 3 消息 stub 调用数同），收益是完整上下文与审计语义，勿外推为 token 节省

## What's Well-Reasoned

- base 路径可达判断正确（不引入 0.4.0 重契约，T3 全链路）
- 两身份 execute 成立（digest 不含闭包；/chat 写闭包永不执行、/resume 闭包绑 call_id 代理 exec_write + 名门禁 + 一次性弹出，与 test_confirm_executes_write_once 同构）
- Echo 双模零改动可行（分支键 = _pending 条目有无 checkpoint 字段；Echo/直连测试构造均不含该键）
- 怀疑点选得准（开放问题 1/2/4 恰是三面承重墙）

## 未及评估

- MIMO 真身下恢复轮终稿措辞质量（mimo-chat thinking blocks 透传）——只能真实冒烟回答
- 长会话 checkpoint 逼近 2MB 的速度（exec_read result 全量进 messages）——超限表现为恢复失败，可加长度守卫降级
- 固定确认文案的体验裁定（产品决策，preview 已兜底）

## 裁定：GO

核心机制在 base 0.4.3 公开面实证走通（T3）；硬约束全部可满足。但提案第 1 要点按字面实现必死（A1），A2-A5 为四条强制修正：①stash 规则改"pending 未确认的第一份 ready"；②/resume 只按 call_id 查 sidecar 自有 stash；③多写批次非首个良性取消；④/chat 与 /resume 构造字节一致（不变量+测试）；⑤sidecar 不可达降级现行路径、超时不自动执行。
