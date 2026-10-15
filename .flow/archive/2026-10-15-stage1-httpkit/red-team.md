# Red-Team: 阶段1——把 4 份 HTTP 管道拷贝收敛进共享 httpkit，净删 ~250 行

**verdict 先行：GO（有条件）**。逐行比对确认复制与漂移都真实存在，插件契约把响应内部实现与分发接口解耦，爆炸半径干净（无任何外部模块 import 这些私有符号）。但提案的头条数字"净删约 250 行"经实测高估 3-5 倍，"4 个 server 切换使用"对壳不成立，且指定验证套件恰好不覆盖本次要统一的漂移点。无任何 kill 准则已被触发，故不判 KILL。

## Top Kill-Assumptions（按 影响 × 可能性 × 测试成本 排序）

**1. "净删约 250 行"——算术上不成立（头条目标失真）**
- **Claim:** 一句话目标即"净删约 250 行重复代码"。
- **Fails if:** 阶段1 的真实价值被 LOC 衡量。实测：四个文件中可移除块（`_Responder`×3、`_json_bytes`×3、`make_handler`/`serve`×4、`assistant_params`×2、壳 `_send`）**毛删除 189 行**（逐文件行区间实测：coupon 54 / roi 65 / forecast 62 / 壳 8），加上 forecast 内联 static 与壳 static 分支也不过 ~203 行毛量。新建 httpkit（含 docstring 约 90-130 行）+ 各 server 必须保留的薄包装（`make_handler` 签名被测试钉死：`tests/test_server.py:24` 调 `server.make_handler(state, cfg)`，`tests/test_coupon_server.py:19` 调 `coupon_server.make_handler(app)`）+ 新 import ≈ 再计 120-160 行。**净删 realistic 估值 ~50-90 行**。
- **Evidence to get this week:** 已拿到——上述行数为实测，不是估算。实施 PR 的 diff stat 是最终确认。
- **Kill criterion:** 若 PR 落地净删 <100 行且提案仍以 250 行作为立项依据，则验收标准失真；应改写目标行为"收敛漂移、单一事实源"（这个理由其实更强）而非行数。注意：这不杀死重构本身，只杀死它的表述。
- **Cheapest test:** 已完成（本次行数实测）；实施时看 `git diff --stat`。

**2. "4 个 server 改为 import 使用"——壳无法使用其中两个核心组件**
- **Claim:** `make_dispatch_handler` + `serve_quiet` 收敛"4 个 server 各一份"的 `make_handler`+`serve`。
- **Fails if:** 实施者按字面把壳也塞进去。壳的 `make_handler`（`workbench/server.py:55`）是注册表前缀分发 + 助手端点（`/api/assistant/chat`、`/api/assistant/status`），结构不是 routes_get/routes_post 二分；壳的 `serve`（`workbench/server.py:111`）含 sidecar 生命周期、SIGTERM→KeyboardInterrupt 转换、finally 回收——`serve_quiet(app, port, banner)` 无法表达。壳实际只能复用 Responder/_json_bytes。另外三个工具的 `serve` 也各有漂移：forecast 启动即 `state.load()` 失败早暴露、Ctrl+C 分支不调用 `httpd.shutdown()` 而 coupon/roi 调用；`roi_tool/server.py:165` 的 `serve()` 全仓库无调用方（无 `__main__.py`、无 cli），是半死代码。
- **Evidence to get this week:** 实施前在提案中把范围改写为"3 个工具 server 全量 + 壳仅复用 Responder"；检查壳 diff 是否触碰 assistant/sidecar 路径。
- **Kill criterion:** 若实施 diff 中壳的 `make_handler`/`serve` 被改写以适应工厂（而非仅替换 `_send`/`_json_bytes` 调用点），停止——那是为对称性牺牲助手生命周期代码。
- **Cheapest test:** `pytest tests/test_assistant_http.py`（覆盖聊天端点、确认写回环、503 降级；已验证现绿）。壳 sidecar 启动路径无自动化测试，手动 `python -m workbench serve` 起一次即可。

