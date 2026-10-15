# 任务清单：OverflowError 空洞修复

> 来源：`.flow/prd.md`（含红队 3 准入 + GRILL 4 决议）。单提交（Q4-A）。

- [x] 1. 三层修复 + 9 条矩阵 + 全量回归 — 证据：矩阵 8 函数 9 用例全绿（含 10**311 不因除法再炸）；指纹 19/19；NaN/顺序门禁绿；全量 231 passed in 103.84s；ENGINE_VERSION=0.1.0 未变

## 1. 三层修复 + 9 条矩阵 + 全量回归

## What to build

层 1 `spec.py`：`import sys`；`_int_cents` 在 bool/int 检查后加 `abs(value) > sys.float_info.max` → SpecError（只报界"约 1.8e308"）；`load_spec` except 元组加 OverflowError。
层 2 `engine.py`：`import sys`；`_validate_candidate` 对 t/f 加同一上限（int 检查后、f<=0 前），不 bump ENGINE_VERSION。
层 3 `coupon_tool/server.py`：route_post 外层元组加 OverflowError + docstring 同步；`stress.py` docstring 加丢弃行为说明。
矩阵（`tests/test_coupon_server.py` 追加 9 条，真 socket，状态码+子串断言，巨大候选带显式 label）：threshold 10³⁰⁹（200+coupon_legality）、threshold 10³¹¹（同，钉文案不因除法再炸）、basket amount（422 场景不合法）、topup（同）、new_basket amount（422 请求不合法）、conversion_rate（422 场景不合法）、q_table.q（422 请求不合法）、new_basket weight（422 请求不合法）、/api/import 行（422 请求不合法）。

## Acceptance criteria

- [ ] 9 条矩阵全绿；指纹 19/19、NaN 门禁、顺序钉死不回退
- [ ] 全量 pytest 绿（223+9）
- [ ] ENGINE_VERSION 未变

## Blocked by

None - can start immediately
