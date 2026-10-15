# 任务清单：重构阶段3 — coupon_tool server 路由表化

> 来源：`.flow/prd.md`（含 GRILL 决议）。无 issue tracker，本文档即任务总线。
> 硬要求：行为逐字节等价（零 deliberate-change）；characterization 先行。

- [x] 1. 补 8 条盲区 characterization（对现状先绿） — 证据：15 passed in 0.85s（8 新全绿；test8 用 balanced 缺 profit_scale 构造外层无前缀 422）
- [x] 2. route_post 路由表化（8 handler + _load_spec_or_422） — 证据：52 passed（test_coupon_server 15 + test_workbench + test_coupon_cli）
- [x] 3. route_get 两段式表化（GET_EXACT + GET_PATTERNS） — 证据：同上 52 passed（含 characterization 6/7）
- [x] 4. 复杂度复查 + 全量回归 — 证据：图谱实测 route_post 29/105→4/6、route_get 21/56→4/7、全部 handler ≤4/6（原目标 ≤15）；全量 195 passed in 102.40s

---

## 1. 补 8 条盲区 characterization（对现状先绿）

## What to build

追加到 `tests/test_coupon_server.py`（复用 base_url fixture），全部先对**现状代码**跑绿：

1. POST /api/demo 带 `data=b"not-json"` → 200（无预读怪癖）
2. POST /api/import buckets 模式 → 200，断言 issues/baskets 键结构
3. POST /api/import orders 模式 → 200
4. POST /api/decision 缺 run_id → 422；happy path → 200 {"saved": ...}
5. GET /api/review/list → 200 {"reviewed_runs": [...]}
6. GET /api/scenario/nonexistent → 404 且 error 文案 ≠ "not found"
7. GET /api/export/x/bogus → 404 {"error": "not found"}
8. POST /api/demo 场景 + 破坏候选（threshold_cents=100, face_value_cents=200）经 /api/compare → 422 且**无**"场景不合法"前缀（外层路径）

## Acceptance criteria

- [ ] 8 条对现状全绿（PRD Testing Decisions 全项）
- [ ] 不改任何生产代码

## Blocked by

None - can start immediately

---

## 2. route_post 路由表化（8 handler + _load_spec_or_422）

## What to build

`coupon_tool/server.py`：route_post 改为查 `POST_ROUTES` 分发；8 个 `_h_*` handler；`_load_spec_or_422(r, body) -> spec | None` 助手（仅 compare/stress/run 用）。纪律：dispatch 不预读 body；锁块随 handler 原样搬移；外层双 except 继续罩整个分发；review 的内层三异常 catch 留在其 handler；FileNotFoundError 不进外层。

## Acceptance criteria

- [ ] route_post 函数体只剩查表 + 外层异常包裹（≤ 20 行）
- [ ] `pytest tests/test_coupon_server.py` 全绿（含任务 1 的 8 条）
- [ ] route_get/route_post 签名不变，make_handler/plugin.py/serve 零改动

## Blocked by

- 任务 1

---

## 3. route_get 两段式表化（GET_EXACT + GET_PATTERNS）

## What to build

route_get 改为 `GET_EXACT`（7 条精确）+ `GET_PATTERNS`（3 条顺序正则：scenario/{id}、run/{id}、export/{id}/{kind}）两段分发；正则 handler 接 match 对象；各分支的锁/异常/404 语义原样搬移（export 不锁、scenario 404 带 store 文案、run 404 "run not found"、非法 kind 落未命中）。

## Acceptance criteria

- [ ] route_get 函数体只剩两段查表（≤ 20 行）
- [ ] characterization 6/7 与全部既有 GET 测试绿

## Blocked by

- 任务 2

---

## 4. 复杂度复查 + 全量回归

## What to build

1. codebase-memory 重新索引仓库，query_graph 复查 coupon_tool/server.py 各函数 cyclomatic/cognitive——route_post 拆分后不应再有 ≥15 的函数
2. 全量 `pytest`

## Acceptance criteria

- [ ] 图谱证实无 ≥15 复杂度残留（新 handler 全部个位数）
- [ ] 全量 pytest 绿
- [ ] 结果记录进 VERIFY 证据

## Blocked by

- 任务 3
