# 任务清单：重构阶段4 — coupon engine.simulate 拆分

> 来源：`.flow/prd.md`（含 GRILL 决议与两处修订）。无 issue tracker，本文档即任务总线。
> 硬要求：只搬移不改算术；指纹门禁先封存；19 用例逐 hash 相等。

- [x] 1. 指纹门禁封存 — 证据：19 passed in 0.05s（红队 12/12 前缀核对过；7 变体本机封存）；封存提交先于重构落地
- [x] 2. simulate 拆五函数（接线红线） — 证据：指纹 19/19 逐 hash 相等（零漂移）；coupon 回归 69 passed in 0.95s；simulate 33/54→15/19——≤10/15 目标未达，GRILL Q5（六 append 留 simulate，PRD 钉死）优先于 tasks 数字目标，偏差记录
- [x] 3. 复杂度复查 + 全量回归 — 证据：图谱实测 simulate 15/19、五 helper 最大 6/10（_validate_candidate）、无 >15；全量 214 passed in 100.15s（195+19）

---

## 1. 指纹门禁：test_engine_fingerprint.py 封存 19 用例（对现状先绿）

## What to build

新建 `tests/test_engine_fingerprint.py`：

- battery：黄金表 10 候选（复用 test_coupon_engine 的黄金场景）+ noN + c0zero + GRILL Q2 定义的 7 个变体（absbig / straddle+fees / mixed-topup-0default / mixed-topup-4default / multinew / qtable / 组合）
- 每用例：`simulate(spec, candidate)` → `dataclasses.asdict(result)`（含 engine_version）→ `json.dumps(sort_keys=True, ensure_ascii=False)` → sha256 完整 64 位 hexdigest
- 期望值：本机对**未重构代码**生成后 inline 封存；12 个可复现用例额外断言 `hexdigest[:16] == 红队值`（16634525229d2f2e 等，见 red-team.md）；7 个不可复现用例的红队旧 hash 记 docstring
- 每个变体用例同时断言目标 limitation 文案在场（构造健全性检查）
- docstring 注明平台绑定与再生成说明

## Acceptance criteria

- [ ] 对现状代码 19 项全绿（195+19 中先跑此文件）
- [ ] 12 个红队交叉核对断言全过
- [ ] 不改任何生产代码

## Blocked by

None - can start immediately

---

## 2. simulate 拆五函数（接线红线）

## What to build

`coupon_tool/engine.py`：按 PRD 决策 1（修订后签名）提取：

- `_validate_candidate(candidate) -> (enabled, t, f)`
- `_basket_branches(spec, bk, i, t, f, limitations) -> (branches, loss_i, topup_default_used)`（桶穿 append 就地）
- `_conversion_response(spec, t, f, c0, retention, enabled, limitations) -> d_c_plus`
- `_aggregate_ledger(ledger, n_visitors, c0, e_pi0, l_rate, d_c_plus, k_cost) -> metrics`（嵌套 _sum）
- `_decompose(ledger, pi0_by_basket, k_cost) -> decomposition`（嵌套 _delta_vs_pi0）

红线：limitations 就地 append；粘性 OR 在 caller；禁 fsum/分组求和/ledger 重排；e_pi_after 原样搬；新增成交块与六个尾部 append 留 simulate；validation/vres 留 simulate；模块 docstring 不动。

## Acceptance criteria

- [ ] 指纹 19 项逐 hash 相等（零漂移）
- [ ] `pytest tests/test_coupon_engine.py tests/test_coupon_stress.py tests/test_coupon_compare.py tests/test_coupon_server.py` 全绿
- [ ] simulate 变编排（目标 ≤10/15）

## Blocked by

- 任务 1

---

## 3. 复杂度复查 + 全量回归

## What to build

1. 图谱 query_graph 复查 engine.py 各函数复杂度（simulate ≤10/15，无 ≥15 残留）
2. 全量 `pytest`（195+19）
3. 三提交序列：①test 封存（先）②refactor ③handoff（SHIP 阶段执行）

## Acceptance criteria

- [ ] 图谱证实复杂度目标
- [ ] 全量 pytest 绿（195+19=214 项）
- [ ] 结果记录进 VERIFY 证据

## Blocked by

- 任务 2
