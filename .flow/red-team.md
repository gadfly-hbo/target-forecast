# Red-Team: 测算工作台整合 P0 — 抽共享底座，两工具插件化（引擎不动，单端口单入口）

## Top Kill-Assumptions (ranked)

### K1 —「URL 加前缀即可迁移」是便宜的
- **Claim:** 两工具前端/服务端可以通过加 `/t/{id}/` 前缀搬进壳里，引擎不动、前端只改少量路径。
- **Steelman:** 前端 fetch 点极少且集中（target 3 处 fetch；coupon 一个 api() 帮助函数收敛全部 POST，另有 8 处导出 `<a href>`），服务端路由是扁平的精确匹配表，剥离前缀后可直接复用现有匹配逻辑。
- **Fails if:** 前端或服务端存在未被发现的路径/引用假设（如导出下载链接是根绝对路径、iframe/挂载后相对路径解析错乱、静态资源缓存键冲突），迁移变成逐行排雷。
- **Evidence（已取）:** `grep` 证实：两前端全部 API 调用点已枚举（target_forecast/static/app.js:36,49,416；coupon_tool/static/app.js:15 单一 api() + :378-381,414-417 导出链接）；两服务端均为扁平 `self.path` 匹配（target_forecast/server.py:186-203；coupon_tool/server.py:90-245）。coupon 的 api() 帮助函数意味着加 base 前缀是一处改动；导出链接是字符串模板，同样集中。
- **Kill criterion:** 迁移中发现任何工具的前端路径调用点超过已枚举集合，或服务端路由依赖第三方不可控重定向 → 停下重新评估迁移策略。
- **Cheapest test:** P0 第一个切片就做「coupon api() 加 base + 壳内冒烟」，一天内见分晓。

### K2 — 单壳进程能同时承载两工具且无状态互串
- **Claim:** 标准库 ThreadingHTTPServer 单进程托管两个工具（各自有 WorkbenchState/Workbench 上下文与锁）不会互相干扰。
- **Steelman:** 两工具现有 server 都已经是 ThreadingHTTPServer + 各自锁保护的上下文，无共享全局态；壳只是把两个 handler 的路由表挂到同一进程。
- **Fails if:** 任一工具的 handler 依赖「自己拥有整个 path 命名空间」之外的隐式单例（如模块级缓存、cwd 相对路径在 shell 启动目录变化后失效）。
- **Evidence（已取）:** coupon Workbench 用构造参数 data_dir/out_dir/templates_dir（相对路径，cwd 敏感）；target WorkbenchState 用 root: Path。壳启动时若 cwd 不同，相对路径会失效——已识别，需在插件注册时显式传绝对路径。
- **Kill criterion:** 壳内某工具的数据目录读写落到错误位置（演示播种写到壳目录而非仓库根）→ 修插件上下文构造。
- **Cheapest test:** 壳起服务后调两工具的 /api/state，再从仓库根外另一目录启动复测一次。

### K3 —「存量测试保持绿色」与「入口变更」不冲突
- **Claim:** P0 结束后 `.venv/bin/python -m pytest tests -q`（98+ 项）不修改断言仍全绿。
- **Steelman:** tests/test_server.py 与 tests/test_coupon_server.py 打的是两工具各自的独立 server 入口；只要旧入口（`main.py serve`、`python -m coupon_tool serve`）保留可用，存量测试零改动。
- **Fails if:** 为了插件化把服务端路由代码大改，导致旧入口行为漂移；或测试依赖端口/路径假设被壳占用。
- **Kill criterion:** 任何存量测试需要改断言才能过 → 视为迁移破坏，回退该改动而不是改测试。
- **Cheapest test:** 每个迁移切片后跑全量 pytest（4 秒内，成本极低）。

### K4 — 壳 + 工具自治前端 够用，不会被「未来 LLM 驱动」推翻
- **Claim:** iframe/页签式壳与 per-tool API 前缀，不会成为 P3 pi agent sdk 接入时的架构债。
- **Steelman:** LLM 走的是 JSON API 层（manifest actions），不碰前端 DOM；壳前端形态与 LLM 能力正交。
- **Fails if:** P3 需要跨工具编排 UI 状态（如 LLM 把目标测算的基线参数直接填进优惠券场景），而工具前端完全自治导致无桥接点。
- **Kill criterion:** P3 设计时发现必须穿透工具前端内部状态才能编排 → 届时在 manifest 里补 UI-bridge 接口（P0 不为此设计）。
- **Cheapest test:** P0 只保证 manifest 有 actions 占位字段与单一 API 前缀规范——这两个预留足以支撑 P3 起步，无需更多。

### K5 — 底座抽象不超 speculative
- **Claim:** 从两个工具抽出的共性（路由分发、静态托管、导航壳、启动脚本）是真实共性，不是为假想第三个工具过度设计。
- **Fails if:** 抽到一半发现两工具的「共性服务」其实差异很大（如 coupon 的导出下载 vs target 没有下载），底座被迫长出一套只有一方用的抽象。
- **Kill criterion:** 底座出现任何「当前两个工具都不用、只为未来准备」的函数/端点 → 删除。
- **Cheapest test:** PRD 阶段逐条核对底座职责清单，每条标注「哪个现有工具在用」。

## What's Well-Reasoned

- **引擎不动**的决策有硬依据：两引擎已是纯函数包，coupon 有 98 项验收测试锁定行为，迁移不碰引擎是低风险拆分的核心。
- **分期路线**（P0 底座 → P2 用 ROI 工具验证协议 → P3 LLM）把最不确定的 LLM 集成放在协议被真实第三个工具验证之后，顺序正确。
- **预留 actions 字段但不实现**：符合「现在只留接口」的不过度设计原则。
- 数据目录收编推到 P1 是对的——P0 强行统一 cwd 敏感的路径会放大 K2 风险。

## What I Couldn't Assess

- pi agent sdk 的实际接口形态（未见其文档），LLM 预留是否充分只能在 P3 验证；P0 的 actions 占位是最低成本的 hedge。
- 壳前端用 iframe 还是 DOM 挂载对「双击 .command 本地工具」场景的体感差异（iframe 内工具的状态栏/全屏交互），留给 GRILL 决策，两种方案都不影响 API 层。

**Verdict: GO** — 无已满足 kill criterion 的假设；K1/K2 的证据已在红队阶段用 grep 直接取到，迁移成本边界清晰。