**3. 指定的验证套件不覆盖被统一的漂移点——"pytest 保持绿"是弱证据**
- **Claim:** 验证 = `pytest tests/test_server.py test_coupon_server.py test_workbench.py test_assistant_http.py`（四文件均存在，实测 54 passed in 56s）。
- **Fails if:** 行为变化落在套件盲区而绿灯放行。盲区精确清单：(a) **四个 `serve()` 函数全部零测试**（套件只起 `make_handler`）——`serve_quiet` 是本次新组件却无覆盖；(b) 无任何断言检查响应头——壳 `_send`（`workbench/server.py:47`）缺 `Cache-Control: no-store` 而工具端有，统一后壳响应多一个头，无测试会察觉；(c) 404 响应体形状：forecast 独立模式回 `text/plain "not found"`（`target_forecast/server.py:281`），coupon/roi 回 JSON——测试只断言状态码；(d) forecast 缺失静态文件今天走 broad except 回 **500**，统一 `static()` 后变 **404**，无测试覆盖；(e) `allow_nan=False` 统一后，若 coupon/roi 引擎某路径产出 NaN/Inf，今天回 200+非法 JSON 体（前端 JSON.parse 本就会炸），之后 `json.dumps` 抛 ValueError → 被 coupon `route_post` 的 `except (ValueError...)` 捕获并**误报为 422 "请求不合法"**（服务端 bug 伪装成客户端错误）。另发现一个提案未列的漂移：forecast `/api/calc` 内联读 body（`server.py:265-266`）绕过 `read_body()`，是第三份读体实现。
- **Evidence to get this week:** 重构前补 ~6 条 characterization 断言（每 server 一个端点的响应头、独立 handler 404 体、缺失静态文件的现状状态码、demo 全流程响应用 `allow_nan=False` 序列化验证不抛）。
- **Kill criterion:** 无——这是验证充分性问题，用补测试解决，不构成停做理由。若不愿补这 6 条断言，则提案的"验证"一节应降级表述为"冒烟回归"而非"验证"。
- **Cheapest test:** 30 分钟写一个 `test_httpkit_characterization.py`，先对现状跑绿，重构后除 deliberate-change 清单外必须仍绿。

**4. httpkit 放 `workbench/` 是潜在循环导入 + 依赖方向倒置——开放问题应在动工前关闭**
- **Claim:** 提案自述开放问题：httpkit 放 `workbench/` 还是新顶层包 `tools_common/`。
- **Fails if:** 选 `workbench/`。证据：当前依赖方向是壳→工具（`build_default_registry` 惰性 import 工具插件，`workbench/server.py:34`），README:40 明确"各工具……独立自治""新增工具不改底座"，README:59 把"独立入口保留可用、独立与壳内行为一致"列为既定特性。工具 server `from workbench.httpkit import ...` 后：今天**不会**真的循环（`workbench/__init__` 只牵 `.server`+`.registry`，工具 import 是运行期惰性），但埋了一颗枪——任何未来在 `workbench.server` 模块级 eager import 工具的改动都会制造 `coupon_tool.server → workbench.httpkit → workbench/__init__ → workbench.server → coupon_tool.plugin → coupon_tool.server` 的真实循环；且独立工具入口（`main.py serve`、`python -m coupon_tool serve`）将为一个响应帮助类背上整个壳包。两种放置的实施成本差仅为"是否新建一个目录"。
- **Evidence to get this week:** 无需更多证据——这是决策不是研究。用 `tools_common/`（或等名顶层包），壳与工具都正向依赖它。
- **Kill criterion:** 对"放 workbench/"这一选项：若采纳，需同时在 tests 里加一条 import 守卫（断言 `coupon_tool.server` 的模块依赖图不含 `workbench.server`），否则该选项的隐性成本未被定价。更简单：直接判这个选项出局。
- **Cheapest test:** 重构后 `python -c "import coupon_tool.server"` + `python -m coupon_tool serve --help` 冒烟（独立入口是 README 承诺的特性）。

