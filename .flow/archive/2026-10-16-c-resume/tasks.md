# 任务清单：(c)-resume 检查点重放

> 来源：`.flow/prd.md`（红队 A1-A5/R1-R7 + GRILL 5 包决议）。三提交序（包 5）。

- [x] 1. sidecar — 证据：3fcabd4，node 12/12
- [x] 2. Python — 证据：d525b6e+6d87e4b（双弹出修复），pytest 241
- [x] 3. 冒烟+回归 — 证据：真链路完整通过（audit tool.finished 写记录+落盘 cvr=0.06+完整上下文终稿 44131.20 元）；全量 241 passed in 97.67s

## 验收要点

1. node：三份 saveCheckpoint 序断言、ready 恢复免模型重放+写恰一次、构造不一致 CONFIGURATION_CHANGED、双写批一执行一良性取消、伪造 blob 不被信任、blocked 200+stash、executed 标志；npm test 全绿（既有 502 用例翻转）。
2. pytest：exec_write 门禁/一次性；checkpoint_staged 分支；_confirm 四分支（成功透传/404 降级恰一次/executed:false 降级/executed:true 不执行/超时放回不执行）；Echo 套件零改动全绿。
3. 冒烟：完整链 + audit 含 tool.finished 写记录；全量 pytest 236+ 绿。

## Blocked by：1→2→3
