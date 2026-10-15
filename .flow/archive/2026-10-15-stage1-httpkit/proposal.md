# 提案（讨论稿）：target-forecast 仓库重构 — 阶段1

> 来源：2026-10-15 会话中基于 codebase-memory 图谱分析输出的重构方案。本 flow 只执行**阶段1**。

## 一句话目标

阶段1：收敛 HTTP 基础设施四份拷贝——新建共享 httpkit 模块，4 个 server 切换使用，净删约 250 行重复代码。

## 背景与证据（图谱 + 逐行比对确认）

以下代码在 4 个 server 中逐字复制：

| 重复代码 | 出现位置 |
|---|---|
| `_Responder`（send/json/read_body/static） | `coupon_tool/server.py:60`、`target_forecast/server.py:168`、`roi_tool/server.py:28`，3 份几乎逐字相同 |
| `_json_bytes` | coupon / roi / workbench 各一份 |
| `make_handler` + `serve`（安静模式、KeyboardInterrupt 模板） | 4 个 server 各一份 |
| `assistant_params` 读写 | `target_forecast/server.py:197-207` 与 `roi_tool/server.py:85-94` 逻辑相同 |
| 静态文件服务 + MIME 猜测 | 4 处，且实现已轻微漂移（workbench 有路径穿越防护，工具端没有；forecast 的 `json()` 多了 `allow_nan=False`） |

## 阶段1 方案（原话收敛）

- 新建 `workbench/httpkit.py`（或 `tools_common/httpkit.py`，若要避免工具反向依赖 workbench），收敛为：
  - `Responder(handler)` 类：send / json / read_body / static（带穿越防护，统一 `allow_nan` 策略）
  - `make_dispatch_handler(routes_get, routes_post)` 工厂
  - `serve_quiet(app, port, banner)` 公共启动模板
  - `AssistantParamsStore(path)`：load/save/merge 一处实现
- 四个 server 改为 import 使用。
- 漂移点（穿越防护、`allow_nan`）取最严的实现为准。
- 预计净删 ~250 行。
- 验证：`pytest tests/test_server.py tests/test_coupon_server.py tests/test_workbench.py tests/test_assistant_http.py`。

## 硬约束（不可推翻）

1. **不引入 Web 框架**。`prd.md`（上一轮，已归档）与各模块 docstring 明确"无框架、离线可用、只用标准库"是既定设计决策（红队结论）。
2. **不动三个引擎的数学**（`coupon_tool/engine`、`target_forecast/engine`、`roi_tool/engine`）。
3. 每阶段独立成 PR/提交，全程 `pytest` 保持绿。
4. 保留用户已有改动（本次开工时工作区干净，baseline_dirty=[]）。

## 后续阶段（不在本 flow 范围，仅记录）

- 阶段2：P0 target_forecast pipeline 收敛（main.py 与 server.py 的汇总/scan/load_cfg 双份）
- 阶段3：P1 coupon server 路由表化（route_post 圈复杂度 29/认知 105）
- 阶段4：P2 engine.simulate 拆分（33/54）
- 阶段5：P2 其余 + P3 测试 helper 去重

## 已拒绝的替代

- 引入 Flask/FastAPI：违反约束 1。
- 为"未来工具"提前抽象插件协议：现有 Registry + manifest dict 够用。

## 开放问题

- httpkit 放 `workbench/` 还是新顶层包 `tools_common/`？（工具反向依赖 workbench 的接受度）
- forecast server 的 `_Responder` 无 `static()` 方法（它内联在 route_get 里）——收敛时以 coupon/roi 版本为准，需确认 forecast 的特殊分支（index.html 直读、xlsx/csv 下载）如何融入统一 Responder。
