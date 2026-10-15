# PRD：重构阶段1 — HTTP 基础设施收敛（httpkit）

> 规格来源：`.flow/proposal.md`（2026-10-15 重构方案的阶段1）。红队报告：`.flow/red-team.md`（GO，有条件）。

## Problem Statement

仓库内 4 个基于标准库 `http.server` 的 server（coupon_tool / target_forecast / roi_tool 三个工具 + workbench 壳）各自拷贝了同一套 HTTP 管道代码（`_Responder`、`_json_bytes`、`make_handler`/`serve` 模板、assistant_params 读写、静态文件服务）。拷贝已经开始各自漂移：

- forecast 的 `json()` 独有 `allow_nan=False`，coupon/roi 没有——同一工作台三种 NaN 行为
- 壳 `_send` 缺 `Cache-Control: no-store`，工具端有
- 路径穿越防护只有壳有，工具端没有
- forecast 缺失静态文件走 broad except 回 500，coupon/roi 回 404
- forecast `/api/calc` 内联读 body，绕过 `read_body()`，是第三份读体实现
- roi_tool 的 `serve()` 无调用方，是半死代码

每修一个公共行为（安全头、错误形状）要改 4 处且必然漏改——漂移正在复利。

## Solution

新建顶层包 `tools_common/`（红队拍板：否掉 `workbench/` 放置，保持壳→工具的单向依赖，独立工具入口不背壳包），收敛一份 HTTP 管道实现；3 个工具 server 全量切换，workbench 壳仅复用其中的 Responder 部分（壳的注册表分发与 sidecar 生命周期不套工厂）。

## User Stories

1. As a 维护者，I want HTTP 响应发送/JSON 序列化/请求体读取只有一份实现，so that 修行为只改一处
2. As a 维护者，I want 静态文件服务统一带路径穿越防护，so that 工具端与壳的安全水位一致
3. As a 维护者，I want JSON 序列化的 NaN 策略全局统一为 `allow_nan=False`，so that 非法 JSON 不会流到前端才炸
4. As a 维护者，I want assistant_params 的 load/save/merge 只有一份实现，so that 落盘格式永不分叉
5. As a 维护者，I want roi 的未知计划名 422 守卫留在工具路由层，so that 收敛不冲掉防 LLM 幻觉落盘的保护
6. As a 维护者，I want 每个 server 的公开签名（`make_handler(state, cfg)` 等）不变，so that 现有测试与启动脚本零改动
7. As a 维护者，I want 独立工具入口（`main.py serve`、`python -m coupon_tool`）不依赖 workbench 包，so that README 承诺的"独立自治"保持成立
8. As a 审查者，I want 重构前有一组 characterization 测试钉住现状行为（响应头、404 体形状、缺失静态文件状态码、serve 冒烟），so that 重构的行为变化是显式清单而非意外
9. As a 维护者，I want 行为漂移的收敛方向逐条记录（deliberate-change 清单），so that review 能区分"有意统一"与"意外破坏"

## Implementation Decisions

1. **新包 `tools_common/`**（`__init__.py` + `httpkit.py`）。壳与三个工具都正向依赖它；依赖方向保持 tools_common ← 工具 ← 壳，无环。
2. **httpkit 提供四个组件**：
   - `Responder(handler)`：`send` / `json`（`ensure_ascii=False, allow_nan=False`）/ `read_body` / `static`（带穿越防护）。取现有最严实现为准。
   - `json_bytes(obj)`：单一序列化入口。
   - `make_dispatch_handler(handle_get, handle_post)` 工厂：生成安静模式的 Handler 类，404 回 JSON `{"error": "not found"}`。各 server 保留薄包装函数以钉住现有签名（测试已冻结它们）。
   - `serve_quiet(handler_factory, port, banner)`：ThreadingHTTPServer + 启动横幅 + KeyboardInterrupt 安静退出的公共模板。
   - `AssistantParamsStore(path)`：load / save / merge（`setdefault(key).setdefault(name).update` 形状）。校验（如 roi 的未知计划名 422）留在各工具路由层。
