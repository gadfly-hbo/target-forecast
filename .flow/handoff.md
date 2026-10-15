# 交接卡：阶段4 engine.simulate 拆分（完成于 2026-10-15）

## 已完成

- 三提交序列（GRILL Q7）：`454c537` 指纹封存（对未重构引擎，出处可审计）→ `97b8357` 重构 → 本卡；均推 `origin/main`
- `coupon_tool/engine.py`：`simulate`（33/54）拆为五私有函数 + 编排；**数值逐位不变**——19 用例 sha256 指纹重构前后逐 hash 相等，独立审查在沙箱复现旧引擎再次证明
- 复杂度（**codebase-memory 图谱口径**；radon 口径 simulate=31/_aggregate_ledger=18，方向与幅度同）：simulate 15/19、五 helper 最大 `_validate_candidate` 6/10；≤10/15 目标未达——GRILL Q5 钉死"六 append 留 simulate"（PRD 决议优先于 tasks 数字），偏差公开记录
- 验证：全量 `pytest` 214 passed（195+19 指纹）；SHIP 前独立复跑通过
- REVIEW：**PASS 0 blocking**（fresh-context；含 AST multiset 语句级等价证明与 SANITY 守卫活性验证）；N1 生成器键名已修复

## 关键资产（后续阶段复用）

- `tests/test_engine_fingerprint.py`：任何触碰 engine 的改动都应先跑它（逐位门禁）；重封存配方在 `.flow/gen_fingerprint.py`（键名已对齐 battery，带 12/12 命中数断言）
- 红队突变方法论（MUT 注入 + 指纹比对）：评估"等价重构"验证充分性的可复用范式

## 开放依赖 / 下一批前置

- 阶段5（最后一批）：P2 其余——spec._check_behavior（19/31）、exports.export_markdown（15/31）、assistant service._execute（11/15）+ P3 测试 helper 去重 + 阶段1 遗留 NaN 负向测试 + e_pi_after 死累加器删除（本阶段按红线保留）

## 已知事实 / 技术债

- `retention`/`conv`/`h` 在 simulate 与 helper 各有一份轻度重复推导（冻结签名所迫，REVIEW N3；去重需重新封存指纹，留阶段5 若触碰）
- 指纹 hash 平台绑定：异机失败优先怀疑真实 FP 差异，可用生成器在重构前重封存

## 过程备注

- 本阶段子代理配额恢复，红队/GRILL 第1轮/REVIEW 三处均回到 fresh-context 模式（阶段3 的全程降级模式结束）
