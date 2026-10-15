# PRD：重构阶段3 — coupon_tool server 路由表化

> 规格来源：`.flow/proposal.md`。红队报告：`.flow/red-team.md`（GO，三个开工前条件；**内联降级模式**——子代理配额不可用）。

## Problem Statement

`coupon_tool/server.py` 的 `route_post`（圈复杂度 29 / 认知 105，全仓库最高）与 `route_get`（21/56）把 18 条路由内联在两个 if/elif 链里，混着重复骨架（3×`load_spec`+SpecError 422、3×缺参 422）、按路由不均质的异常处理与锁粒度。新增一条路由要在 60 行的链里找位置，异常语义靠缩进层级表达，无法一眼审计"哪条路由捕获什么异常、锁到哪里"。

## Solution

改为**两段式路由表**（精确匹配表 + 顺序正则表）+ 每路由一个 handler 函数；HTTP 行为零变化——路径、状态码、响应体（含错误文案）、锁粒度、异常吞噬范围逐条保持现状。

## User Stories

1. As a 维护者，I want 每条路由是一个命名函数，so that 新增路由不改动既有分支
2. As a 维护者，I want 异常→状态码→文案的映射按路由显式可见，so that "哪条路由吞什么异常"可审计
3. As a 维护者，I want 锁块与业务语句的绑定关系在重构后逐字节不变，so that run 路由的封存原子性不被破坏
4. As a 维护者，I want 复杂度显著下降（route_post 认知 105 → 各 handler 个位数），so that review 与定位成本下降
5. As a 审查者，I want 重构前补齐盲区 characterization 测试，so that "行为零变化"可证伪
6. As a 壳用户，I want route_get/route_post 的公开签名不变，so that plugin.py 与独立 make_handler 零改动

## Implementation Decisions

1. **两段式路由表**（红队条件③）：
   - `POST_ROUTES: dict[str, handler]`——8 条精确路由
   - GET 侧：`GET_EXACT: dict[str, handler]`（`/`、`/style.css`、`/app.js`、`/api/state`、`/api/review/list`、`/api/runs`、`/api/templates`）+ `GET_PATTERNS: list[tuple[compiled_regex, handler]]`（scenario/{id}、run/{id}、export/{id}/{kind}，**保持现状顺序**）
   - handler 签名：GET 为 `(app, r, path) -> None`（正则 handler 接收 match 对象：`(app, r, m) -> None`）；POST 为 `(app, r) -> None`——**body 由各 handler 自读**（红队条件②），无统一预读
   - `route_get`/`route_post` 保持现有签名 `(app, h, path) -> bool`，函数体变为查表分发；未命中返回 False
2. **异常包裹保持现状形状**：`route_post` 的外层 `except SpecError → 422 str(exc)` 与 `except (ValueError, KeyError, TypeError) → 422 "请求不合法：{exc}"` 继续罩住**整个 POST 分发**（含表查找后的 handler 调用）；compare/stress/run 的内层 `load_spec` 短路（422 + "场景不合法：{exc}" 前缀 + return）提取为 `_load_spec_or_422(r, body) -> spec | None` 私有助手，**仅用于这三条路由的 load_spec 处**；`/api/review` 的内层 `(ValueError, FileNotFoundError, SpecError)` catch 原样留在其 handler 内；FileNotFoundError 不进外层 catch。
3. **锁块随 handler 原样搬移**（红队 kill 准则 3）：demo 锁 save_spec、run 锁整个封存+导出、export 不锁、scenario/{id} 锁 load……逐路由与现状逐语句对齐。
4. **正则 handler 的 404 语义**：scenario/{id} 的 `(FileNotFoundError, SpecError) → 404 str(exc)`、run/{id} 的 `FileNotFoundError → 404 "run not found"`、export 的缺失文件 404 与非法 kind 不匹配（落到未命中 → make_dispatch_handler 404 "not found"）全部保持。
5. **不做**：不引入装饰器注册器、不动 make_handler/plugin.py/serve、不动响应体字段顺序、不改 `_Responder` 用法、不重构 spec/compare 等其他模块（阶段5 范围）。
6. **零 deliberate-change**：本阶段要求行为逐字节等价。

## Testing Decisions

