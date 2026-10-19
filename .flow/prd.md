# PRD：经营目标测算正式实现（target-forecast）

来源：`.flow/proposal.md`（已批准方案 v0.1 + 用户 2026-10-19 启动决定，逐字钉入）+ `.flow/red-team.md`（GO，5 个 kill-assumption 已登记处置）。无 issue tracker，按 fallback 落盘本文件。

## Problem Statement

经营/分析人员要把一个经营期待（如"明年净 GMV 1.28 亿"）变成有数据、有假设、可比较、可保存、可复查的测算方案时，现有 target-forecast 工具做不到：

1. **没有"方案"对象**：参数散落在 config.yaml（CLI/默认值）、assistant_params.json（AI 写入）、页面临时态（POST /api/calc 无状态）三处，互不同步；结果是固定文件名的一次性 output，页面"导出"读的是最近一次 CLI 产物，无法回答"这份报告是哪份输入算的"。
2. **引擎有 5 个已确认正确性问题**（红队现场复核）：全模式A（无 UV）下全渠道汇总直接 KeyError 500；SKU 梯队划分索引错配（5 元的款被标成爆款）；短历史（如 4 个月）的"基期年化 GMV"是 4 个月求和而非年化，增速虚增约 3 倍；同名平台 A/B 两种文件后读覆盖先读；全渠道客单用混合视角分母。另有平台间目标期错配可能产生"看起来合理"的错误合计。
3. **AI 与手动两张皮**：助手调参写 assistant_params.json，旧前端仅在启动时读取合并一次，服务端 /api/calc 从不合并它、也不与工作稿同步；提案无修订绑定，过期提案可能覆盖新修改。

## Solution

按已批准的方案与 UI demo 做正式实现，本轮只完整交付**经营目标测算**这一个工具：

- 一个持续可修改的**方案工作稿**（目标/范围/数据引用/口径/情景假设/依据/采用档/修订号），手动编辑、AI 采纳、CLI 都经过**同一个业务更新入口**。
- **数据快照 / 方案版本 / 运行记录**都有明确身份；保存后的输入与结果不可变；重复保存去重；工作稿变更使相关确认与计算结果按规则失效，过期结果可查看、可导出，但不能冒充当前结果保存。
- 本地文件持久化：原子写、内容身份、冲突检测、关闭重开恢复；不引入数据库。
- 五个工作视图的已批准 UI 落地为真实界面，接真实引擎与磁盘存储；AI 未配置时手动流程完整可用。
- 引擎 5 个正确性问题先修正再复用，修正用"有业务期望的最小测试"验证，并用真实工作区做修正前后差异对照（diff-map），不把旧错误指纹化。

优惠券、ROI 保持现有行为不变；本轮不做 JuanerAI 集成、不改共享 pi runtime、不调真实付费模型。

## User Stories

目标与起点：
1. 作为经营人员，我想用一句业务描述开始（"明年净 GMV 增长 20%，新客和复购分别要做到多少？"），形成一份可以直接修改的工作稿，而不是先填专业参数问卷。
2. 作为经营人员，我希望描述里没说明白的信息（目标金额、平台、口径）保持"待确认"，系统不替我静默套默认值。
3. 作为经营人员，我希望完全不用 AI 也能走完：手动创建目标、导入数据、设假设、计算、保存、导出。
4. 作为经营人员，我想从现有 config.yaml / workspace 旧输入一键创建方案，并看到来源记录与差异预览。

数据准备：
5. 作为分析人员，我想在界面里选择订单明细（模式A）或平台月度指标（模式B）的 xlsx 文件，预览前几行、确认字段映射，而不是手工把文件放进源码目录。
6. 作为分析人员，我想看到数据检查清单：必需字段、日期/月份有效性、金额为有限正数、平台+月份唯一、期间覆盖、订单身份一致性、零总量，异常定位到文件/行/列，而不是一个 HTTP 500。
7. 作为分析人员，同一平台同时存在明细和月度文件时，我要显式选择用哪份，系统不允许后读覆盖先读。
8. 作为分析人员，多平台期间不一致时，我要看到并确认缩短范围或排除平台，系统不静默补齐。
9. 作为分析人员，没有 UV 时场视角明确显示"缺少流量数据，未启用"，人视角照常可用，系统不编造 UV、不把缺失当 0。
10. 作为经营人员，我确认口径后，如果之后换了数据，口径确认要失效并提示我重新确认。

