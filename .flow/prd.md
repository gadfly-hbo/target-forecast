# PRD — 测算工作台整合 P1：数据收编 + 统一导出 + 状态栏与设计语言

规格源优先级：`.flow/proposal.md`（P1）> P0 规划继承项 > 本 PRD > 实现建议。红队：`.flow/red-team.md`（GO，K1-K5）。

## Problem Statement

P0 后两个测算工具共享壳服务，但数据仍散落在仓库顶层：`data/`（目标测算输入）、`coupon_data/`（优惠券存储）、`output/`（两工具产出混放）。三个问题：① 顶层目录随工具增多会继续膨胀，与「一套底座」目标不符；② 优惠券有工作台内导出下载，目标测算的 Excel 报表只能去 Finder 找，两工具导出体验不统一；③ 壳缺底部状态栏，跨工具通用信息（本机运行、版本、当前工具）没有落位，设计语言只做了 P0 初版。

## Solution

建立 `workspace/{tool_id}/` 数据布局并无损收编存量数据；两工具导出下载统一到 `/t/{id}/api/export/...` 约定（目标测算只下载已存在的磁盘产物，不在 serve 路径新增报表生成）；壳加底部状态栏并按全局 Xanthil 设计基线精修。

## User Stories

1. 作为使用者，我想所有测算工具的数据都在 `workspace/{tool_id}/` 下，以便顶层目录干净、备份/迁移清晰。
2. 作为使用者，我想双击启动脚本后存量数据自动无损迁移到新布局，以便无感升级、不丢历史场景与报表。
3. 作为使用者，我想迁移遇到冲突（新旧位置都有文件）时绝不被覆盖，以便本地数据安全。
4. 作为维护者，我想迁移逻辑是可单测的纯函数（计划→执行分离），以便先在临时目录验证再碰真实数据。
5. 作为使用者，我想在工作台里直接下载目标测算的 Excel 报表与中间指标 CSV，以便不用去 Finder 翻 output/ 目录。
6. 作为使用者，我想两工具的下载入口形态一致（都在 `/t/{id}/api/export/...`），以便用法可迁移到未来的 ROI 工具。
7. 作为使用者，我想壳底部状态栏看到当前工具、本机运行声明与版本，以便确认环境与数据边界。
8. 作为使用者，我想数据源为演示数据时有明确标记，以便不会把演示数当正式数（forecast 的 demo_used 状态在壳层可见）。
9. 作为维护者，我想数据目录改动后 113 项存量测试零断言修改保持绿色，以便确认行为无回归。
10. 作为维护者，我想 `workspace/` 不入 git、旧 data/ coupon_data/ output/ 条目从 .gitignore 移除后由迁移保证干净，以便仓库卫生。

## Implementation Decisions

### D1 — 目标布局

```
workspace/
├── forecast/            # 目标测算（tool_id=forecast）
│   ├── orders/          # 模式A 订单明细（原 data/orders）
│   ├── metrics/         # 模式B 聚合指标（原 data/metrics）
│   └── output/          # 报表 + 中间指标（原 output/，含 目标测算报告.xlsx、中间指标/）
└── coupon/              # 优惠券测算（tool_id=coupon）
    ├── scenarios/ runs/ decisions/ reviews/ profiles/   # 原 coupon_data/* 原样收编
    └── output/          # 三格式导出（原 output/coupon/）
templates/               # 两工具共用，原位不动
config.yaml              # 留仓库根（全局口径与情景参数）
```

### D2 — 迁移机制（新增细节，吸收红队 K1）

- `workbench/migrate.py`：`plan(root) -> 操作计划`（纯函数，可单测：列出 move 操作与冲突清单）+ `apply(root) -> 报告`（执行计划：逐文件移动；**冲突文件跳过不覆盖**，报告列出）。
- 冲突定义：目标路径已存在且与源不是同一文件。目标存在源不存在 → 视为已迁移，跳过。
- 启动脚本（三个 .command）起服务前：若 `workspace/` 不存在且旧目录有数据 → 执行迁移并输出结果；已迁移 → 无操作。**服务进程本身不做隐式迁移**（fail-closed：HTTP 服务不悄悄改文件系统）。

### D3 — 两工具路径改造（新增细节，吸收红队 K2）

- forecast：`WorkbenchState` 扫描 `root/workspace/forecast/{orders,metrics}`；`demo.generate`、`templates.build`、report/main.py 的 OUT_DIR 指向 `workspace/forecast/output`；CLI 提示文案同步。空数据自动生成演示数据逻辑保留（写到新路径）。
- coupon：`plugin.py` 构造 `workspace/coupon` 与 `workspace/coupon/output`；`server.serve()` 与 `storage.Store`、`exports.export_all` 的默认参数同步更新。
- 存量测试设施允许调整指向（如 test_server.py fixture 的 root 语义不变，靠迁移后的 workspace 供数），**业务断言零修改**是硬门槛（红队 K2 kill criterion）。

### D4 — 统一导出下载（新增细节，吸收红队 K3）

