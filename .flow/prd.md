# PRD — 测算工作台整合 P2：投放 ROI 测算工具（插件协议验证）

规格源优先级：`.flow/proposal.md`（P2）> P0/P1 继承约束 > 本 PRD > 实现建议。红队：`.flow/red-team.md`（GO，K1-K5；K3 已确证）。

## Problem Statement

工作台的插件协议（P0 设计、P1 加固）从未被第三个真实工具验证过。「新增测算工具不改底座一行代码」目前只是断言。需要一个真实业务工具——投放 ROI 测算——走通「引擎包 + plugin.py + static 前端 + 注册」全路径，暴露协议缺口（如有），并给用户一个可用的投放决策工具。

## Solution

新增 `roi_tool/` 包：纯函数测算引擎 + plugin.py 适配 + 单页前端，在 `workbench/server.py` 注册表登记（唯一允许的底座接触点）。工具回答：「每个投放计划预期赚不赚钱、ROI 多少、转化率至少要多少才保本、三档情景下结论稳不稳」。演示计划集内置合成数据（明确标注合成假设），无持久化、无导出端点、无数据导入。

## User Stories

1. 作为投放决策者，我想输入每个计划的消耗/CPC/转化率/客单/毛利率/退款率，看到预期 ROI 与净贡献，以便判断计划值不值得投。
2. 作为投放决策者，我想看到每个计划的盈亏平衡转化率，以便知道保底要求。
3. 作为投放决策者，我想切换保守/基准/挑战三档情景，以便检验结论对假设的敏感度。
4. 作为投放决策者，我想多计划并排比较并按净贡献排序，以便分配预算。
5. 作为投放决策者，我想「不值得投」成为明确结论而非被算法回避，以便止损。
6. 作为工作台使用者，我想壳导航自动出现「投放 ROI」并可深链 `?tool=roi`，以便与现有工具一致的进入方式。
7. 作为工作台使用者，我想演示数据有明确的合成假设标注，以便不误用。
8. 作为维护者，我想 P2 全程 `workbench/`、`target_forecast/`、`coupon_tool/` 零改动（K1 守护），以便验证插件协议完备。
9. 作为维护者，我想存量测试中唯一被修改的断言是两工具集合断言（K3 授权），其余全部冻结，以便确认无回归。
10. 作为维护者，我想 README 记录第三个工具的接入方式，以便未来第四个工具照做。

## Implementation Decisions

### D1 — 工具身份

- 包名 `roi_tool/`，tool_id `roi`，名称「投放 ROI」，icon 「📈」。注册进 `build_default_registry`。

### D2 — 引擎模型（基线，公式自解释）

每计划输入：`spend_cny`（消耗元）、`cpc_cny`（单次点击成本）、`cvr`（转化率 0-1）、`aov_cny`（客单价）、`gross_margin`（毛利率 0-1）、`refund_rate`（退款率 0-1）。

```
点击 clicks   = spend / cpc
订单 orders   = clicks × cvr
GMV           = orders × aov
净毛利 net    = GMV × (1 − refund_rate) × gross_margin − spend
ROI           = GMV / spend
盈亏平衡 CVR* = spend ÷ (spend/cpc × aov × (1−refund) × margin)
              = cpc × spend... 化简：CVR* = cpc / (aov × (1−refund_rate) × gross_margin)
```

- 情景（保守/基准/挑战）：对 `cvr` 与 `aov` 施加增速，其余参数平推；增速可配（默认 -20% / 0% / +20%）。
- 输出（每计划×情景）：clicks/orders/GMV/net/ROI/CVR*/结论（net>0 投 / 边界 / 不投）。
- 汇总：情景内合计 spend/GMV/net 与按 net 降序排名；跨情景结论稳定性（某计划在三档下结论是否一致）。
- 参数校验：spend>0、cpc>0、0<cvr<1、aov>0、0≤margin<1、0≤refund<1；不合法 → 422 带原因（coupon 模式）。
- 引擎为纯函数：`evaluate(plans, scenarios) -> result`，无 IO。

### D3 — 服务端与插件

- `roi_tool/server.py`：route_get/route_post 模式（复用 coupon/forecast 的结构惯例，代码独立书写）；`GET /api/state` 返回引擎版本、演示计划（若未自定义）、参数默认值、情景定义、`demo_used: true` 标记、`synthetic` 标注；`POST /api/calc` 接收 plans+scenario 调整 → evaluate → JSON；不合法输入 422。
- `roi_tool/plugin.py`：`build_tool(root)`，无持久化目录需求（不建 workspace/roi/，K5）；handle_get/handle_post 绑定。
- 无导出端点（无磁盘产物，P1 D4 约定）；无 runs 封存。

### D4 — 前端