假设与情景：
11. 作为经营人员，我要为三档（保守/基准/挑战）分别编辑人视角驱动假设，每项假设记录来源类型、解释、适用范围与待验证事项；数据不支持的参数不显示成可生效输入。
12. 作为经营人员，"确认用于试算"只表示本次条件推演可用，系统不得把假设标成已验证事实；改动假设后确认失效。
13. 作为经营人员，我手动保存的修改和 AI 采纳的修改必须落在同一份工作稿上，立即互相可见。

计算与比较：
14. 作为经营人员，数据/口径/假设未就绪时计算按钮不可用，并告诉我缺什么、去哪补。
15. 作为经营人员，计算状态至少区分：准备不足、计算中、已完成、失败、已取消、执行结果未知；失败或停止不写入半结果，工作稿和旧运行保留。
16. 作为经营人员，三档结果用同一数据同一口径比较：各档净 GMV、较基期变化、距目标差距、月度分布、平台贡献、人/货/场一致性；比率分子分母同视角同覆盖。
17. 作为经营人员，我选择"采用"某档只是讨论选择，系统不自动宣称推荐。

保存与导出：
18. 作为经营人员，我点"保存方案与本次运行"后，方案版本与运行快照被固定；同内容重复保存返回已有版本/运行，不增生记录。
19. 作为经营人员，工作稿再修改后，旧运行仍可查看和导出但明确标注来自旧版本；当前工作稿必须重新计算才能保存。
20. 作为经营人员，导出的 Excel 报告/中间指标 CSV/JSON 快照必须绑定我指定的运行，带输入与参数来源、方案版本、运行时间和口径；绝不下载到"最近一次 output"。
21. 作为经营人员，导出失败时显示"运行已保存，导出失败可重试"，重试不重新计算。
22. 作为经营人员，关闭重开工作台后，我的工作稿、版本和历史运行都在。

AI 协作：
23. 作为经营人员，AI 读取的是当前方案及修订，提案必须展示旧值、新值、理由、影响范围（会失效哪些确认）。
24. 作为经营人员，采纳后修改经统一入口生效，手动视图立即一致；放弃零变更。
25. 作为经营人员，提案生成后我又手动改过，旧提案不能覆盖我的新修改（提示重新生成）。
26. 作为经营人员，重复点采纳/确认不能产生重复业务效果；网络恢复后结果不确定时系统先查状态而不是盲目重试。
27. 作为经营人员，AI 未配置或失败时，我看到的助手状态是如实说明，手动流程不受任何影响。
28. 作为分析人员，原始订单明细不默认发送给模型；模型只能拿到方案摘要、质量问题与受限工具读取的结果。

兼容与边界：
29. 作为老用户，旧 Excel/CSV 产物被标为"旧版产物，未关联新运行"，可以下载，但系统不伪造它的输入快照与版本链。
30. 作为老用户，优惠券和 ROI 工具的入口、页面、测算行为与导出保持原样。
31. 作为审核者，页面上凡是未接入真实能力的地方都不得显示成生产执行成功（A15）。

## Implementation Decisions

### D1. 分层与新模块

在业务层新增一个包 `target_forecast/plans/`（纯 Python，无 HTTP 依赖），它是**唯一业务更新入口**：

- `models.py`：领域对象与序列化——PlanDraft（工作稿：goal/scope/period/platforms/caliber/assumptions 三档+依据/selected/data_ref/confirmations/revision/changes）、DataSnapshot、PlanVersion、RunRecord、ExportRecord、AIProposal。
- `store.py`：本地文件持久化——`workspace/forecast/v2/` 下 `plans/<plan_id>/{draft.json, versions/, runs/}` 与 `snapshots/<snapshot_id>/`；所有写 = 写临时文件 + `os.replace` 原子替换；draft 写带 `base_revision` 乐观并发（不匹配 → ConflictError）；启动时校验 JSON 可解析，损坏文件隔离为 `<name>.corrupt-<ts>` 不覆盖。
- `service.py`：业务操作——create_plan（含 from_config 导入，记录来源并冻结当时值）、update_draft(patch, base_revision, source∈{manual, ai, cli, import})、confirm(kind∈{caliber, assumptions}, base_revision)、import_data(文件→检查→快照)、resolve_source_conflict(显式选源)、propose_change（AI 提案 dry-run：返回 旧值/新值/影响范围/将失效确认/base_revision，不落盘业务参数）、apply_proposal(proposal_id, base_revision)、discard_proposal、start_run（冻结内容键→job）、cancel_run、save_run（幂等去重）、export_run(run_id, format)（失败可重试、不重新计算）。
- 引擎/ingest/pipeline/aggregate/report 保持模块边界，由 plans 层调用；HTTP 路由、CLI、assistant 执行器都只调 plans 层。

