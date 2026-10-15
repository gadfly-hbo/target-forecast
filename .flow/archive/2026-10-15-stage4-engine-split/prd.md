# PRD：重构阶段4 — coupon engine.simulate 拆分

> 规格来源：`.flow/proposal.md`。红队报告：`.flow/red-team.md`（GO，fresh-context，含突变实验证据；三个开工前置条件全部采纳）。

## Problem Statement

`coupon_tool/engine.py` 的 `simulate`（圈复杂度 33 / 认知 54，~220 行）把候选校验、逐篮子分支展开、转化响应、账本汇总、limitations 收集、4.6 贡献拆解六件事混在一个函数里。红队突变实验证明：现有 68 条 coupon 测试对"提取 helper 后接线"最容易犯的三类错（limitations 顺序漂移、粘性标志丢失、浮点重聚合）**全部静默放行**——"只搬移"的纪律必须有指纹级门禁兜底。

## Solution

沿既有子模型注释边界提取五个私有函数，`simulate` 变成编排；重构前封存 19 用例的逐字段 sha256 指纹，重构后逐 hash 相等作为硬验收。

## User Stories

1. As a 维护者，I want 四个子模型各自是命名函数，so that 改动局部化、边界可审计
2. As a 审查者，I want 指纹门禁（19 用例逐 hash 相等），so that "只搬移不改算术"是可证伪断言
3. As a 运营用户，I want limitations 列表顺序逐位不变，so that 前端 warn-card 与导出摘要的提示顺序不漂移
4. As a 下游消费者（compare/stress/exports），I want `simulate`/`SimulationResult` 公共 API 与数值完全不变，so that 零适配

## Implementation Decisions

1. **五个私有函数**（签名按红队修正）：
   - `_validate_candidate(candidate) -> (enabled, t, f)`：保留 `f = candidate.get("face_value_cents", 0) or 0` 的 None→0 强转；保留"候选校验先于 `validate_spec(spec)`"的顺序（compare 的 per-candidate catch 依赖）
   - `_basket_branches(spec, bk, i, t, f, limitations) -> (branches, loss_i, topup_default_used)`：子模型①② + 桶穿 limitation append（就地，红队 K2/红线）
   - `_conversion_response(spec, t, f, c0, retention, enabled, limitations) -> d_c_plus`：子模型③（含 t/f，红队 K5）
   - `_aggregate_ledger(ledger, n_visitors, c0, e_pi0, l_rate, d_c_plus, k_cost) -> metrics`：子模型④（GRILL Q4 修正：k_cost 提升到 simulate 计算，签名去掉 enabled——metrics 段只在此处用它）
   - `_decompose(ledger, pi0_by_basket, k_cost) -> decomposition`：4.6（含 k_cost）
2. **接线红线**（红队条件③，写进提交说明）：
   - limitations 一律**就地 append 传引用**，禁止 helper 返回列表再合并
   - `topup_at_threshold` 为跨篮子粘性 OR：caller 侧 `topup_at_threshold = topup_at_threshold or topup_default_used`（或赋值语句原样留在循环内）
   - 禁止 `math.fsum` / 分组小计 / 任何 ledger 行序变化；每个累加器（e_pi0 / l_rate / e_pi_after / _sum / _delta_vs_pi0）的加法项序逐句保持
   - `e_pi_after` 是死累加器（只写不读）——**原样搬移保留**，删除留阶段5
3. **指纹门禁**（红队条件①）：重构前在本机生成 battery（黄金表 10 候选 + noN + c0zero + absbig + straddle+fees + 两个 mixed-topup + multinew + qtable + 桶穿+C₀=0 组合，共 19 用例），每用例序列化全量 `SimulationResult`（`json.dumps(..., sort_keys=True)`）取 sha256 封存；重构后逐 hash 相等。转正为 `tests/test_engine_fingerprint.py`（先例：阶段1 characterization），docstring 注明 hash 平台绑定（CPython/IEEE754 双精度下稳定；异机失败=真实 FP 差异信号，可重生成）。与红队基线的交叉核对：红队生成脚本未留存，12 个用例（黄金 10 + noN + c0zero）已实证可复现——对这 12 个断言 `hexdigest.startswith(红队16位)`；其余 7 个（multinew/qtable/absbig/straddle+fees/两个 mixed-topup/组合）fixture 参数不可考，红队旧 hash 仅作 docstring 历史参考，本机重新封存为准（GRILL Q1 修正——原"应逐一相同"条款不可满足）。
4. **零 deliberate-change**：`SimulationResult` 字段、metrics 键序、ledger 行序、limitations 顺序、导出文件内容全部逐位不变。
5. 模块级 `simulate`/`SimulationResult`/既有私有助手（`_q_i`/`_row`/`_variable_fee`/`_per_basket`/`_baseline_basket_rows`）不动。

## Testing Decisions