- **动工前补盲区 characterization**（红队条件①，加进 `tests/test_coupon_server.py`，先对现状绿）：
  1. POST /api/demo 带 `b"not-json"` body → 200（无预读怪癖）
  2. /api/import buckets 模式 happy path → 200 issues/baskets 结构
  3. /api/import orders 模式（或非法 mode 回退 orders）→ 200
  4. POST /api/decision 缺 run_id → 422；happy path → 200 {"saved": ...}
  5. GET /api/review/list → 200 {"reviewed_runs": [...]}
  6. GET /api/scenario/nonexistent → 404 且 error 为 store/SpecError 文案（非 "not found"）
  7. GET /api/export/x/bogus → 404 {"error": "not found"}
  8. POST /api/compare 引擎深处 SpecError（如候选不合法）→ 422 无"场景不合法"前缀（外层路径）
- 回归：`pytest tests/test_coupon_server.py tests/test_coupon_cli.py` + 全量 `pytest`
- 完成后用图谱复查复杂度（route_post 拆分后各 handler 认知复杂度应全部 ≤ 15）

## Out of Scope

- coupon_tool 其他模块（spec/compare/exports/review/stress）——阶段4/5
- workbench 壳、roi/forecast server——阶段1 已收敛
- route_get 的静态三分支合并进 httpkit（现状即 r.static 调用，无收益）

## PRD diff gate（相对 proposal.md 的差异）

proposal 硬约束全部保留。差异点：

1. **开放问题 1 拍板**：正则路由用**有序正则表**（GET_PATTERNS），与精确表两段并存——非单一 dict（红队条件③）。
2. **开放问题 2 拍板**：GET 与 POST 两套 handler 签名；POST 为 `(app, r)`，**body 各 handler 自读**——非统一 `(app, r, body)`（红队发现 1：统一预读改 /api/demo 行为）。
3. **开放问题 3 拍板**：锁粒度**保持每路由现状**，统一提取方案否决（红队发现 3）。
4. **新增**：动工前补 8 条盲区 characterization（红队发现 5：/api/import 等零覆盖）。
5. **新增**：异常语义逐路由保持的显式清单（决策 2：外层罩分发、内层前缀短路仅限三路由、review 内层三异常、FileNotFoundError 不外抛吞噬）。

---

## GRILL 决议

### 第 1 轮（内联降级模式——子代理配额 403，2026-10-15，6 个已决问题包）

- **Q1 `_load_spec_or_422` 助手形态**：`(r, body) -> ScenarioSpec | None`——内层 try 捕 SpecError → `r.json({"error": f"场景不合法：{exc}"}, 422)` → 返回 None；compare/stress/run 三路由调用后 `if spec is None: return`。证据：server.py:169-175 现状短路形状。
- **Q2 表的位置与命名**：handler 私有名 `_h_<route>`（如 `_h_compare`）；`POST_ROUTES` / `GET_EXACT` / `GET_PATTERNS` 为模块级常量，定义在 handler 之后、route_get/route_post 之前；模块 docstring 补一行表结构说明。
- **Q3 characterization 8（外层无前缀 422）触发方式**：demo 场景 + 破坏一个 enabled 候选（`threshold_cents=100, face_value_cents=200`）——`load_spec` 的 `validate_spec` 只查 semantics/cost/behavior 不查候选（spec.py:223-233），候选合法性在 `engine.simulate`（engine.py:112-119）——故 load_spec 通过、compare 内 simulate 抛 SpecError → 外层 except → 422 `str(exc)` 无前缀。
- **Q4 characterization 落点**：追加到 `tests/test_coupon_server.py`（复用既有 base_url fixture），不新建文件。
- **Q5 GET 侧无外层 try**：现状 route_get 没有 broad except（与 POST 不同）——保持，不给 GET 加。
- **Q6 复杂度复查方式**：用 codebase-memory 图谱 query_graph 按文件过滤复查拆分后各 handler 的 cyclomatic/cognitive（阶段1 已验证该字段可用）。
- **无需提问已钉死**：route_get/route_post 签名冻结（plugin 依赖）；make_handler/serve 不动；错误响应体字段顺序不动。

### 第 2 轮（主代理）

枚举零新增开放问题——**GRILL converged after 2 rounds**。