### D2. 身份与失效规则

- `plan_id` = `plan-<yyyymmdd>-<4位随机>`；draft.revision 单调递增；每次 update 追加 changes（来源+说明+revision，保留最近 50 条）。
- 内容分三组失效域：**data**（数据快照引用）、**caliber**（口径参数）、**assumptions**（三档参数+依据）。每个域存内容哈希；确认记录 = {kind, domain_hash, at_revision}；域内容变化 → 哈希不匹配 → 对应确认失效（UI 显示"需重新确认"）。标题/业务描述等不属于任何域，改动不失效确认。
- `snapshot_id` = 内容哈希（统一月度指标+货结构+字段映射+来源文件哈希）`snap-<sha256前12>`；被运行引用后不可变；替换数据 = 新快照。
- `version_id` = 内容哈希 + 用户可读名 `v1.0 / v2.0…`（按该方案版本数递增）；同内容去重。
- `run_id` = `RUN-<方案内序号>`（展示）+ 内容键（版本内容 + 数据快照 + 引擎版本）用于幂等：同键重复保存返回已有运行。
- 运行结果状态机：`preparing|running|done|failed|cancelled|unknown`；save_run 只接受与当前工作稿内容键一致的 done 计算；工作稿变更后旧运行标注"来自旧版本 rN"，查看/导出不受影响。
- 引擎版本：`ENGINE_VERSION` 常量（本轮修正后从 `forecast-engine-1.1` 起），运行记录携带；引擎变更后显式重跑 = 新运行身份，不覆盖旧结果。

### D3. 引擎与流水线修正（阶段 A，红队 kill-1 处置）

修正清单（每项配"有业务期望的最小合成测试"，先红后绿）：
1. **无 UV 缺列**：`aggregate.consolidate` 在 field_all 为 None 时不再引用不存在的 UV 列；输出显式"无UV数据"口径标记。
2. **SKU 梯队索引**：`_assign_tiers` 返回带原索引的 Series，赋值按索引对齐，禁止 `.values` 错位；测试用未排序 SKU 验证"5 元的款不是爆款"。
3. **短历史年化**：`baseline.annual_gmv` 当窗口不足 12 个月时按月均×12 年化，并输出 `coverage_months` 与年化标记；平台年度增速基于年化口径；UI/报告展示覆盖月数。
4. **同平台 A/B 冲突**：`pipeline.ingest_platforms` 检测同名平台双来源时不再覆盖，返回冲突清单由调用方显式选择（CLI 报错列选项；UI 走选择流程）。
5. **混合视角分母**：全渠道客单 = 主口径GMV ÷ 主口径订单数（同视角）；转化率仅覆盖填报 UV 平台（已有），口径标记保留。
6. **平台目标期对齐**：共同基期末月 = 各平台历史末月的最大值；目标期 = 共同末月之后连续 12 个月；平台历史不足共同末月的，缺月计入质量问题清单并需用户确认（缩短范围或排除平台），不静默错配。

**diff-map 对照**：修正前先对真实 workspace（天猫/京东/抖音明细 + 私域月度）跑一次完整 pipeline 冻结输出；修正后复跑，所有数值差异必须能归因到上述具名修正之一，否则停下来查（红队 kill criterion 1）。对照证据存 `.flow/engine-diffmap/`（机器可读 + 一页摘要），不入 git 产品路径。

### D4. 计算任务异步模型（红队 kill-3ii 处置）

- plans 层提供 `start_run`：冻结内容键与快照引用，登记 job（内存注册表 + 磁盘 run 记录 `running`），线程执行，平台间检查取消旗标；`cancel_run` 置旗标 → 状态 `cancelled`（已算部分丢弃，不写半结果）。
- 进程崩溃/关闭时 `running` 恢复为 `unknown`（重开可见"执行结果未知"，可重新计算，不产生重复效果）。
- HTTP：`POST /t/forecast/api/v2/runs` → 202 {job_id}；`GET .../runs/{job_id}` 轮询状态；`POST .../runs/{job_id}/cancel`。失败保留错误分类与用户可继续的说明。
- 旧 `/api/calc` 同步路径在本轮结束后不再被新 UI 使用（见 D8 兼容处置）。

### D5. UI 落地（阶段 C；已批准 demo 为实现基线）

