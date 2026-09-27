# Red-Team: 测算工作台 P2 — 投放 ROI 工具验证插件协议（底座零改动）

## Top Kill-Assumptions (ranked)

### K1 —「不改底座一行代码」与壳的既有行为自动兼容
- **Claim:** roi 工具只需引擎包 + plugin.py + static 前端 + 注册表一行，壳的导航/状态栏/深链/分发自动生效。
- **Steelman:** 协议字段（id/name/icon/handle_get/handle_post/seed_demo/actions）在 P0 设计、P1 状态栏（壳 fetch 工具 /api/state 的 demo_used）都是按「任意第三工具」语义实现的；demo_used 在 roi 的 /api/state 里给出即可自动显示演示标记。
- **Fails if:** roi 的某个合理需求落在协议外——如需要壳在导航分组、需要 query 之外的路径语义、需要 seed_demo 之外的启动钩子、或 iframe 内需要壳传参。任一出现即「协议漏需求」，P2 必须停下来补协议（这正是 P2 的目的，但补协议必须作为显式决策记录，不能悄悄改）。
- **Evidence（已取）:** workbench/registry.py 协议字段固定；workbench/server.py 分发纯前缀匹配、无工具类型特判；壳 app.js 对工具清单完全通用（P0 审查已确认）。
- **Kill criterion:** 实现中出现「workbench/ 必须改行为才能用」的时刻 → 停下，评估是协议缺口（补协议+记录）还是 roi 需求越界（砍需求）。
- **Cheapest test:** 切片 1 先写「底座零改动」守护测试：diff 检查 workbench/ 与两现有工具在 P2 全程不变（git diff --stat 基线对比）。

### K2 — ROI 模型简单到可用，而不是简单到被弃用
- **Claim:** 推荐基线（点击=消耗÷CPC，GMV=点击×CVR×客单，净毛利=GMV×(1−退款)×毛利率−消耗）是用户要的测算。
- **Steelman:** 线上零售投放核算的行业标准链路就是消耗→点击→订单→GMV→毛利；盈亏平衡 CVR 直接回答「这条计划值不值得投」；与 coupon 工具「允许不投成为结论」的哲学一致。
- **Fails if:** 用户实际想要的是更复杂的模型（复购 LTV、自然流量蚕食/增量归因、多触点）——MVP 交付后被认为玩具。
- **Kill criterion:** 用户在 PRD diff 门否定模型基线 → 先定模型再动工，这是本流程的第一个门。
- **Cheapest test:** PRD diff 门本身就是这个测试——用户在动工前看到完整公式。

### K3 —「底座零改动」与存量测试的硬冲突（已确证）
- **Claim:** P2 后存量测试仍全绿。
- **Steelman:** 引擎/协议/现有工具不动，绝大多数测试不受影响。
- **Fails if:** `tests/test_workbench.py::test_default_registry_builds_all_tools` 断言 `set(reg.ids()) == {"forecast", "coupon"}` 且名称集合相等——注册 roi 后**必然失败**。这不是回归，是产品正确性变化（工具变多），但按 P1 的「断言零修改」先例会被误判为破坏。
- **Evidence（已取）:** tests/test_workbench.py 中该测试精确断言两工具集合；shell 页导航/其他测试用包含式或动态断言不受影响。
- **Kill criterion:** 无——此冲突不可避免，必须在 PRD diff 门显式披露并获得确认：允许把该断言更新为「包含 forecast/coupon 且总数≥2」式的超集校验（唯一被允许的存量断言修改）。
- **Cheapest test:** 切片 1 先改这一处断言并跑全绿，其余断言冻结。

### K4 — 演示数据的合成标注惯例被遵守
- **Claim:** roi 演示计划集标注为合成假设。
- **Fails if:** 演示数被当成行业真值引用。coupon 已有 synthetic 标注惯例（README 与界面），roi 必须同等标注。
- **Cheapest test:** 静态断言演示响应带 synthetic 标记 + UI 常驻标注。

### K5 — 第三工具的工程量在 MVP 边界内不失控
- **Claim:** 引擎（纯函数）+ 单页前端 + plugin + 测试，一次 flow 内完成。
- **Fails if:** 前端仿 forecast 仪表盘全套（图表/Inspector/多视图）被搬过来——那超出 MVP。
- **Kill criterion:** 前端切片出现图表库/多视图架构 → 砍到「计划表 + 情景切换 + 参数侧栏 + 结果表」。
- **Cheapest test:** 切片拆解时前端范围写成显式清单。

## What's Well-Reasoned

- P2 把「协议验证」作为验收本质是对的：底座零改动不是洁癖，是迫使协议缺陷暴露的手段；K1 的 kill criterion 已把「补协议」路径显式化。
- 模型基线用行业 standard 链路，且 MVP 明确排除 LTV/增量归因——避免在验证协议的工具里埋产品深水区。
- K3 冲突在 ASSESS 阶段就被 grep 确证而非实现期爆雷，diff 门披露即可。

## What I Couldn't Assess

- 用户对 ROI 模型基线的真实期望（K2，只能靠 diff 门）。
- roi 工具未来是否要接真实消耗数据（影响是否预留导入接口）——MVP 不做，P3/后续再定。

**Verdict: GO** — K3 是唯一已确证的冲突且解法明确（披露+一处断言更新授权），K1/K2 各有显式门（K2=diff 门，K1=守护测试）。
