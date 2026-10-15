# 提案（讨论稿）：target-forecast 仓库重构 — 阶段3

> 来源：2026-10-15 会话中基于 codebase-memory 图谱分析输出的重构方案。本 flow 只执行**阶段3**。
> 阶段1（httpkit 收敛，5ed0651）、阶段2（pipeline 收敛，d58e3fc）已完成推送，产物归档于 `.flow/archive/2026-10-15-stage{1,2}-*/`。

## 一句话目标

阶段3：P1 coupon_tool server 路由表化——`route_post`（圈复杂度 29 / 认知复杂度 105，全仓库最高）与 `route_get`（21/56）改为路由表分发 + 每路由一个 handler 函数，行为不变。

## 背景与证据（图谱复杂度 + 逐行读码确认）

`coupon_tool/server.py` 的 route_post 是全仓库复杂度最高的函数。问题不止长，而是有明确的重复骨架：

- `load_spec` + `SpecError→422` 出现 3 次（compare / stress / run）
- "缺参数→422" 出现 3 次（review 的 run_id 检查、decision 的 run_id 检查等）
- 8 个 POST 路由分支 + 2 个 GET 正则路由全部内联在一个 if/elif 链里
- `with app.lock` 粒度不一（demo 只包 save_spec，run 包住整个封存+导出）

## 阶段3 方案（原话收敛）

- 改为路由表 + 每路由一个 handler 函数：

  ```python
  def _h_compare(app, r, body): ...
  def _h_run(app, r, body): ...
  POST_ROUTES = {"/api/compare": _h_compare, "/api/run": _h_run, ...}
  ```

- 公共的 `load_spec_or_422` 提取一次。`route_get`（21/56）同样处理。
- 这是纯机械重构，行为不变，现有 `test_coupon_server.py` 全覆盖。
- 验证：`pytest tests/test_coupon_server.py`。

## 硬约束（不可推翻）

1. 不引入 Web 框架或非标准库依赖（沿用既定红队结论与 README）。
2. 不动 coupon 引擎的数学公式（`.flow/archive/2026-09-27-assistant-p3/proposal.md` 为规格来源）。
3. 全程 `pytest` 保持绿；**HTTP 行为零变化**（路径、状态码、响应体、锁粒度语义）。
4. 保留用户已有改动（本次开工时工作区干净，baseline_dirty=[]）。
5. 阶段1/2 成果（tools_common/httpkit、target_forecast/pipeline）不回退；coupon server 已切换到 httpkit 的事实保持。

## 后续阶段（不在本 flow 范围，仅记录）

- 阶段4：P2 coupon engine.simulate 拆分（33/54；只搬移不改算术）
- 阶段5：P2 其余（spec._check_behavior 19/31、exports.export_markdown 15/31、assistant service._execute 11/15）+ P3 测试 helper 去重

## 已拒绝的替代

- 引入 Flask/FastAPI 路由装饰器：违反约束 1。
- 顺手重构 coupon_tool 其他模块（spec/compare/exports）：超出阶段3范围，留阶段5。

## 开放问题

- 路由表键是否含 GET 的正则路由（`/api/scenario/{id}`、`/api/run/{id}`、`/api/export/{id}/{kind}`）——正则路由通常需要单独的匹配层，是否值得表化？
- handler 签名统一为 `(app, r, body) -> bool` 还是 GET/POST 分开两套签名？
- `with app.lock` 的粒度：保持每路由现状（最保守）还是统一提取（属行为变化风险）？
- 壳插件（plugin.py 的 handle_get/handle_post 闭包）与独立 make_handler 是否受影响（预期不受——route_get/route_post 签名不变）。