- 批准基线 = 审核包 `index.html + style.css + app.js + model.js`（`demo.html` 为其单文件打包）。新 UI 代码落在 `target_forecast/static/v2/`（`index.html/style.css/app.js/api.js`），沿用已批准的布局、五视图、右侧 AI 提案、弹窗、toast、亮暗主题、窄屏与键盘行为，逐视图把演示数据层替换为真实 API：
  - model.js 的本地计算/提案模拟/localStorage 全部删除，由 `api.js`（fetch 封装 + 错误分类）替代；业务恒等式（重复保存去重、过期拦截、失效规则）以服务端为准，前端只做呈现与即时反馈。
  - 首页自然语言：无 AI 时"形成草稿"= 原样保存描述并列出待确认项（不假装理解了文本）；AI 可用时由助手动作为草稿补全并标注待确认项。
  - 数据视图：真实文件选择（`<input type=file>` → 浏览器读字节 → `POST` 原始字节 + `X-Filename`）、映射预览（前几行+字段下拉）、质量清单（文件/行/列定位）、来源冲突选择、覆盖缺口确认。
  - 计算视图：job 轮询；停止=cancel；失败/取消/unknown 状态如实呈现；"工作稿已修改，以下仍是上次计算"过期横幅。
  - 保存导出视图：保存按钮在内容键不一致时禁用并解释；运行列表查看快照/导出三格式（xlsx 报告、中间指标 CSV、JSON 快照）；导出失败可重试。
  - 报告：复用 `report.py` 生成 xlsx（从运行快照构造，新增方案版本/运行时间/口径 sheet 信息），另提供中间指标 CSV 与 JSON 快照；demo 的 HTML 报告不作为正式产物。
- **托管决策（红队 kill-3i 处置）**：新 UI 是完整产品 chrome（自有 230px 侧栏/64px 顶栏/286px 助手），**不嵌入旧壳 iframe**（避免双 chrome）。workbench 壳做一处**可加性**改动：插件 manifest 新增可选字段 `standalone: true` 时，壳导航该项以整页方式打开 `/t/forecast/`（同标签跳转）；coupon/ROI 两个插件不设置该字段，iframe 行为与壳 chrome 完全不变。`main.py serve` 独立入口同步服务新 UI。
- 旧工具页（`target_forecast/static/` 现况）被新 UI 取代——本工具正在重构，属本轮范围；旧 Excel/CSV 导出在新 UI 中以"旧版产物"区保留下载。

### D6. AI 接入（阶段 D；复用现有 sidecar 架构）

- 架构不动：shell `/api/assistant/chat|stage|exec_read|exec_write` ↔ `AssistantService` ↔ sidecar（pi loop）。新 UI 的右侧 AI 面板直接调这些壳级端点（新 UI 是整页，不经 iframe，但同源同端口）。
- forecast 插件 `actions` 重做到 plans 层：读=`get_plan_state`（当前方案修订+确认状态+质量问题+最近运行摘要）、`compare_runs`；写=`propose_plan_changes`（dry-run 产出提案卡：旧值/新值/理由/影响/将失效确认/base_revision）与 `apply_proposal`（write，确认门后执行；服务端校验 proposal 摘要 + base_revision + 幂等 call_id；过期/冲突 → 拒绝并提示重新生成，零变更）。
- 修订绑定：提案对象存 base_revision；apply 时 draft.revision 必须等于 base_revision，否则提案标记 expired，不执行。
- 幂等与恢复：沿用 (c)-resume 的 call_id 一次性与"结果不确定先读回状态"语义；重复确认返回首次结果，不重复写。
- sidecar 唯一修正：`/health` 的 `sdk` 字段改为读取已安装 pi-agent-runtime 的真实版本（当前证据 = **0.5.3-harness.3**，软链解析值；proposal 据此覆盖 0.4.3 旧叙述）。不改 pi-agent-runtime 共享仓。
- 原始订单明细不进模型上下文：system 注入只带轻量元信息，数值经受限工具现取（沿用 G3）。
- 无 key/无 sidecar → 面板如实显示"助手未配置（回放/不可用）"，手动流程不受影响（A15）。
- **真实付费模型不调用**（用户已明确）：AI 链路用契约测试（sidecar 假 transport + service 层 FakeSidecar）与真实冒烟（不起真实模型，验证 stage→confirm→exec_write→draft 落盘链路）验收；"真实模型质量"标注为未验证项。

### D7. 持久化与兼容（阶段 B/E 交叉）

