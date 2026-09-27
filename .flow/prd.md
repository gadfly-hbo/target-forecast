# PRD — 测算工作台整合 P0：统一底座 + 两工具插件化

规格源优先级：`.flow/proposal.md` > 本 PRD > 实现建议。红队报告：`.flow/red-team.md`（verdict GO，K1-K5 已记录）。

## Problem Statement

用户（经营者本人，本机双机使用）目前要维护两个独立的测算工具：目标测算（端口 8300，自己的 .command、server、前端）和优惠券测算（端口 8310，同样一整套）。每个新测算工具（如投放 ROI）都要复制整套 HTTP 骨架、静态页服务、启动脚本、端口管理——底座能力被重复建设。同时未来要用 pi agent sdk + LLM 驱动测算，两个割裂的 API 命名空间意味着 LLM 工具面也要做两套。

## Solution

抽取共享底座 `workbench/`：单一壳服务（标准库 http.server，单端口 8300）+ 工具注册表 + 带左侧导航的壳前端 + 单一启动脚本。两个现有工具以**插件**形式注册进壳：壳按 `/t/{tool_id}/` 前缀分发 API 与静态资源，工具引擎与前端的业务逻辑零改动（仅 API 路径从根绝对改为相对）。旧独立入口（`main.py serve`、`python -m coupon_tool serve`）保留可用，存量 98+ 项测试零断言修改保持绿色。manifest 中预留 `actions` 空字段，为 P3 LLM function-calling 留接口。

## User Stories

1. 作为使用者，我想双击一个 `启动测算工作台.command` 就打开包含所有测算工具的工作台，以便不再记多个端口和脚本。
2. 作为使用者，我想在工作台左侧导航切换「目标测算 / 优惠券测算」，以便在同一窗口内使用两个工具。
3. 作为使用者，我想两个工具在壳内的交互、视觉与独立运行时一致，以便没有学习成本。
4. 作为使用者，我想旧的独立入口（两个旧 .command、CLI serve）仍然可用，以便既有习惯与测试不被破坏。
5. 作为使用者，我想旧入口启动时看到「已整合进工作台」的提示与兼容行为，以便平滑过渡。
6. 作为维护者，我想新增测算工具时只写一个引擎包 + 一个 manifest（id/name/icon/static/register_routes/seed_demo/actions），以便不改底座一行代码。
7. 作为维护者，我想插件协议有文档化的最小示例（以现有两工具为范例），以便第三个工具（ROI）直接照做。
8. 作为维护者，我想壳服务有独立冒烟测试（工具清单、前缀分发、页面服务），以便底座变更可回归。
9. 作为维护者，我想工具前端静态文件中不出现根绝对 `/api` 引用（不变量测试），以便任何工具都能在任意前缀下工作。
10. 作为未来的 LLM 接入方，我想所有工具 API 收敛在 `/t/{tool_id}/api/` 单一网关下且 manifest 预留 actions 声明位，以便 P3 不需要重构 API 层。
11. 作为维护者，我想数据目录（data/、coupon_data/）在 P0 保持原位、壳内工具读写路径与独立运行时一致，以便迁移零数据风险。

## Implementation Decisions

### D1 — URL 方案（新增细节，proposal 未指定具体前缀形态）

- 壳根 `/`：导航壳页面（含工具清单 API `/api/state`，供启动脚本健康检查）。
- 工具页：`/t/{tool_id}/`（index.html）、`/t/{tool_id}/style.css`、`/t/{tool_id}/app.js`。
- 工具 API：`/t/{tool_id}/api/...`。
- 壳分发逻辑：匹配 `^/t/([a-z0-9_]+)(/.*)?$`，剥离前缀后交给该工具的路由函数；未知 tool_id → 404。
- 工具 id：`forecast`（目标测算）、`coupon`（优惠券测算）。

### D2 — 服务端插件化方式（新增细节）

- 每个工具包新增 `plugin.py`，暴露 `TOOL` manifest（dict：id/name/icon/static_dir/seed_demo/actions=[]）与路由函数 `handle_get(handler, path)` / `handle_post(handler, path)`（path 已剥离前缀，返回 bool 表示是否命中）。
- 两工具现有 `server.py` 的路由匹配逻辑**原样提取**为上述路由函数，独立 server 的 do_GET/do_POST 改为调用同一函数——单一事实源，避免双份维护；对外行为不变（存量测试锁定）。
- 壳持有各工具自己的上下文对象（WorkbenchState / Workbench），构造时显式传**仓库根绝对路径**，消除 cwd 敏感性（红队 K2）。
- 进程模型：单 ThreadingHTTPServer；两工具上下文各自的锁保持不变。

### D3 — 前端迁移方式（新增细节；红队 K1 证据支持）

- 工具前端所有 API 调用从根绝对路径改为**相对路径**（`fetch("api/state")`），页面从 `/t/{id}/` 加载时自然解析到 `/t/{id}/api/...`；独立运行时页面在根，相对路径同样解析到 `/api/...`——**一处改动，两种部署都正确**。
- target：3 处 fetch（app.js:36,49,416）。coupon：api() 帮助函数 1 处（app.js:15）+ 导出 `<a href="/api/export/...">` 8 处改为相对。
- 工具前端 DOM/CSS/交互零改动；壳用 iframe 加载工具页（隔离最强，工具状态栏/样式不受壳影响）。〔iframe vs DOM 挂载的最终确认走 GRILL〕

### D4 — 包物理布局（对 proposal 架构图的解释性决策）