- 约定：每工具导出下载统一挂 `/t/{id}/api/export/...`。coupon 现状已符合（`/t/coupon/api/export/{run_id}/{kind}`），仅需路径根变化（随 D3）。
- forecast 新增 `GET /t/forecast/api/export/report`（下载 workspace/forecast/output/目标测算报告.xlsx）与 `GET /t/forecast/api/export/metrics/{platform}`（下载中间指标 CSV）。**只服务已存在的磁盘产物**，文件不存在 → 404 提示「先运行 main.py run 生成」。不在 serve 路径新增报表生成能力（K3 kill criterion）。
- 壳不做导出聚合端点（红队 K4：无第二用户，不做当前工具不用的功能）。

### D5 — 壳状态栏（新增细节，吸收红队 K4）

- 壳底部状态栏字段：产品名+版本、当前激活工具名、本机运行声明、数据源标记（仅当工具 /api/state 含 demo_used 时显示「演示数据」）。
- 数据来源：壳前端直接 fetch 当前工具的 `/t/{id}/api/state`（同源，无需插件协议新增接口）。coupon 无 demo_used 字段则状态栏不显示数据源块。**不为状态栏扩展插件协议**（K4 kill criterion）。

### D6 — 仓库卫生

- `.gitignore`：移除 `data/`、`output/`、`coupon_data/` 三条，加 `workspace/`。
- README：目录结构、数据放置说明（templates 文案同步指向 workspace）、迁移说明。

### D7 — 设计语言（新增细节，吸收红队 K5）

- 范围限定三处：底部状态栏（新，Xanthil token：surface-2 底、border-strong 顶线、meta 10.5px 字号、语义色对）、侧栏微调（激活态对齐 accent token，P0 已接近）、内容区 iframe 底色与壳底一致。不做清单外组件（无命令面板/Inspector 重构）。

## Testing Decisions

好测试标准：测外部行为（文件系统结果、HTTP 响应），不测内部实现；迁移逻辑先用 tmp 目录验证再碰真实数据。

- **新 seam 1：迁移纯函数**（tests/test_migrate.py，tmp_path）：空目录无操作；源有数据目标无 → 全部移动；冲突（目标已有不同文件）→ 跳过并报告、源不被删；目标存在源不存在 → 视为已迁移。目标存在源不存在 → 视为已迁移，跳过。
- **新 seam 2：导出下载 HTTP**（tests/test_workbench.py 增补）：`/t/forecast/api/export/report` 对存在文件 200、不存在 404；`/t/coupon/api/export/{run_id}/markdown` 收编后路径正常。
- **回归 seam**：`tests/` 113 项存量测试零断言修改全绿（硬门槛）。
- **端到端**：真实仓库执行一次 migrate（本机数据），壳起服务验证两工具 state 正常、forecast 报表可下载。

## Out of Scope

- P2（投放 ROI 工具）、P3（LLM / pi agent sdk / actions 填充）。
- forecast 在 serve 路径生成报表的新能力（下载只服务已有产物）。
- 壳级导出聚合端点、插件协议为状态栏新增接口。
- P0 审查遗留的 5 条非阻断建议（记录在 `.flow/archive/workbench-p0/review-findings.md`，不在 P1 处理）。
- 引擎、口径、情景参数逻辑的任何改动。

## GRILL 决议（自我拷问，2026-09-27）

约束：proposal（P1）与 P0 继承决策不重新讨论；以下均为 PRD 未细化的开放点，按推荐自答，无升级项。

**G1 — 冲突粒度：文件级。** 迁移判断逐文件（目标文件已存在且内容不同 → 跳过+报告；目录存在与否不构成冲突）。「workspace 存在但为空」正常搬迁。

**G2 — 旧目录清理：迁移后删除空目录。** apply 对已搬空的旧目录（data/、coupon_data/、output/ 内已空的子树）执行自底向上 rmdir（仅删空目录）；有冲突遗留的非空目录保留并列入报告。

**G3 — 目录自动创建。** migrate apply 与 forecast demo 生成路径都保证父目录自动创建（demo.generate 现状若已建目录则复用；缺失则补 mkdir parents）。

**G4 — 迁移有冲突被跳过时不阻断启动。** 启动脚本输出冲突清单 + 提示，仍起服务（fail-closed 只针对「不覆盖文件」，服务可用性 fail-open）。

**G5 — forecast 导出端点的中文平台名。** `/t/forecast/api/export/metrics/{platform}` 的路径参数做 URL decode（%E5%A4%A9%E7%8C%AB ↔ 天猫）；未匹配到文件 404。前端生成链接时 encodeURIComponent。

**G6 — WorkbenchState 的 root 语义不变。** 构造仍收仓库根，内部拼 `workspace/forecast/{orders,metrics}`；插件协议（P0）的 build_tool(root) 签名不动。

**G7 — 测试数据环境。** 单测全部 tmp 目录；真实仓库迁移作为切片 5 的 e2e 冒烟执行一次（本机）；MacBook 端靠启动脚本在首次启动时自动迁移。

**G8 — coupon 的 serve() 独立入口默认值同步。** `python -m coupon_tool serve --data-dir` 默认指向 workspace/coupon（与 plugin 一致），CLI 参数可覆盖行为不变。

## Further Notes

- 双机数据各自维护的现状不变：迁移在每台机器首次启动时各自执行，冲突跳过策略保证两端本地数据不被覆盖。
- K3 的方向选择（forecast 只下载已有产物）如未来被证伪（用户想要在壳内一键生成报表），作为独立需求重新评估。