- 新存储根 `workspace/forecast/v2/`（gitignore 已覆盖 workspace）。首启不自动迁移任何旧文件。
- "从现有配置创建方案"：读取 config.yaml 三档参数与口径 → 生成工作稿，changes 记录来源 `import:config.yaml@<hash>`，冻结当时值（之后 config.yaml 改动不影响已建方案）。
- `workspace/forecast/orders|metrics`：作为"从工作区目录导入"的显式选项读取（不自动改名/删除/覆盖），导入即生成数据快照。
- `assistant_params.json`：当前不存在（红队核实）；若出现，在新建方案时提供差异预览，用户确认后并入，未知字段列明。
- 旧 CLI（`main.py run|demo`）保留可用，输出仍写 `workspace/forecast/output/` 并在报告中标注"旧版产物，未关联新运行"；**旧路径绝不写入 `v2/` 存储**，新运行也绝不写固定文件名 output。页面"旧版产物"区读取 output/ 列表提供下载。
- `workspace/forecast/output/目标测算报告.xlsx` 等现存文件不移动、不删除。

### D8. 退役边界

- `/api/calc`、`/api/state`（旧 forecast 无状态接口）与旧静态页：本轮结束后不再服务（插件路由切换到 v2 页面与 v2 API）；`tests/test_server.py` 中针对旧接口的用例随之更新或删除并在 PR 说明。
- 旧 `/api/export/report|metrics`（读固定文件名）：保留但响应头/页面标注旧版产物。
- coupon/ROI 的所有路由、测试、行为不动（回归由现有测试套件保证）。

### D9. 范围与预算护栏（红队 kill-5 处置）

- 预估切片见 tasks.md（ISSUES 阶段产出，含依赖序）。
- 预算耗尽时的降级顺序（预先登记，非授权裁剪）：① AI 真实模型验收本就不在本轮（契约测试为准）；② 若仍不足，暂停在"手动主流程完整 + AI 提案链路契约测试通过"的完整可交付点，向用户报告后再继续。**不**通过简化已批准交互来赶进度。
- 引擎修正 diff-map 出现不可归因差异 → 暂停升级（kill-1 criterion）。

## Testing Decisions

好测试的标准：断业务期望与外部行为，不断实现细节；修正类测试必须先红（对具名 bug 给出期望业务结果）。

- **plans 层（新）**：`tests/test_plans.py` 等——tmp_path 上的草稿 CRUD、修订冲突、三组失效域、提案生命周期（采纳/放弃/过期/幂等）、保存去重、导出绑定与重试、崩溃恢复（corrupt 隔离、running→unknown、原子写）。纯 Python，无 HTTP。
- **引擎修正**：`tests/test_engine_fixes.py`——6 个具名修正的最小合成用例（无 UV 汇总不炸且口径标记正确；未排序 SKU 梯队；4 个月历史年化=月均×12；A/B 同名冲突返回而非覆盖；客单同视角分母；跨平台目标期对齐+缺口确认）。
- **diff-map**：脚本 `scripts/engine_diffmap.py`（或 .flow 工具脚本）对真实 workspace 修正前后输出做逐表对照，差异归因清单为验收证据。
- **HTTP 层**：沿用 `serve_background` 模式（test_server.py/test_workbench.py 先例）测 v2 路由：上传→检查→快照→确认→job→保存→导出全链 + 错误分类（422/404/409）+ 旧接口退役行为。
- **sidecar/assistant**：`node --test` 现有用例保持绿；新增/更新：/health 版本上报、propose/apply 修订绑定与幂等（service 层 FakeSidecar 先例）。不新增真实模型调用。
- **浏览器验收（A14 等）**：Playwright CLI + 已安装 Chrome（沿用审核包 browser-check.js 模式），本地服务真实数据，覆盖：五视图主链、提案采纳/过期、保存去重、过期拦截、导出下载核对、1440/390、亮暗、键盘与 dialog、无 UV 平台场视角降级。截图存审核证据目录。
- **真实依赖用例（强制）**：真实 workspace 四平台（约 5.8 万行明细 + 月度指标）走完整 HTTP 链路一次，结果与 plans 层直算一致。
- **verify_command**：`.venv/bin/python -m pytest -q`（全仓）；sidecar 改动时追加 `(cd assistant-sidecar && npm test)`；浏览器脚本作为验收证据附在 SHIP 前。
- coupon/ROI/旧 workbench 测试全量回归，不得变红。

## Out of Scope

