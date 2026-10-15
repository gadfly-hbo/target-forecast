# 交接卡：阶段3 coupon server 路由表化（完成于 2026-10-15）

## 已完成

- 提交 `1b51102`（main → origin/main）：`coupon_tool/server.py` 路由表化——`POST_ROUTES`（8 handler）+ `GET_EXACT`/`GET_PATTERNS`（两段式）；`_load_spec_or_422` 仅限 compare/stress/run 三路由
- 复杂度：route_post 29/105 → **4/6**，route_get 21/56 → **4/7**，26 个函数最大 4/6
- 行为零变化：异常包络（前缀/无前缀/review 内层三异常）、锁粒度（demo/save-only、run 整块、export 无锁）、不预读 body、两种 404 体——全部由 8 条新增 characterization 钉住
- 验证：全量 `pytest` 195 passed（187 + 8 新）；SHIP 前独立复跑通过
- REVIEW：PASS 无 blocking（**全程降级模式**：子代理配额 403 未恢复，红队/GRILL 第1轮/REVIEW 三处均内联执行，已按规则记录并披露）

## 开放依赖 / 下一批前置

- 阶段4：P2 coupon engine.simulate 拆分（33/54；只搬移不改算术，test_coupon_engine 的对平断言为安全网）
- 阶段5：P2 其余（spec._check_behavior 19/31、exports.export_markdown 15/31、assistant service._execute 11/15）+ P3 测试 helper 去重
- 阶段1 遗留：NaN 负向测试（构造 NaN 引擎输出 → /api/compare 422）仍未补

## 已知事实 / 技术债

- "缺少 run_id" 422 在 _h_review/_h_decision 两处重复（REVIEW S1，judgement call 保留）
- GET 精确 handler 与正则 handler 双签名（REVIEW S2 保留；统一签名会把 m=None 渗进精确 handler）
- `/api/import` orders 模式的非法行编辑路径仍无 characterization（当前只测 happy path）

## 过程备注

- 本阶段子代理全程不可用（403 五小时窗口），三个 fresh-context 环节均按 dev-flow 规则降级内联并记录；下一批 flow 应优先恢复子代理模式