3. **范围**：coupon_tool / target_forecast / roi_tool 三个 server 全量切换；workbench 壳**仅**把 `_send`/`_json_bytes` 调用点替换为 httpkit 组件，壳的 `make_handler`（注册表前缀分发 + assistant 端点）与 `serve`（sidecar 生命周期、SIGTERM 转换）不改结构。
4. **deliberate-change 清单**（统一后有意改变的行为，实施时写入提交说明与 tasks.md）：
   - 壳所有响应增加 `Cache-Control: no-store` 头
   - forecast 独立模式 404 体从 `text/plain "not found"` 变为 JSON `{"error": "not found"}`（与壳内分发行为对齐）
   - forecast 缺失静态文件从 500 变 404
   - forecast `/api/calc` 读体改走统一 `read_body()`
   - coupon/roi 的 JSON 响应统一 `allow_nan=False`：引擎产出 NaN/Inf 时从"200+非法 JSON 体"变为序列化异常（coupon 的 route_post broad except 会报 422——接受该语义，前端本来就无法解析非法 JSON）
   - roi_tool 的 `serve()` 保留但改为调用公共模板（不删——避免顺手清理超范围；标记半死状态即可）
5. **不触碰**：三个引擎的数学、插件协议（registry manifest 契约）、assistant/sidecar 路径、静态前端文件。
6. **目标口径修正**（红队实测）：毛删 ~190 行、净删估 50-90 行；立项价值锚定为"收敛漂移、单一事实源"，不以 LOC 验收。

## Testing Decisions

- 好测试 = 只断言外部可观察行为（状态码、响应头、响应体形状、落盘文件内容），不断言内部实现。
- **先补 characterization 测试再动手**（`tests/test_httpkit_characterization.py`）：
  1. 每 server 一个端点的 `Cache-Control: no-store` 响应头现状断言
  2. 独立 handler 的 404 体形状现状断言
  3. forecast 缺失静态文件的现状状态码
  4. demo 全流程响应可被 `json.dumps(..., allow_nan=False)` 序列化（coupon compare / roi calc / forecast calc）
  5. coupon 独立入口 `python -m coupon_tool` 冒烟（import 守卫：`coupon_tool.server` 不 import `workbench.*`）
  6. 各 server `make_handler` 薄包装签名冒烟（已被现有测试钉住，确认即可）
- 重构后：除 deliberate-change 清单条目外，characterization 测试必须仍绿。
- 回归套件：`pytest tests/test_server.py tests/test_coupon_server.py tests/test_workbench.py tests/test_assistant_http.py`（红队实测 baseline 54 passed / 56s）。
- 既有守卫测试必须保持绿：`test_roi_rejects_unknown_plan_name`（roi 422 守卫）、`test_confirm_write_real_loopback`（落盘 JSON 格式不变）。
- 手动验证（无自动化覆盖的路径）：`python -m workbench serve` 起壳一次，确认三个工具页面加载；`main.py demo` 跑通。

## Out of Scope

- 阶段2-5（pipeline 收敛、coupon 路由表化、engine.simulate 拆分、测试 helper 去重）
- 引入任何 Web 框架或非标准库依赖
- roi `serve()` 半死代码的删除（仅记录）
- 前端静态文件、引擎公式、插件协议的任何改动
- assistant-sidecar（TS 进程）

## Further Notes

- 红队发现提案"工作区干净"表述不准：git 有 6 个脏条目，全部是 `.flow/` 自身过程文件（归档操作），不触及代码——baseline_dirty=[] 对代码成立。
- 漂移点统一方向一律取最严实现（红队与提案一致）。
- 上一轮 flow（assistant P3）产物已归档至 `.flow/archive/2026-09-27-assistant-p3/`。

## PRD diff gate（相对 proposal.md 的差异）

proposal.md 的硬约束与阶段1范围全部保留。以下为差异点：