- 优惠券与 ROI 工具的任何重构/机制复用（阶段 E 另行立项）；它们的现有行为保持。
- 真实付费 LLM 调用与模型质量验收（需用户另行授权；本轮 AI 仅契约级验证）。
- 前端框架迁移、数据库引入、通用 Agent/插件平台、JuanerAI 集成、共享 pi runtime 或其他仓库的修改。
- 自动抓取平台数据、执行投放、真实资源优化、因果识别、统计预测准确性承诺、自动经营决策。
- 账号/权限/多人协作；多工作空间。
- 非完整 12 个月目标期的产品化（目标期固定为共同末月后 12 个月；覆盖缺口走确认流程）。
- 旧 output 产物的物理迁移/删除。

## Further Notes

- 红队裁决 GO；kill-assumption 处置：①→D3 diff-map；②→D1 单一入口+D7 旧路径冻结（CLI 经 plans 层只读复用，不写新存储——决策：旧 CLI 保持 legacy，不升级为产生新运行，避免半过渡态）；③→D4 异步+D5 standalone 整页；④→D6 契约测试+版本修正；⑤→D9。
- 已批准 UI 不可简化：任何"原型只是 demo"式的交互削减都属 spec 违例（REVIEW 重点）。
- 状态显示不是单个大绿灯：工作稿已保存/口径已确认/假设已确认/计算完成/运行已保存/文件已导出分别可见。

---

## PRD diff gate 记录（2026-10-19, auto）

相对 proposal.md 的增/改/删决策点：
- 全部为**纯增量实现细节**：D1 模块结构与存储布局、D2 身份/失效规则、D3 六项修正的具体公式、D4 异步 job 模型、D5 standalone manifest 标志与 static/v2 位置、D6 动作命名与 /health 修正、D7 旧 CLI 冻结为 legacy（proposal §7 过渡策略的落地选择）、D8 旧接口退役边界、D9 预算护栏。
- 无任何"改变或删除 proposal 已批准决定"的条目（已批准 UI、A01–A15、兼容策略、边界全部保留）。
- auto 模式：纯增量 → 自批准，记录于此。

---

## GRILL 第 1 轮决议（2026-10-19，作者盲审子代理，9 包全部按推荐采纳）

已逐包对照 proposal.md 验证：无冲突项，全部回答 proposal 留白。以下并入 PRD 决策：

**G1. 口径参数二分（包1→D2/D3 修订）**：caliber 键分两类——
- *ingest 期*：`new_customer_window_days`、`goods_window_months`、`tier_scope`、`tier_pareto_pct`、`tier_tail_pct`、`new_product_days`。导入时取值并**冻结进数据快照**（快照记录取值）；被快照冻结后，修改这些键 = 重新导入产生新快照（走 data 域失效），draft 中对已引用快照显示只读。
- *引擎期*：`baseline_months`、`target.months`。留在 draft 的 caliber 失效域，可编辑，改动失效口径确认。
- 运行内容键 = 版本内容（含引擎期口径）+ 快照（含 ingest 期口径冻结值）+ 引擎版本。

**G2. AI 提案双轨合一（包2→D6 修订）**：
- `propose_plan_changes` = 只读 dry-run 动作，但其执行器在 plans 层**持久化 AIProposal 记录**（提案是生命周期对象而非业务参数变更，执行器 docstring 钉死此例外）；提案卡渲染/采纳/放弃走 v2 API，壳 `_pending` 只承载 apply 这一次确认。
- base_revision 由 `get_plan_state` 返回 → 模型回传 → 提案落盘绑定；apply 时模型只传 proposal_id，服务端校验 revision 相等，不依赖模型透传修订号。
- `_EXECUTORS` 未命中兜底从"假成功"改为 raise（422），钉死"未实现的执行器不返回假成功"；forecast 旧 `get_state` 动作随 D8 退役，避免共享快路径打向已退役端点。

**G3. job/run 两层身份（包3→D2/D4 修订）**：
- `job_id`：每次计算尝试唯一（含 done/failed/cancelled/unknown），磁盘留痕供状态查询与恢复；done-未保存的 job 结果存盘，计算视图带"未保存"标记可查看；job 不进"运行记录"列表。
- `run_id`：仅 save_run 成功时铸造（RUN-<方案内序号>），对外展示与导出绑定。
- 刷新恢复：draft 与已保存 run 由服务端恢复；localStorage 只允许存"当前方案指针 + 未保存 job_id"，内容一律从服务端按 id 取回。