单页（forecast 式，Xanthil token）：顶部情景切换（保守/基准/挑战）、主区计划结果表（spend/GMV/ROI/net/CVR*/结论 chip）、参数侧栏（每计划六参数可调，防抖重算）、演示标注常驻。无图表、无多视图（K5 守护）。API 全相对路径。

### D5 — 「底座零改动」守护（K1/K3）

- P2 全程 `workbench/`（除注册表登记一行）、`target_forecast/`、`coupon_tool/` 无行为改动；REVIEW 以 diff 复核。
- 存量测试唯一允许修改：`test_default_registry_builds_all_tools` 的两条精确集合断言 → 更新为「forecast/coupon 必在且总数≥3、名称对应」（K3 授权，diff 门确认）。其余断言冻结。

### D6 — README

底座章节补第三工具范例：新增工具三步（引擎包 → plugin.py → 注册表登记）+ roi 工具简介。

## Testing Decisions

- **主 seam：引擎纯函数**（tests/test_roi_engine.py）：黄金案例手工算定（一个正向计划、一个亏损计划、一个边界计划）；公式不变量（盈亏平衡 CVR* 下 net≈0）；情景单调性（挑战 net ≥ 基准 ≥ 保守）；校验 422 矩阵。
- **HTTP seam**（tests/test_workbench.py 增补或 tests/test_roi_server.py）：壳内 /t/roi/api/state、POST calc 端到端、422 路径、未知路由 404、静态页服务。
- **守护 seam**：底座零改动 diff 检查（REVIEW 复核 + 切片完成时人工 git diff --stat）；静态不变量（roi_tool/static 无根绝对 /api）。
- **回归 seam**：全部存量测试（含 K3 授权的一处断言更新）绿。

## Out of Scope

- LTV/复购归因、自然流量蚕食/增量测算、多触点模型（K2 显式排除）。
- 真实广告平台数据接入与导入。
- 持久化、运行封存、导出下载（无磁盘产物）。
- actions 填充、LLM 接入（P3）。
- forecast/coupon 的任何功能改动。

## GRILL 决议（自我拷问，2026-09-27）

约束：P2 proposal 与 P0/P1 继承决策不重新讨论；以下均为 PRD 未细化的开放点，按推荐自答，无升级项。

**G1 — 演示计划集内容（4 个合成计划）**：① 天猫直通车（搜索，高 CVR 稳赚）② 抖音千川（信息流，量大利薄、情景敏感）③ 京东快车（中规中矩、基准情景边界）④ 小红书聚光（高客单低 CVR、基准情景亏损但挑战转正——展示「结论随假设翻转」）。参数为合成假设，全响应带 `synthetic: true` 标注。

**G2 — 结论口径（引擎出事实，前端出 chip）**：引擎输出 net/ROI/cvr_star/gap（=cvr_star−cvr）与 `verdict`（net>0 → "净贡献为正"；否则 "净亏损"）+ `below_breakeven`（cvr<cvr_star）布尔。不做多档模糊评级（可投/观察/不投）——两档结论 + 事实字段足够，避免伪精确。

**G3 — 情景默认增速**：保守 −20% / 基准 0% / 挑战 +20%，作用于 cvr 与 aov，其余平推；前端可调三档各自的增速值（与 forecast Inspector 调参体验一致）。

**G4 — 引擎版本与契约**：`roi_tool/__init__.py` 暴露 `ENGINE_VERSION = "1.0"`；`/api/state` 返回 engine_version/演示 plans/参数默认值/情景定义/demo_used:true/synthetic 标注/boundary 本机运行声明（与 coupon state 契约同风格）。

**G5 — demo_used 语义**：roi 无持久化，每次 calc 的 plans 来自请求体，/api/state 返回的 plans 恒为内置演示集——demo_used 恒 true、界面常驻「合成假设」标注，壳状态栏自动显示演示标记（D5 机制，零底座改动）。

**G6 — 前端参数编辑**：每计划六参数全部可编辑（number input，防抖 400ms 重算），情景切换即时重算；支持增删计划（最小实现：添加空白计划、删除行）——回答「多计划比较」故事的基本需要，不做计划模板/复制。

**G7 — K1 守护的操作化**：每个切片完成后 `git diff --stat <review_base> -- workbench/ target_forecast/ coupon_tool/` 必须为空（注册表一行除外），REVIEW 复核同一命令。

## Further Notes

- 若实现中暴露协议缺口（K1），处理顺序：停下 → 判断缺口 or 需求越界 → 缺口则补协议（显式记录于 PRD/history）→ 继续。
- 演示计划集：3-4 个合成计划（如 天猫直通车/抖音千川/京东快车/小红书聚光 风格），参数为合成假设。