- **指纹测试先于重构落地并先绿**（对现状代码），重构后不变即绿。
- 回归：`pytest tests/test_coupon_engine.py tests/test_coupon_stress.py tests/test_coupon_compare.py tests/test_coupon_server.py`（server 含黄金数值 ±1 分与对平断言）
- 复杂度复查：图谱 query_graph，`simulate` 拆分后 ≤10/15（阶段3 先例），无 ≥15 残留
- 全量 `pytest` 195+19（指纹 parametrize 逐用例）条全绿

## Out of Scope

- `e_pi_after` 死累加器删除、limitations 重复 append 模式整理——阶段5
- spec/exports/assistant 的复杂度问题——阶段5
- compare.py 的候选级 SpecError 吞噬语义——现状保留

## PRD diff gate（相对 proposal.md 的差异）

proposal 硬约束全部保留。差异：

1. **开放问题 1 拍板**：limitations **就地 append 传引用**（helper 签名带 `limitations`），返回-合并方案否决。（红队 K2，MUT1 证据）
2. **开放问题 2 拍板**：`_basket_branches` 返回 **tuple** `(branches, loss_i, topup_default_used)`，不引入 dataclass。（最小 diff）
3. **开放问题 3 拍板**：子模型③ 签名带 `limitations` 就地 append，同时补 `t, f` 参数。（红队 K5 签名缺陷修正）
4. **开放问题 4 拍板**：`_aggregate_ledger` 接受长参数表（红队确认无碍）。
5. **新增**：指纹门禁（红队条件①，MUT 实验证实现有测试不充分）。
6. **新增**：接线红线清单与 `e_pi_after` 原样保留的决定（红队条件③）。
7. **修正**：提案称黄金数值"±100"——实为 ±1 分（TOL_CENTS=1），验证网比自述更强，但比特级缺口靠指纹补。

---

## GRILL 决议

### 第 1 轮（author-blind 子代理，2026-10-15，7 个已决问题包，含红队 hash 实证复现）

- **Q1 交叉核对条款修正**：红队生成脚本未留存——12 用例（黄金10+noN+c0zero）断言 `hexdigest[:16] == 红队值`（griller 已实证复现一致）；其余 7 用例本机重新封存，红队旧 hash 记 docstring 作历史参考。PRD 原文已改。
- **Q2 七个变体用例的 fixture 定义表**（记录在案的定义基准，每用例同时断言目标 limitation 文案在场，防退化 battery 静默封存）：
  - absbig：conversion={"mode":"absolute","delta_c_plus":0.95}（>上限触发 engine.py:212）
  - straddle+fees：篮子A=110 桶界 [10000,14000] + fixed_fee_cents=100/fee_rate=0.01/fixed_activity_cost_cents=50000
  - mixed-topup-0default：篮子1-4 topup_amount_cents=20000、篮子0 缺省，t=20000 全落②
  - mixed-topup-4default：篮子4 缺省其余显式（专打粘性 OR，MUT2 盲区）
  - multinew：默认相对转化 + 双条目 new_basket（权重 .6/.4）
  - qtable：q_mode=table + 2-3 行 q_table（gap_max/ftr_max）
  - 组合：c0=0.0 且 A=140 桶界 [13000,15000]（同时触发 :193 与 :218，MUT1 杀手）
- **Q3 指纹存储**：inline 字典字面量（先例 test_httpkit_characterization.py；tests/ 无 __init__.py 不可跨文件 import；不进 synthetic.py 扩公共面）；存完整 64 位 hexdigest；pytest parametrize 按用例名 → 19 个测试项。
- **Q4 签名再修正**：k_cost 计算提升到 simulate（条件常量纯搬移），`_aggregate_ledger(ledger, n_visitors, c0, e_pi0, l_rate, d_c_plus, k_cost)`，去掉 enabled。PRD 原文已改。
- **Q5 第六/第七块归属**：新增成交块（engine.py:220-231）与六个尾部 limitation append（:254-265）**原样留在 simulate**（读 caller 专属状态；保持现有相对位置即保序），不加第六个 helper。
- **Q6 闭包去向**：`_sum` 作为嵌套 def 随 `_aggregate_ledger`、`_delta_vs_pi0` 随 `_decompose`——逐字节搬移，不新增模块级名字。
- **Q7 提交粒度**：三提交——①`test(coupon): 指纹门禁封存`（对未重构代码绿，可审计"先封存"出处）②`refactor(coupon): simulate 拆五函数` ③`docs(flow): 阶段4交接卡`。
- **已钉死**：validation/vres 留 simulate；模块 docstring 不动；e_pi_after 保留/红线/19 用例成员/复杂度目标 ≤10/15；_basket_branches 可行（n_baskets 从 spec 可推导）。

### 第 2 轮（主代理）

枚举零新增开放问题——**GRILL converged after 2 rounds**。