**G4. 数据质量三级分类（包4→D1/D2 修订）**：
- **blocker**（拒绝生成快照）：缺必填列、无法解析日期/月份、金额非有限数或非正、平台+月份重复、零总量、同批平台名重复。
- **confirmable**（快照可生成，计算前须逐项确认/处置）：平台内缺月（season 填充保留但快照与报告标注"缺月已按均值填充"）、短历史年化、跨平台末月缺口、A/B 同名来源冲突、GMV/转化率校验超阈。
- **warning**：仅展示。
- confirm kind 扩为三种：`data_coverage / caliber / assumptions`，全部走 D2 域哈希失效。

**G5. 上传两阶段协议（包5→D5 修订）**：
- `POST /t/forecast/api/v2/uploads`（原始字节 + X-Filename → 存 `v2/_staging/<upload_id>/`，返回列清单与前 5 行预览）→ `POST .../plans/<id>/import`（upload_id + 平台名 + 字段映射 → 检查 → 快照 → 清 staging）。
- 平台名以用户确认值为准（默认取文件名 stem，可改）。
- ingest 同步执行（本地 pandas 秒级），取消语义只承诺到计算 job（A09 原文即"计算可停止"）；staging 超 24h 未应用由启动时清理；崩溃不留半快照（原子写）。
- 映射以规范化映射表（原始列名→canonical 字段）入快照并参与内容哈希；快照保留源文件字节副本（不可变，供复查）。

**G6. standalone 导航回路（包6→D5 修订）**：
- v2 顶栏加"← 返回工作台"链接（检测到同源壳时显示）——对已批准 chrome 的最小增量，REVIEW 时单独标注此 deliberate-change。
- `standalone` 加入 Registry MANIFEST_KEYS 白名单并在 registry docstring 钉协议；`?tool=forecast` 深链继续有效（壳读取后整页跳转）。
- api.js 全相对路径；`main.py serve` 独立入口挂载 v2 API，无 workbench 时助手面板显示"standalone 模式无助手"（如实，不冒充未配置）。

**G7. 退款净额口径（包7→D3/D5 修订）**：
- 维持"实付金额必须为正，负行/零行 = blocker"，错误信息定位到文件/行并说明处置（"请按净额口径导出或剔除退款行"）；口径确认清单增加显式条目"实付金额=支付净额（已扣退款），本工具不再做退款抵减"。
- 真实净额抵减计算（负行支持/退款列）超出本轮边界，记入 handoff 未决项，不在本轮实现（避免 diff-map 出现不可归因差异）。

**G8. 导出产物协议（包8→D1/D2 修订）**：
- exports 存 `plans/<plan_id>/runs/<run_id>/exports/<format>`，一律 tmp+os.replace；重试 = 从 RunRecord 持久结果**重新渲染**（结果负载为 run 目录下 JSON 快照文件，随 run 原子写）。
- 同格式重复导出去重返回已有文件（导出身份 = run_id+format+渲染器版本，生成时间不参与去重）；xlsx/csv/json 三种格式全部内嵌方案版本/运行 ID/口径/输入来源。
- 启动时 `.corrupt` 隔离检查覆盖 exports；v2 API 所有 JSON 响应先经 NaN 清洗（沿用 _sanitize 先例；httpkit json allow_nan=False 是硬约束）。

**G9. 演示入口与 A15 落点（包9→D5 修订）**：
- 保留"载入示例"显式动作：内置合成数据走正常 import 管道生成带 `synthetic:true` 的快照，数据/运行/导出全程带演示标记；v2 取消空目录自动播种（该行为随旧 server 退役）。
- demo-only 元素清单（REVIEW 逐项对照）：顶栏"交互原型 · 合成数据"标签→真实数据源徽标；首页 workflow-note→删除；侧栏"重置演示数据"→删除；"↗ 重构方案与审核说明"外链→删除。
- 助手面板三分态文案钉死：已配置（真实模型，本轮未验收）/回放或不可用（如实标注）/standalone 无助手。

轮次依赖说明：包1→3→2 锁定 models.py/store.py schema，为后续所有切片地基；已在 ISSUES 排序中体现。

---

## GRILL 第 2 轮决议（2026-10-19，主代理自审，9 包全部按推荐采纳；无升级项）