**5. "assistant_params 读写逻辑相同"——load/save 相同，merge 策略有意不同**
- **Claim:** `target_forecast/server.py:197-207` 与 `roi_tool/server.py:85-94` 逻辑相同，`AssistantParamsStore` 一处实现。
- **Fails if:** 统一把 roi 的守卫冲掉。roi 在路由层拒绝未知计划名（防 LLM 幻觉落盘，`server.py:122-126`），有回归测试钉住（`test_assistant_http.py:145`）；forecast 无对应校验。两者落盘路径也不同（`workspace/forecast/` vs `workspace/roi/`）。`AssistantParamsStore(path)` 只收敛 load/save/通用 merge 形状（`setdefault(key).setdefault(name).update`），校验必须留在各工具路由层——提案没说不留，但也没说留。
- **Evidence to get this week:** 助手经 HTTP 回环写参数（`workbench/assistant/service.py:165,182`），不直接 import server 内部；`test_confirm_write_real_loopback`（`test_assistant_http.py:109`）直接断言落盘 JSON 内容——文件格式不变即安全。
- **Kill criterion:** 实施 diff 若删除 roi 的未知计划名 422 分支或使其不可达，停止。
- **Cheapest test:** 现有 `test_roi_rejects_unknown_plan_name` 就是守卫测试，保持绿即可（已确认在指定套件内）。

## What's Well-Reasoned

- **复制事实属实**：coupon 与 roi 的 `_Responder` 逐字相同（`coupon_tool/server.py:60-89` vs `roi_tool/server.py:28-57`）；`_json_bytes` 三份逐字相同；三个工具的 `make_handler`/`serve` 模板结构一致。提案引用行号全部命中。
- **漂移证据属实且是比 LOC 更强的立项理由**：forecast `json()` 独有 `allow_nan=False`（`server.py:183`）、壳独有路径穿越防护（`workbench/server.py:83`）、壳 `_send` 缺 `no-store`、forecast 无 `static()`。四份拷贝已经开始各自演化，正是收敛的时间窗。
- **爆炸半径干净**：全仓库 grep 确认无任何模块在四个 server 之外 import `_Responder`/`_json_bytes`/`_send`；插件契约（`registry.py` 的 `handle_get/handle_post` 协议）把响应内部实现完全解耦，收敛不会破坏插件架构；助手只走 HTTP 回环。
- **约束 1（无框架）有据**：模块 docstring 与 README:84 均明确"只用标准库 http.server，无新增依赖"，提案遵守。
- **测试钉住了公开签名**：现有套件强制每个 server 保留薄包装（`make_handler(state, cfg)` 等签名被动冻结），这恰好防止实施者借机改 API。
- **指定验证套件真实存在且现绿**：四文件 54 测试，实测 56 秒通过——baseline 可信。

## What I Couldn't Assess

- **coupon/roi 引擎是否会在合法边界输入下产出 NaN/Inf**（决定 `allow_nan=False` 统一是否引入新 422/500）：guard 看起来齐全（spend=0 被拒等），未穷举证明。最便宜的确认：用 demo 集 + 现有测试夹具的全量响应跑 `json.dumps(..., allow_nan=False)`。
- **"~250 行"的原始口径**：是否误把阶段2（main.py/server.py pipeline 双份）的量算进了阶段1。无法从文档推断，但无论如何实测毛量只有 ~190-200。
- **约束 4 的事实小错**：提案称"本次开工时工作区干净，baseline_dirty=[]"，但 git 显示 6 个脏条目——全部位于 `.flow/`（上一轮 prd/red-team/review-findings/tasks 被删并归档、proposal.md 在改）。属本 flow 自身的过程文件操作，不触及代码，对重构无影响，但"工作区干净"的表述不准确。

**Verdict: GO**——无 kill 准则已被触发。动工前做三件廉价的事：① 把目标行从"净删 ~250"改为实测口径（毛删 ~190、净删估 50-90，价值锚在收敛漂移）；② 开放问题当场拍板 `tools_common/`（或等名顶层包），否掉 `workbench/` 选项；③ 补 6 条 characterization 断言把 serve/响应头/404 体/缺失静态文件钉住，再动手。范围表述改为"3 个工具 server 全量收敛 + 壳仅复用 Responder"。
