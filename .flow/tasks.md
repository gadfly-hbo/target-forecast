# Tasks — 测算工作台整合 P2（投放 ROI 工具）

规格源：`.flow/prd.md`（含 GRILL 决议 G1-G7）。验收基线：`.venv/bin/python -m pytest tests -q`；存量断言冻结（K3 授权的唯一例外见切片 2）。

- [ ] 1. roi_tool 引擎纯函数 + 黄金案例测试
- [ ] 2. server/plugin + 注册 + 壳内冒烟
- [ ] 3. 前端单页 + 静态不变量 + README

---

## 1. roi_tool 引擎纯函数 + 黄金案例测试

**What to build:** `roi_tool/__init__.py`（ENGINE_VERSION）、`roi_tool/engine.py`：Plan 校验（422 式错误信息）、`evaluate(plans, scenarios)` 纯函数（clicks/orders/GMV/net/ROI/cvr_star/gap/verdict/below_breakeven，三档情景作用于 cvr 与 aov）、`roi_tool/demo.py` 内置四个合成计划（G1）。无 IO。

**Acceptance criteria:**
- [ ] 黄金案例：手工算定的正/负/边界三计划数值精确匹配（含 cvr_star 化简公式）
- [ ] 不变量：cvr = cvr_star 时 net ≈ 0（容差 1e-6）；情景单调性（挑战 net ≥ 基准 ≥ 保守）
- [ ] 校验矩阵：spend/cpc≤0、cvr/aov/margin/refund 越界 → 带字段名的错误
- [ ] tests/test_roi_engine.py 全部 tmp/纯内存

**Blocked by:** None - can start immediately

## 2. server/plugin + 注册 + 壳内冒烟

**What to build:** `roi_tool/server.py`（route_get/route_post 模式：/api/state 返回 G4 契约、/api/calc 调引擎、422/404 语义）、`roi_tool/plugin.py`（build_tool(root)，无持久化目录）、在 `workbench/server.py` 的 `build_default_registry` 登记（唯一底座接触点）、K3 授权的存量断言更新（tests/test_workbench.py:306,308 → 超集校验）、tests/test_roi_server.py 或 test_workbench 增补（壳内 /t/roi/ state + calc e2e + 422 + 404）。

**Acceptance criteria:**
- [ ] 壳内 /t/roi/api/state 200 且含 engine_version/synthetic/demo_used
- [ ] POST /t/roi/api/calc 返回四计划结果与汇总排名
- [ ] 不合法输入 422 带原因；未知路由 404
- [ ] K3 断言更新为「forecast/coupon/roi 都在」超集校验，其余存量断言零修改
- [ ] 守护：`git diff --stat <review_base> -- workbench/ target_forecast/ coupon_tool/` 仅注册表一行

**Blocked by:** 1

## 3. 前端单页 + 静态不变量 + README

**What to build:** `roi_tool/static/{index.html,style.css,app.js}`：顶部情景切换 + 计划结果表（verdict chip）+ 参数侧栏（六参数可调、增删计划、防抖重算）+ 合成假设常驻标注；Xanthil token；API 全相对路径。静态不变量测试（无根绝对 /api）+ 页面服务冒烟。README 底座章节补第三工具接入范例与 roi 简介。

**Acceptance criteria:**
- [ ] 壳内 /t/roi/ 页面 200，app.js/style.css 正常服务
- [ ] 静态扫描断言 roi_tool/static/*.js 无根绝对 /api 引用
- [ ] README 含「新增工具三步」（引擎包 → plugin.py → 注册）与合成假设说明
- [ ] e2e：壳起服务三工具导航齐全、?tool=roi 深链可用

**Blocked by:** 2