**G10. v2 API 路由与错误语义**（全部挂在 forecast 插件 `/t/forecast/` 前缀下；standalone serve 时挂 `/api/v2/...`）：
- `GET api/v2/state`：方案列表、最近编辑、运行汇总、能力标记（assistant_backend、engine_version、storage 状态）。
- `POST api/v2/plans`：创建草稿（{need, title?} 或 {source:"config"}）；config 创建在响应中带来源与取值展示。
- `GET api/v2/plans/<id>`：草稿详情（revision、三域确认状态、质量清单、pending 提案、最近 job、runs 摘要）。
- `PATCH api/v2/plans/<id>`：update_draft {base_revision, patch}；修订冲突 → 409。
- `POST api/v2/plans/<id>/confirm`：{kind: data_coverage|caliber|assumptions, base_revision}。
- `POST api/v2/uploads` → {upload_id, 列清单, 前5行预览}；`POST api/v2/plans/<id>/import` {upload_id, platform, mapping, source_mode} → 快照+质量清单。
- `POST api/v2/plans/<id>/jobs` → 202 {job_id}；`GET api/v2/jobs/<job_id>`；`POST api/v2/jobs/<job_id>/cancel`。
- `POST api/v2/plans/<id>/runs` {job_id}：幂等保存（同内容键返回已有 200，新建 201）；内容键不符 → 409。
- `GET api/v2/runs/<run_id>`：快照详情；`GET api/v2/runs/<run_id>/export/<fmt>`：下载（缺失则渲染，失败 500 可重试，重试不重新计算）。
- `GET api/v2/plans/<id>/proposals`；`POST api/v2/proposals/<pid>/apply` {base_revision}；`POST api/v2/proposals/<pid>/discard`。
- 错误分类：400 结构错误 / 404 对象不存在 / 409 修订冲突·过期提案·过期计算 / 422 业务校验（质量 blocker、就绪检查）/ 500 未预期；错误体 {error, code, detail?, blocking?}，message 面向业务、可继续。

**G11. 内容键规范化**：`json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(",",":"))`，NaN/Inf 一律先转 None，浮点不取整；sha256 hex 前 16 位。适用于 snapshot_id、版本内容键、运行内容键、导出去重键。changes.source ∈ {manual, ai, cli, import}。

**G12. 目标期语义（v1）**：目标期 = 各平台共同基期末月之后连续 12 个月（engine `target.months`），用户不可另选起期；共同末月 = max(各平台历史末月)；平台缺口进 confirmable。目标与范围视图只读展示派生期间；自定义起期记入 handoff 未决项。

**G13. 假设元数据**：按情景存 {params, source_type: manual|ai|import, note（依据与边界）, scope_note（适用范围）, to_verify（待验证事项）}；假设表"依据与边界"列保留已批准 UI 的静态说明文案。新建空白方案的三档参数初值 = config.yaml 当前三档，changes 记录 `import:config.yaml@<hash>`；这不违反"不静默套默认"——假设域必须显式"确认用于试算"才可计算，且确认在数据/口径/假设任何变化后失效。

**G14. 提案粒度与生命周期**：提案 = {id, plan_id, scenario, patches: [{param, old, new}], rationale, impact: {invalidates: [确认域...], note}, base_revision, status, created}；单情景、多字段原子补丁。status: pending→applied|discarded|expired；**draft 每次变更主动把所有 pending 提案标记 expired**（响应返回 expired 列表，UI 即时禁用旧提案），apply 双重校验 revision。

**G15. CLI 同一入口**：`main.py` 新增薄壳子命令（全部只调 plans 层，零业务逻辑）：`plans`（列表）、`plan <id>`（详情）、`plan-create [--from-config]`、`plan-calc <id>`（同步等待 job）、`plan-save <id> --job <job_id>`、`plan-export <run_id> [--format xlsx|csv|json]`。旧 `run|demo|serve|templates` 原样保留。

**G16. 快照源文件副本**：快照目录保存源文件字节副本（不可变）+ 来源清单（原路径/文件名/mtime/sha256/演示标记）；从 workspace 目录导入同样复制。复查与"旧输入不被动"由此保证。

**G17. 前端恢复与轮询**：job 轮询 800ms；页面加载时按 localStorage 指针恢复当前方案，若其最近 job 为 running/unknown 则恢复轮询或显示"执行结果未知"；job 结果体（三视角月度×三档）内嵌 job 记录落盘；所有数值渲染只对已 sanitize 的 JSON 负责。

**G18. 旧测试处置**：`tests/test_server.py`（旧 forecast 接口）改写为 standalone v2 冒烟；`/api/calc` 参数裁剪用例迁入 plans 层测试；`tests/test_workbench.py` 保持绿并新增 standalone manifest 白名单用例；coupon/ROI 测试不动。

第 2 轮后无新增实质开放问题 → **GRILL converged after 2 rounds**（预算 2x9 用完且无遗留；无 proposal 冲突、无不可逆无推荐项，全程零升级）。
