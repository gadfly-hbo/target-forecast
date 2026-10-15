# 任务清单：重构阶段1 — HTTP 基础设施收敛（httpkit）

> 来源：`.flow/prd.md`（含 GRILL 第 1 轮决议）。无 issue tracker，本文档即任务总线。
> 切片顺序 = 提交顺序 = 风险升序。每片完成后跑四文件回归套件。

- [x] 1. Characterization 测试钉住现状行为 — 证据：`pytest tests/test_httpkit_characterization.py` 8 passed in 7.76s（对未重构现状全绿）
- [x] 2. 新建 `tools_common/httpkit.py`（无调用方） — 证据：import 通过；回归 62 passed in 62.64s
- [x] 3. roi_tool server 切换 — 证据：51 passed in 58.88s（characterization + workbench + assistant_http；含 roi 422 守卫测试）
- [x] 4. coupon_tool server 切换 — 证据：15 passed in 8.30s（test_coupon_server + characterization 含子进程冒烟）
- [x] 5. target_forecast server 切换 — 证据：12 passed in 12.25s（test_server + characterization，deliberate-change #2/#3 断言翻转后绿）
- [x] 6. workbench 壳切换（仅 Responder/_json_bytes/_read_json_body） — 证据：51 passed in 58.02s（deliberate-change #1 翻转后绿）

---

## 1. Characterization 测试钉住现状行为

## What to build

新建 `tests/test_httpkit_characterization.py`，在任何重构动手前对**现状代码**跑绿，把红队盲区钉成断言：

1. 每 server 一个端点的 `Cache-Control: no-store` 响应头（coupon / roi 现状有；壳现状无——壳断言记录现状值，重构后按 deliberate-change #1 更新为"有"）
2. 独立 handler 的 404 体形状现状（forecast=text/plain，coupon/roi=JSON）
3. forecast 缺失静态文件的现状状态码（500）
4. demo 全流程响应可被 `json.dumps(..., allow_nan=False)` 序列化不抛（coupon compare / roi calc / forecast calc）
5. coupon 独立入口子进程冒烟：空闲端口 + `--port N --data-dir tmp`，cwd=tmp_path，轮询 `/api/state` ≤10s 后 terminate
6. import 守卫：`coupon_tool.server`/`roi_tool.server`/`target_forecast.server` 不 import `workbench.*`
7. roi 无独立测试文件——本文件自行在端口 0 启动 `roi_tool.server.make_handler(App(tmp_path))`

## Acceptance criteria

- [ ] 对未重构的现状代码全绿（除标注"重构后更新"的壳 no-store 条目用 xfail/skip 记录）
- [ ] 子进程冒烟测试 hermetic：不写仓库 workspace，不撞固定端口
- [ ] `pytest tests/test_httpkit_characterization.py` 独立可跑

## Blocked by

None - can start immediately

---

## 2. 新建 `tools_common/httpkit.py`（无调用方）

## What to build

新建顶层包 `tools_common/`（`__init__.py` 仅一行 docstring，不 re-export），`httpkit.py` 含五组件：

- `Responder(handler, static_dir: Path | None = None)`：send（带 `Cache-Control: no-store`）/ json（`ensure_ascii=False, allow_nan=False`）/ read_body / static（resolve + 前缀穿越检查 + is_file → 404 JSON；无条件 `; charset=utf-8`）
- `json_bytes(obj)`
- `make_dispatch_handler(handle_get, handle_post)`：安静模式 Handler，未命中回 JSON 404
- `serve_quiet(handler_factory, port, banner)`：bind 127.0.0.1，`try serve_forever / except KeyboardInterrupt: pass / finally server_close()`
- `AssistantParamsStore(path)`：load / save / `merge(section, patches) -> dict`（双 setdefault 形状）

## Acceptance criteria

- [ ] 五组件齐备，docstring 说明取自哪个现状实现（最严者）
- [ ] 任务 1 的测试仍全绿（本片不改任何行为）
- [ ] `python -c "import tools_common.httpkit"` 通过

## Blocked by

- 任务 1（characterization 先绿）

---

## 3. roi_tool server 切换

## What to build

`roi_tool/server.py` 删除本地 `_Responder`/`_json_bytes`，改用 httpkit；`make_handler(app=None)` 薄包装保留签名；`serve()` 改为调 `serve_quiet`（保留，标记半死）；assistant_params 改用 `AssistantParamsStore`，**未知计划名 422 守卫保留在路由层**。

## Acceptance criteria

- [ ] `test_roi_rejects_unknown_plan_name` 保持绿
- [ ] `pytest tests/test_workbench.py tests/test_assistant_http.py` 绿（roi 无独立套件，靠壳内挂载测试回归）
- [ ] 任务 1 的 roi 端点断言仍绿

## Blocked by

- 任务 2

---

## 4. coupon_tool server 切换

## What to build

`coupon_tool/server.py` 删除本地 `_Responder`/`_json_bytes`，改用 httpkit；`make_handler(app)` 薄包装保留；`serve()` 走 `serve_quiet`（banner 文案保留）；route_get/route_post 内部调用点替换，SpecError/422 语义不变（JSONDecodeError⊂ValueError 路径已确认）。

## Acceptance criteria

- [ ] `pytest tests/test_coupon_server.py` 绿
- [ ] 任务 1 的 coupon 断言（含子进程冒烟，走新 serve_quiet 路径）仍绿
- [ ] 响应行为除 deliberate-change 清单外零变化

## Blocked by

- 任务 3

---

## 5. target_forecast server 切换

## What to build

`target_forecast/server.py`：删除本地 `_Responder`；`/`、`/style.css`、`/app.js` 迁移到 `r.static(...)`（缺失文件 500→404，deliberate-change #3）；`/api/calc` 读体改走 `read_body()`（deliberate-change #4）；404 体 text/plain→JSON（deliberate-change #2）；xlsx/csv 导出分支保留 raw `r.send` 与平台名穿越防护；删除模块级 `load_assistant_params`/`save_assistant_params`，改用 `AssistantParamsStore`；`serve()` 薄包装保留 `state.load()` 预加载后调 `serve_quiet`，退出语删除（deliberate-change）。

## Acceptance criteria

- [ ] `pytest tests/test_server.py` 绿
- [ ] 任务 1 的 forecast 断言按 deliberate-change 清单更新后绿
- [ ] 手动 `main.py demo` 跑通（在 VERIFY 记录）

## Blocked by

- 任务 4

---

## 6. workbench 壳切换（仅 Responder/_json_bytes/_read_json_body）

## What to build

`workbench/server.py`：10 处 `_send` 调用点 + 3 处 `_json_bytes` + `_read_json_body` 改用 httpkit Responder/json_bytes；字节字面量错误体改 `Responder.json(...)`（输出逐字节相同）；壳所有响应获得 `Cache-Control: no-store`（deliberate-change #1）。**不改** `make_handler` 的注册表分发结构、`serve` 的 sidecar 生命周期、静态资源 ctype 映射。

## Acceptance criteria

- [ ] `pytest tests/test_workbench.py tests/test_assistant_http.py` 绿（含 `test_confirm_write_real_loopback` 落盘格式断言）
- [ ] 壳 diff 不含 assistant/sidecar 路径改动
- [ ] 任务 1 的壳 no-store 断言翻转为"有"后绿

## Blocked by

- 任务 5
