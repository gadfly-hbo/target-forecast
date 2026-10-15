# 提案（讨论稿）：target-forecast 仓库重构 — 阶段4

> 来源：2026-10-15 会话中基于 codebase-memory 图谱分析输出的重构方案。本 flow 只执行**阶段4**。
> 阶段1（httpkit，5ed0651）、阶段2（pipeline，d58e3fc）、阶段3（coupon 路由表，1b51102）已完成推送，产物归档于 `.flow/archive/2026-10-15-stage{1,2,3}-*/`。

## 一句话目标

阶段4：P2 拆分 `coupon_tool/engine.py` 的 `simulate`（圈复杂度 33 / 认知 54）——按既有注释边界提取私有函数，**只搬移不改算术**，数值输出逐位不变。

## 背景与证据（图谱复杂度 + 逐行读码确认）

`simulate` 是 220 行单函数，混了 6 件事：候选校验、逐篮子分支展开（子模型①②）、转化响应（子模型③）、账本汇总（子模型④）、局限提示收集（limitations）、贡献拆解（4.6 对平）。函数内已有清晰的子模型注释边界——拆分有现成的接缝。

拆分方案（原方案阶段4 原文）：

- `_validate_candidate(candidate)`——开头校验块（enabled/F/T 整数分检查）
- `_basket_branches(spec, bk, i, t, f)` → `(branches, loss_i, topup_at_threshold)`——子模型①②（自然命中三分支 / 凑单流失五分支）
- `_conversion_response(spec, c0, retention, enabled, limitations)` → `d_c_plus`——子模型③
- `_aggregate_ledger(ledger, ...)` → `metrics`——子模型④
- `_decompose(ledger, pi0_by_basket)` → `decomposition`——4.6
- `simulate` 变成 ~50 行编排；每步可被 `test_coupon_engine.py` 的既有对平断言（4.6 拆解与 ΔΠ 对平）验证

## 硬约束（不可推翻）

1. **只搬移、不改算术**：diff 只含代码移动（允许提取参数/返回值接线），任何一行金额/概率计算的运算符、常数、顺序不得变化。
2. `SimulationResult` 的字段与数值**逐位不变**——`test_coupon_engine.py` 的黄金数值（如 incremental_contribution_cents 876_987±100）与对平断言为安全网；导出文件（决策摘要/CSV/JSON）内容不变。
3. 不动引擎的公共 API：`simulate(spec, candidate)` 签名、`SimulationResult` dataclass 字段、模块级 `_q_i`/`_row`/`_variable_fee`/`_per_basket`/`_baseline_basket_rows` 不动或仅内部重排。
4. 不引入新依赖；全程 `pytest` 保持绿。
5. 保留用户已有改动（开工时工作区干净，baseline_dirty=[]）。

## 后续阶段（不在本 flow 范围，仅记录）

- 阶段5：P2 其余（spec._check_behavior 19/31、exports.export_markdown 15/31、assistant service._execute 11/15）+ P3 测试 helper 去重 + 阶段1 遗留的 NaN 负向测试

## 已拒绝的替代

- 顺手重构成类/管道结构：超出"搬移"范畴，风险不可控。
- 顺手修 limitations 收集的重复 append 模式：属行为面（输出顺序），不动。

## 开放问题

- limitations 列表在多个子步骤被 append（穿越粗桶提示在循环里、其余在汇总段）——提取的子函数以 `limitations: list` 传入就地 append，还是各自返回新列表再合并？（就地 append 最接近现状，输出顺序天然一致）
- `_basket_branches` 需要返回的附带状态较多（branches, loss_i, topup_at_threshold）——返回 tuple 还是小 dataclass？
- 子模型③ 的 `d_c_plus` 计算同时读 `limitations`（两个 append 点）——签名怎么带。
- 汇总段（子模型④ + 4.6）有大量闭包变量（pi0_by_basket、n_visitors、c0、k_cost、l_rate）——提取时参数列表会很长，是否接受。
