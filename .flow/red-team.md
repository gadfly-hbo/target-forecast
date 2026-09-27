# Red-Team: 测算工作台 P1 — 数据收编 workspace/ + 统一导出 + 状态栏与设计语言

## Top Kill-Assumptions (ranked)

### K1 —「无损迁移」在两台机器上都可安全自动执行
- **Claim:** data/ 与 coupon_data/ 的存量内容可以自动搬到 workspace/{forecast,coupon}/，用户无感、不丢数据。
- **Steelman:** 路径面已枚举且极小（main.py / demo.py / templates.py / 两 server.py / 两 plugin.py / storage.py / exports.py / 启动脚本 / .gitignore）；移动文件本身可逆（先复制后删旧），冲突可检测。
- **Fails if:** 两台机器（macmini/MacBook）各自数据有差异（真实业务数据两端各自维护——P0 launcher 注释明确「data/ 数据不入库，两端各自维护」），迁移脚本在两端行为不一致，或一端数据被另一端模式覆盖；或用户在迁移中途打开了正在运行的服务，读到一半的旧路径。
- **Evidence（已取）:** 本机 data/（orders/、metrics/）与 coupon_data/（scenarios/runs/decisions/reviews/profiles）均有真实内容；output/ 有生成的报告与中间指标。.gitignore 忽略 data/、output/、coupon_data/——git 里没有任何数据，迁移不能靠版本控制回滚。
- **Kill criterion:** 迁移逻辑出现「复制后删除源」且无法 dry-run / 无法冲突提示 → 停止，改为显式迁移脚本 + 人工确认。
- **Cheapest test:** 迁移函数写成纯函数（给定源/目标目录返回操作计划），先用 tmp 目录单测，再对真实目录执行。

### K2 — 收编后「引擎不动、存量测试零断言修改」仍成立
- **Claim:** 数据目录改到 workspace/ 后，113 项测试仍然全绿、断言零修改。
- **Steelman:** 测试的数据目录全部参数化（test_coupon_server.py 用 tmp_path_factory；test_server.py 用 WorkbenchState(ROOT) 但 data/ 收编后 ROOT 下无 data——这是真实断点）；引擎读的是构造参数，不是硬编码路径。
- **Fails if:** target_forecast 的 demo 生成、模板生成、report 输出路径与 data/ 收编纠缠（demo.generate(ROOT) 写 data/orders，report 写 output/），一处漏改导致 demo 数据写到旧位置被「空目录自动生成演示数据」逻辑反复触发。
- **Evidence（已取）:** test_server.py 的 fixture 直接 `server.WorkbenchState(ROOT, ...)`，其 load() 在 root/data 为空时自动生成演示数据到 root/data——收编后 ROOT/data 不存在，必须在 fixture 或 WorkbenchState 参数上调整（属于测试设施改动，非断言改动，PRD 需明示允许）。
- **Kill criterion:** 任何业务断言需要修改才能过 → 迁移破坏了行为，回退该改动。
- **Cheapest test:** 收编切片完成后立即全量 pytest（4-7 秒，成本极低）。

### K3 — 统一导出通道有真实第二用户（forecast 的报表下载）
- **Claim:** 统一导出约定值得建：forecast 的 Excel/CSV 产出现在无下载通道，P1 补上后用户会在工作台里下载。
- **Steelman:** 现状 output/目标测算报告.xlsx 只能去 Finder 找；工作台内直接下载是明显体验增益；coupon 已有成熟导出模式可参照。
- **Fails if:** forecast 的报表生成只在 CLI run 路径（main.py run），serve 路径从不生成文件——为下载通道要在 serve 路径新增「生成报表」能力，这超出「统一导出」变成「新增功能」，违背不过度设计。
- **Evidence（已取）:** report.py 由 main.py run 调用；server.py serve 路径只有 /api/calc JSON，从不写 Excel。即 forecast 当前在壳内根本没有可下载的产物。
- **Kill criterion:** 统一导出需要为 forecast 新增报表生成逻辑 → 收缩范围：P1 只统一 coupon 现有导出 + forecast 已有磁盘产物（若有）的下载，forecast serve 内生成报表推到 P2 之后单独评估。
- **Cheapest test:** PRD 阶段逐条列出「导出通道服务的产物清单」，凡清单外的一律不做。

### K4 — 状态栏需要壳级聚合而非展示位
- **Claim:** 统一状态栏要做跨工具状态聚合（数据源、演示/正式、最近测算时间）。
- **Steelman:** 壳 /api/state 已有工具清单；各工具 /api/state 已含 demo_used/coupon scenarios——聚合成本低。
- **Fails if:** 「最近测算时间」等状态需要插件协议新增接口（actions 之外再加 status 上报），而各工具状态语义不同（forecast 的 calc 在内存、coupon 的 run 落盘），聚合层要为两个工具各写适配——底座再次长出工具特定代码，违背 K5/G7 教训。
- **Kill criterion:** 状态栏信息无法从工具现有 /api/state 响应直接得到 → 该信息不进 P1 状态栏。
- **Cheapest test:** 列出状态栏字段清单，逐字段标注来源端点已存在/需新增。

### K5 — 设计语言精修范围可控
- **Claim:** 壳 UI 对全局 DESIGN.md「完整对齐」是小改动。
- **Steelman:** P0 壳已用 Xanthil token（底色/侧栏/圆角），diff 应集中在状态栏与细节密度。
- **Fails if:** 「完整对齐」被解释为逐 token 审计 + 全套组件（命令面板/Inspector/语义色对），P1 范围爆炸。
- **Kill criterion:** 设计语言切片出现与「侧栏 + 状态栏 + 内容区」无关的组件工作 → 砍。
- **Cheapest test:** 设计切片只列 P1 新增/修改的具体 token 与组件清单。

## What's Well-Reasoned

- 数据收编方向正确：workspace/{tool_id}/ 消除顶层 data/ 与 coupon_data/ 的散落，与 P0 插件协议的 root 约定自然衔接（plugin 构造时已有 root 参数）。
- 迁移路径面极小且已枚举，K1/K2 的成本边界清晰，风险主要在「自动迁移的行为定义」而非「改哪里」。
- 不动引擎、不动口径的边界继承自 P0，继续有效。

## What I Couldn't Assess

- MacBook 端 data/ 与 coupon_data/ 的实际内容（只能本机验证迁移；需靠 fail-closed 迁移逻辑 + 双端各自执行保证安全）。
- 用户对 forecast serve 内生成报表的真实需求强度（K3 的方向选择影响范围，留给 GRILL 推荐）。

**Verdict: GO** — 无已满足 kill criterion 的假设；K1-K5 均给出可执行的 kill criterion 与最便宜测试，PRD 可直接吸收。
