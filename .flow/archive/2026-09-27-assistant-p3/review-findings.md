# Review Findings — 测算工作台 P3（REVIEW round 1）

Fresh-context reviewer verdict: **FAIL**（VERIFY 复跑一致 161 passed，但绿套件与两个阻断缺陷共存）。

## BLOCKER（本周期修复）

1. **forecast `_Responder` 缺 `read_body`** — assistant_params POST 在处理器内 AttributeError→500→回环断连，真实 confirm 路径必坏；测试未捕获因 service 用 FakeHttp、HTTP 测试明确跳过 confirm 步。修复：补 read_body + 真实回环 confirm 测试。
2. **sidecar 自动启动路径算错** — `Path(root).parent/"assistant-sidecar"` 指向仓库父目录，G5 自动拉起永不发生（手工 e2e 恰好掩盖）。修复：`root/"assistant-sidecar"`。

## SUGGESTION（本周期修复——正确性类）

3. 同轮写调用伴随其他 tool_calls 被静默丢弃 → staging 前先执行同轮只读调用并标注丢弃数。
4. roi 幻觉计划名无防御（盲合并且 `net=None` 崩溃）→ 服务端校验计划名 + 摘要兜底。
5. `handle_chat` 不捕获回环 HTTPError → 断连无响应体；映射结构化 502。
6. 取消的 confirm 永不清理（泄漏）→ 增加 cancel 路径（service+前端）。
7. roi `_assistant_params_path` 用模块相对路径（测试隔离隐患）→ 注入 root（App 化）。

## 记录不处理

- test_shell_assistant_panel 仍是字符串存在断言（确认门前端行为级测试缺位——HTTP seam 已覆盖 API 层）。
- 真实 LLM 会把情景键幻觉为 "baseline"（下游有兜底）；sidecar 无单测文件（转换器已对照 pi-ai 源码核验）。
- fixtures 实现为 .py 模块而非目录（PRD 文微偏差，功能等价，追认）。

## REVIEW round 2（2026-09-27）— PASS（APPROVE_WITH_COMMENTS）

Fresh-context reviewer verdict: **PASS**。Round-1 两阻断项独立复验确认修复（read_body + 真实回环 confirm 测试单跑 PASSED；sidecar 路径修复且实测自动启动 + 真 LLM 两轮 tool_call 闭环 32350.37）；全部建议项修复复验通过。

**round-2 建议（本轮已顺手修复）：** SIGTERM 孤儿 sidecar（serve 注册 SIGTERM→KeyboardInterrupt，实测 reap）；roi 死代码 shim 删除；同轮只读先执行 + dropped 计数与 net-None 兜底补回归测试；handle_chat 捕获 URLError。

**记录不处理：** 确认门前端行为级测试缺位（HTTP seam 已覆盖 API）；forecast 情景名不做服务端校验（幻觉名落盘为脏键，长期项）；sidecar 无独立单测（真链路实测替代）。