1. **目标口径修正**：proposal 称"净删约 250 行"→ 实测毛删 ~190、净删估 50-90，价值锚改为"收敛漂移"。（事实修正，非决策变更；红队实测证据）
2. **httpkit 放置**：proposal 列为开放问题 → 拍板 `tools_common/` 顶层包。（填开放问题，红队论证依赖方向）
3. **范围精确化**：proposal 称"四个 server 改为 import 使用" → "3 个工具 server 全量 + 壳仅复用 Responder/_json_bytes"。（红队证据：壳的 make_handler/serve 含注册表分发与 sidecar 生命周期，不适配工厂）
4. **新增**：动工前补 6 条 characterization 测试（红队条件③）。
5. **新增**：deliberate-change 清单 6 条（红队盲区清单转正）。
6. **新增**：`AssistantParamsStore` 只收敛 load/save/merge，工具层校验显式保留（红队 kill-assumption 5 的处置）。

---

## GRILL 决议

### 第 1 轮（author-blind 子代理，2026-10-15，7 个已决问题包）

- **Q1 Responder 构造**：`Responder(handler, static_dir: Path | None = None)`，`static(name)` 要求 static_dir，resolve + 前缀检查 + is_file → 404 JSON。forecast 的 `/`、`/style.css`、`/app.js` 迁移到 `r.static(...)`；xlsx/csv 导出分支保留 raw `r.send(...)`（文件在 workspace 下，不属任何 static root；平台名穿越防护保留）。理由：构造注入让调用点保持一行，与各包绑定自有 STATIC_DIR 的现状一致。
- **Q2 serve 退出语义**：`serve_quiet` 统一为 `try: serve_forever()  except KeyboardInterrupt: pass  finally: server_close()`。deliberate-change 清单新增两条：forecast 不再打印"已退出。"；coupon/roi 不再同线程调 `shutdown()`（改为 finally server_close）。forecast 的预加载 `state.load()` 留在其薄 serve 包装里。
- **Q3 AssistantParamsStore**：`merge(section: str, patches: dict) -> dict`（双 setdefault 循环，返回合并后的 section，匹配两工具现有响应形状）。路径推导留在各工具（tools_common 不学 workspace 布局）。删除 forecast 模块级 `load_assistant_params`/`save_assistant_params`（无外部调用方，提交说明中记录）。roi 422 守卫保留在路由层 merge 之前。
- **Q4 serve 冒烟机制**：(a) 子进程测试——pytest 分配空闲端口，`python -m coupon_tool serve --port N --data-dir <tmp>`，cwd=tmp_path，轮询 `/api/state` 至多 ~10s 后 terminate（唯一真 socket 路径；coupon 的 CLI 入口传递性覆盖共享 serve_quiet 模板）；(b) roi/forecast 薄 serve 包装用 monkeypatch serve_quiet 断言透传参数；(c) import 守卫单列一条。roi 无独立 server 测试文件，characterization 断言需新测试文件自行在端口 0 启动 `roi_tool.server.make_handler`。
- **Q5 壳 `_read_json_body` 在迁移范围内**：迁到 `Responder(self).read_body()`（零行为变化，不进 deliberate-change 清单）。壳迁移全清单：10 处 `_send` + 3 处 `_json_bytes`；字节字面量错误体改为 `Responder.json(...)`（输出逐字节相同）。
- **Q6 打包细节**：`tools_common/__init__.py` 仅一行 docstring，不做 re-export；server 显式 `from tools_common.httpkit import ...`。PRD "四个组件"措辞更正为五个（Responder / json_bytes / make_dispatch_handler / serve_quiet / AssistantParamsStore）。
- **Q7 实施顺序与提交粒度**：一个 PR、六个提交，按风险序：① characterization 测试（先对现状跑绿）② `tools_common/httpkit.py` 无调用方 ③ roi（最小）④ coupon（SpecError/422 交互）⑤ forecast（漂移最多）⑥ 壳（仅 Responder 替换）。每次切换提交后跑四文件回归套件。tasks.md 需为本 flow 重建。
- **探测后确认已钉死、无需提问**：coupon SpecError/422 与统一 read_body 的组合（JSONDecodeError⊂ValueError 已被 route_post 捕获）；make_dispatch_handler 可调用形状（插件契约已固定 (handler, path) -> bool）；roi serve() 半死处理；NaN characterization 可执行性（现有 fixture 已驱动三引擎 demo 路径）。
