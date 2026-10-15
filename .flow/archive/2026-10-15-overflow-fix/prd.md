# PRD：OverflowError 空洞修复

> 规格来源：`.flow/proposal.md`。红队：`.flow/red-team.md`（GO，3 准入全部采纳；含 10+ 字段崩溃面实测与桶界前提纠错）。

## Problem Statement

整数分/比率字段超出 float 可表示范围（>~1.8e308）时，`load_spec` 与 engine 的 float 强转抛 OverflowError（⊄ ValueError），route_post 外层捕获元组接不住 → 连接重置无响应。实证崩溃面不止提案的四条 int-cents 路径：`load_spec` 内 10 个 float 强转字段（conversion_rate、cost 七字段、reach_new、constraints）、`q_table[].q`、`new_basket[].weight`、`/api/import` 行内大整数同样断连。

## Solution

三层修复（红队准入①：层 3 为**必选主修复**，非防御性可选项）：

1. **`spec.py _int_cents`**：`abs(value) > sys.float_info.max` → `SpecError(f"{name} 超出可计算范围（|值| > {sys.float_info.max:.0e}）")`——篮子 amount/topup 的 choke point → load_spec 阶段 422"场景不合法"。
2. **`engine.py _validate_candidate`**：t/f 加同一上限 → SpecError（文案**原值插值，禁 float 除法**）→ 经 compare per-candidate catch 变 200 + coupon_legality 不可行行（与 F≥T 同语义；stress 静默丢弃该行——记行为说明）。**不 bump ENGINE_VERSION**（准入②）。
3. **`load_spec` 内部**：`except (TypeError, KeyError, ValueError)` 元组加 `OverflowError`，统一 `raise SpecError(f"场景结构不合法：{exc}") from exc`——10 个 float 强转字段归入"场景不合法"文案族（422 带前缀）。
4. **`coupon_tool/server.py route_post` 外层**：捕获元组加 `OverflowError` → 422"请求不合法：{exc}"——q_table.q / new_basket.weight / import 行 / breakeven 乘积 / 未来转换点的唯一覆盖。

## User Stories

1. As a 工作台用户，I want 任何超出 float 范围的输入得到明确 422/不可行行，so that 不再面对连接重置
2. As a 中文优先用户，I want 场景字段溢出报"场景不合法"（中文）而非英文内部异常文案，so that 错误可理解
3. As a 维护者，I want 指纹/顺序/NaN 三类门禁保持绿，so that 五阶段成果零回退

## Implementation Decisions

- 上界统一用 `sys.float_info.max`（int/float 比较精确安全；NaN 配方 2e306 天然在界内）。
- 响应形状三分（红队 K2 确认可接受并记录）：篮子 int-cents → 422"场景不合法"；候选 t/f → 200 不可行行；load_spec 比率/兜底路径 → 422（前者"场景不合法"、后者"请求不合法"）。
- 桶界不纳入（红队 K4：10³⁰⁹ 不炸，≥1.8e310 由层 4 覆盖）。
- CLI 已有 SpecError exit 2，无额外处理；已落盘的含巨大值 scenarios/*.json 在 CLI 下仍 traceback——记"限制"，不加码。

## Testing Decisions

- 回归矩阵（真 socket，追加到 `tests/test_coupon_server.py`）：四条原路径（threshold/basket amount/topup/new_basket amount → 422 或 200 不可行行）+ 红队准入①四条（conversion_rate → 422 场景不合法；q_table.q → 422 请求不合法；new_basket.weight → 422；/api/import 行 → 422）+ t=10**311 → **200 不可行行**（钉死文案不因 float 除法再炸）。
- 门禁不回退：`test_engine_fingerprint.py` 19/19、`test_compare_nan_output_rejected_as_422`、errors 顺序钉死、全量 pytest。

## Out of Scope

- 桶界 10³⁰⁹~1.8e310 区间的 limitation 滑稽长数字文案（不崩溃，红队 K4）
- 已落盘脏 scenario 文件的 CLI traceback
- workbench 壳/assistant（复用 route_post 与 HTTP 回环，自动覆盖）

## PRD diff gate（相对 proposal.md）

1. 层 3（route_post 兜底）从"belt-and-braces"升为**必选主修复**，新增层 3'（load_spec 内 OverflowError→SpecError 一行）——红队 K1/K2（崩溃面 3 倍低估）。
2. 回归矩阵从 4 条扩至 9 条（准入①）。
3. 桶界开放问题按实测关闭：不纳入，理由改写（红队 K4）。
4. 新增禁令：不 bump ENGINE_VERSION、新文案禁 float 除法（红队 K3）。

---

## GRILL 决议

### 第 1 轮（author-blind 子代理，2026-10-15，4 包全按 (A) 采纳）

- **Q1 文案统一只报界**：t/f 各一条——"门槛/面额超出可计算范围（约 1.8e308）"（不插值原值，避免 300 位数字串）；范围检查在各自 int 类型检查后、`f<=0` 前。层 1 同族。
- **Q2 断言深度**：状态码 + 关键子串（超出可计算范围/场景不合法/请求不合法）+ t=10**311 断言 200 且行内 coupon_legality；巨大候选显式带 label。
- **Q3 stress 丢弃行为说明**：写在 `stress.py` 模块 docstring（代码邻接）。
- **Q4 单提交**：三层修复 + 9 条矩阵 + route_post docstring 更新一个 `fix(coupon)` 提交（矩阵修复前必红，gate-first 会留红头）。
- **实现必做（griller 核实）**：两模块 `import sys`；范围检查在 bool/int 检查之后；route_post docstring 同步；红队归因小错修正（new_basket.weight 实崩于 spec.py:232 _check_new_basket，非 engine.py:328，终态同为层 4）。

### 第 2 轮（主代理）

零新增开放问题——**GRILL converged after 2 rounds**。