- `target_forecast/`、`coupon_tool/` **保持顶层包名不移动**（proposal 中的 `tools/` 为逻辑分层示意）：避免改动全部 import、测试、README、CLI 入口，diff 聚焦。
- 新增顶层包 `workbench/`：`server.py`（壳服务+注册表）、`static/`（壳页面）、`__init__.py`。

### D5 — 启动入口（proposal 开放问题，GRILL 待决，本 PRD 给推荐）

- 推荐：新增 `启动测算工作台.command`（单端口 8300，端口占用自动换，流程复用现有脚本模式）；两个旧 .command 改为薄壳——启动同一个壳服务并 `open` 对应工具页 `/t/forecast/` 或 `/t/coupon/`。
- 旧 CLI 入口（`main.py serve`、`python -m coupon_tool serve`）保留，服务行为不变。

### D6 — 数据与配置（proposal 已定）

- `data/`、`coupon_data/`、`output/`、`config.yaml` 全部原位不动；壳以仓库根为 root 构造插件上下文。

### D7 — manifest actions 预留（proposal 已定）

- `TOOL["actions"] = []`，并在 workbench 包 docstring 中注明其 JSON Schema 用途与 P3 填充约定；不实现任何 actions 逻辑。

## Testing Decisions

好测试的标准：只测外部可观察行为（HTTP 响应、引擎输出），不测内部实现；优先复用现有 seam。

- **主 seam（新增）**：壳 HTTP 层——`tests/test_workbench.py` 起壳服务（随机端口），断言：`/api/state` 返回两工具清单（id/name/icon）；`/t/forecast/api/state` 与 `/t/coupon/api/state` 均 200 且结构与独立运行一致；`/t/{id}/` 页面可服务；未知 tool 404。沿用现有 server 冒烟测试模式（tests/test_server.py、tests/test_coupon_server.py 为先例）。
- **不变量测试（新增）**：静态扫描两工具 `static/*.js`，断言不存在根绝对 `"/api` 或 `'/api` 引用——锁死 D3 的可移植性。
- **回归 seam（现有）**：`tests/` 全部 98+ 项存量测试零断言修改保持绿色（红队 K3：任何存量断言需要修改 = 迁移破坏，回退改动）。
- **端到端冒烟（新增，轻量）**：壳内两工具各做一次真实测算调用（forecast 的 POST calc、coupon 的 POST compare demo 场景）验证前缀下业务闭环。

## Out of Scope

- P1：数据目录统一收编（workspace/{tool_id}/）、统一导出下载通道、壳的设计语言精修。
- P2：投放 ROI 测算工具本身。
- P3：pi agent sdk / LLM 接入、actions 内容填充、助手侧栏。
- 引擎、口径、Excel 报表、优惠券四子模型的任何改动。
- 工具前端除 API 路径外的任何视觉/交互改版。

## GRILL 决议（自我拷问，2026-09-27）

约束：proposal.md 已记录的方向决策不重新讨论；以下均为 proposal 未决或 PRD 未细化的开放问题，均按推荐自答（gated 模式下用户预先授权「全部按推荐」），无升级项。

**G1 — 壳前端形态：iframe（推荐并采用）。** 工具前端 DOM/CSS 零改动的隔离成本最低，工具状态栏、滚动、弹窗全自治；DOM 挂载需解决 id/CSS 命名空间污染与视觉回归风险，收益（无 iframe 边框）不抵成本。LLM 驱动走 API 层，与前端形态正交。G1 同时确认 D3 的 iframe 方案。

**G2 — 旧 .command 处置：薄壳转发（推荐并采用）。** 新单一入口 `启动测算工作台.command`；旧两脚本改为：检测壳服务已在 8300 运行 → 直接 `open` 对应工具页（复用优惠券脚本已有的「已在运行只聚焦」模式）；未运行 → 起壳服务（带[已整合]提示语）后打开对应工具页。保留用户既有习惯、零双份维护。

**G3 — 壳服务入口：** 新增 `workbench/` 包，提供 `python -m workbench serve --port N`（等价 `workbench/server.py: serve(root, port)`）；启动脚本调用之。旧 `main.py serve` 与 `python -m coupon_tool serve` 保留独立行为。

**G4 — 工具发现机制：** 显式注册表（workbench 模块内列出已安装插件清单），不用动态扫描导入——本地静态工具集，显式清单可读后、零魔法。

**G5 — 深链与导航激活态：** 壳根页面读 `?tool={id}` 设置初始 iframe 与导航高亮；切换导航只改 iframe src，不刷新整页。旧脚本转发依赖此参数。

**G6 — 壳 UI 最小范围：** 窄侧栏（产品名「测算工作台」+ 工具导航项 icon+name + 底部「全部数据与测算在本机完成」声明）+ 内容区单 iframe。不做工具状态聚合、不做壳内通知中心——那些是 P3 LLM 侧栏的事。壳视觉 token 取全局 `~/.zcode/design/DESIGN.md` 基线（实现前读取），工具内部样式不动。

**G7 — 不变量边界（响应红队 K5）：** 底座职责清单逐条验收：路由分发、静态托管、导航壳、启动脚本、健康检查（/api/state）、iframe 加载。凡不在此清单上的底座功能（统一导出、数据目录收编、actions 实现）P0 一律不做。

## Further Notes

- 红队 K1-K5 结论：GO；K1（路径迁移成本）与 K2（cwd 敏感）的证据已在红队阶段用 grep 取得，D2/D3 直接吸收。
- 壳前端视觉遵循全局设计基线 `~/.zcode/design/DESIGN.md`（JuanerAI Xanthil 暖灰青工作台语言）的最小应用：导航壳的配色/密度 token，不动工具内部。
