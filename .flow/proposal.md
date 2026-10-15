# 提案（讨论稿）：target-forecast 仓库重构 — 阶段2

> 来源：2026-10-15 会话中基于 codebase-memory 图谱分析输出的重构方案。本 flow 只执行**阶段2**。
> 阶段1（httpkit 收敛）已完成并推送（5ed0651），产物归档于 `.flow/archive/2026-10-15-stage1-httpkit/`。

## 一句话目标

阶段2：P0 target_forecast pipeline 收敛——消除 `main.py` 与 `target_forecast/server.py` 之间的业务逻辑双份（汇总/scan/load_cfg），两处调用方变成薄壳。

## 背景与证据（逐行比对确认）

`main.py`（CLI 入口）与 `target_forecast/server.py`（工作台 calc）维护着同一段业务逻辑的两份拷贝，改汇总口径要改两次，是真实的 bug 温床：

| 重复逻辑 | main.py | target_forecast/server.py |
|---|---|---|
| `load_cfg`（读 config.yaml） | `main.py:27-29` | `server.py:32-34`（`load_cfg(root)`） |
| 输入扫描（glob *.xlsx 排除 ~$） | `main.py:32-35` `_collect_inputs` | `server.py:37-40` `_scan`（被 `WorkbenchState.load` 用） |
| 模式A/B ingest+engine 循环 | `main.py:47-61`（run_flow 内联） | `server.py:65-77`（`WorkbenchState.load` 内联） |
| 三视角 concat + consolidate + platform_annual | `main.py:64-77` | `server.py:132-147`（`calc()` 内联） |

两者有一处**结构性差异**：main.py 的 results 含 `unified`（写中间指标 CSV 用），server 的 platforms dict 存 `unified`/`structure` 原始数据、`calc()` 时才算引擎——即 main.py 是"ingest+算+写盘"一次性流程，server 是"ingest 缓存 + 按需 calc"两段式。收敛方案必须容纳这两种用法。

## 阶段2 方案（原话收敛）

- 在 `target_forecast/aggregate.py`（或新 `pipeline.py`）提取：
  - `scan_inputs(root) -> (detail, agg)`
  - `run_platforms(detail, agg, cfg) -> results`（模式 A/B 的 ingest+engine 循环，main.py 和 `WorkbenchState.load` 共用）
  - `build_views(results) -> dict`（concat + consolidate + platform_annual + check/goods sheet）
- `main.py run_flow` 和 `server.calc` 都变成薄壳。注意保留 main.py 的进度打印（可传回调）。
- 验证：`pytest tests/test_core.py` + 手动 `main.py demo` 对比输出。

## 硬约束（不可推翻）

1. 不引入 Web 框架或非标准库依赖（沿用上一轮红队结论与 README）。
2. 不动三个引擎的数学公式（`.flow/archive/2026-09-27-assistant-p3/` 的 proposal 为规格来源）。
3. 全程 `pytest` 保持绿；行为（控制台输出、API 响应、落盘文件）除明确记录外零变化。
4. 保留用户已有改动（本次开工时工作区干净，baseline_dirty=[]）。
5. 阶段1 的 httpkit 成果（tools_common）不回退。

## 后续阶段（不在本 flow 范围，仅记录）

- 阶段3：P1 coupon server 路由表化（route_post 圈复杂度 29/认知 105）
- 阶段4：P2 coupon engine.simulate 拆分（33/54）
- 阶段5：P2 其余 + P3 测试 helper 去重

## 已拒绝的替代

- 把 server 改成调 main.py 的子进程：引入进程边界，违背本地一体化设计。
- 顺手重构 engine/aggregate 内部：超出阶段2范围。

## 开放问题

- 提取目标是放进现有 `aggregate.py` 还是新建 `pipeline.py`？（ingest 循环不算"aggregate"语义）
- server 两段式（缓存 ingest、按需 calc）与 main.py 一段式（ingest+算+写盘）的统一程度：`run_platforms` 返回到哪一层（unified/structure 还是算完的 results）？
- main.py 进度打印与警告捕获（`warnings.catch_warnings`）如何穿过共用层。
