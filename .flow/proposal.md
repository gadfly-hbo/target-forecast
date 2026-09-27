# Proposal — 测算工作台整合 P2：投放 ROI 测算工具（插件协议验证）

来源：2026-09-27 会话，用户指示「P2」。本文件为 P2 flow 的最高规格源。P0/P1 交付事实见 `.flow/archive/workbench-p{0,1}/`。

## 继承的 P2 定义（来自 P0 proposal 分期路线，不可推翻）

> P2：投放 ROI 测算验证插件协议（新工具不改底座一行代码）。

这带来 P2 的验收本质：**第三个工具必须只由「引擎包 + plugin.py manifest + 自己的 static 前端」构成，`workbench/` 底座、forecast/coupon 两工具零改动**（缺陷修复除外——若发现必须改底座，说明协议漏了需求，回头补协议并记录，这正是 P2 要暴露的）。

## 用户原始需求（本次会话逐字要点）

「P2」——即执行上述继承定义。ROI 测算的业务模型细节用户未指定，属于本 flow 要在 PRD diff 门呈现的推荐基线。

## 已有约束（P0/P1 沉淀，对 P2 有约束力）

- 插件协议：manifest 字段 id/name/icon/static_dir/seed_demo/actions=[]/handle_get/handle_post；路由函数收已剥离 `/t/{id}` 前缀的 path（保留 query）。
- 数据布局：`workspace/{tool_id}/`（P1）；目标测算数据在 `workspace/forecast/`，优惠券在 `workspace/coupon/`。
- 导出约定：`/t/{id}/api/export/...` 只服务已有磁盘产物（P1 D4）。
- 前端：API 全部相对路径，禁止根绝对 `/api` 引用（不变量测试）。
- 设计语言：工具内部视觉自治；壳按 Xanthil 基线。
- 注册：在 `workbench/server.py` 的 `build_default_registry` 登记（G4 显式清单）——这是唯一允许的"底座接触点"，登记一行不算改底座行为。
- 不过度设计（K5/G7）：不做当前工具不用的底座功能；actions 留空（P3 才填充）。

## 本 flow（P2）范围

### 推荐基线：投放 ROI 测算模型（业务细节 PRD diff 门确认）

- **对象**：多个投放计划（渠道/计划名），单计划独立核算 + 汇总比较。
- **输入参数**（每计划）：消耗（元）、CPC（元/点击）、转化率 CVR、客单价、毛利率、退款率。
- **测算链路**：点击 = 消耗 ÷ CPC；订单 = 点击 × CVR；GMV = 订单 × 客单；净毛利 = GMV × (1−退款率) × 毛利率 − 消耗；ROI = GMV ÷ 消耗。
- **三档情景**（与现有工具一致风格）：保守/基准/挑战，调 CVR 与客单增速（±），其余平推。
- **输出**：每计划 ROI / 净贡献 / 盈亏平衡 CVR（使净毛利=0 的 CVR）/ 是否达标；汇总合计与排序；「不值得投」允许成为结论（参照 coupon 决策层哲学）。
- **演示数据**：内置合成演示计划集（标注为合成假设），空数据自动播种。

### 明确不做（MVP 边界）

- 无持久化存储、无运行封存（coupon 的 runs/review 是 coupon 的深度，不是底座义务）。
- 无导出端点（无磁盘产物；P1 D4 约定只服务已有产物）。
- 不接真实广告平台数据（没有数据源；导入能力如有真实需求另立项）。
- actions 字段仍留空；不动 forecast/coupon/workbench 的任何代码与测试断言。

## 开放问题（留给 PRD/GRILL）

- ROI 模型参数与公式细节是否按推荐基线（diff 门确认）。
- 工具 id 与命名（推荐 `roi` / 「投放 ROI」）。
- 演示计划集的内容设计。
- 前端形态（参照 forecast 仪表盘 vs coupon 页签，推荐 forecast 式单页：计划表 + 情景切换 + 参数侧栏）。
