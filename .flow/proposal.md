# 提案（讨论稿）：target-forecast 仓库重构 — 阶段5（收官批）

> 来源：2026-10-15 会话中基于 codebase-memory 图谱分析输出的重构方案 + 各阶段交接卡遗留清单。本 flow 执行**阶段5**——重构方案的最后一批。
> 阶段1（httpkit，5ed0651）、阶段2（pipeline，d58e3fc）、阶段3（coupon 路由表，1b51102）、阶段4（engine 拆分，97b8357）已完成推送，产物归档于 `.flow/archive/2026-10-15-stage{1..4}-*/`。

## 一句话目标

阶段5：完成剩余复杂度热点（spec._check_behavior 19/31、exports.export_markdown 15/31、assistant service._execute 11/15）+ P3 测试 helper 去重 + 三项历史遗留（NaN 负向测试、e_pi_after 死累加器删除、forecast server 无用 numpy 导入）。

## 任务清单（原方案阶段5 原文 + 交接卡遗留）

### A. 复杂度收尾（行为不变的重构）

1. **`coupon_tool/spec.py _check_behavior`（19/31）**：按校验主题拆成 `_check_reach / _check_q / _check_conversion` 等小函数；校验规则表驱动化可选（不必做）。
2. **`coupon_tool/exports.py export_markdown`（15/31，5 循环）**：按 sheet 拆 `_section_*` 渲染函数。
3. **`workbench/assistant/service.py _execute`（11/15）**：action 分发改表驱动。

### B. 历史遗留

4. **NaN 负向测试**（阶段1 遗留 S3）：构造 NaN 引擎输出 → coupon `/api/compare` 应回 422（deliberate-change #5 语义："请求不合法"）——补上当时未写的失败模式测试。
5. **`e_pi_after` 死累加器删除**（阶段4 红线保留项）：simulate 里只写不读的累加器（engine.py 三处），删除后**指纹门禁 19/19 必须仍绿**（输出不含它，删除是零漂移死代码清理）。
6. **`target_forecast/server.py` 无用 `import numpy`**（阶段2 遗留 S3）：存量无用导入，一行删除。

### C. P3 测试 helper 去重

7. **`tests/test_coupon_server.py` / `test_workbench.py` / `test_assistant_http.py` 的 `_post`/`_get`**（阶段1 SIMILAR_TO 证据）：提取到 `tests/conftest.py` 或共享模块。注意 test_coupon_server 的 `_get` 返回 bytes、test_workbench/_assistant_http 的返回 parsed JSON——签名差异需先统一或在提取时保留两种。

## 硬约束（不可推翻）

1. 不引入新依赖、不引入 Web 框架（既定）。
2. **A 组三个重构行为不变**：spec 校验的 errors/warnings 顺序不变（API 可见）；markdown 导出字节级不变（导出文件内容）；assistant action 分发语义不变。
3. **e_pi_after 删除后指纹门禁 19/19 逐 hash 相等**（阶段4 资产是安全网）。
4. 全程 `pytest` 保持绿；测试 helper 去重不改变任何测试的断言语义。
5. 保留用户已有改动（开工时工作区干净，baseline_dirty=[]）。

## 已拒绝的替代

- report.py 第三份 concat 收敛（阶段2 显式划出范围外，复杂度也不高，不做）。
- 校验规则全面表驱动化（spec）：原方案标注"可选（不必做）"，遵守。
- 顺手重构本批之外的热点（compare._check_constraints 10/12 等）：未列入，不动。

## 开放问题

- spec 校验拆分的函数边界（errors 与 warnings 在同一函数里混着 append？）。
- export_markdown 的 section 边界（按现有输出的段落标题切？）。
- assistant _execute 表驱动的表形状（action id → handler 的 dict？确认门/写操作的元数据怎么带）。
- 测试 helper 提取的落点（conftest.py fixture vs 纯函数模块 tests/_http.py）与 `_get` 两种返回类型的统一策略。
- NaN 负向测试的构造方式：从引擎哪条合法输入路径能产出 NaN/Inf 进 metrics？（若无此路径，测试应构造 mocked simulate 抛 ValueError 场景还是接受"不可达"结论并记录？）
