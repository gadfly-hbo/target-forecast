# 验收映射：A01–A15 → 正式实现证据（切片 7，2026-10-19）

证据标注：〔本轮〕= 本 flow 实际验证；〔历史〕= 早前切片验证、本轮未重跑；〔未验证〕= 如实标注。
测试命令：`.venv/bin/python -m pytest -q`（本轮 303 passed）；`assistant-sidecar: npm test`（13 passed）。
浏览器证据与下载核对物：`workspace/forecast/acceptance-smoke/`（截图命名见下）。

| # | 可观察行为 | 实现与证据 | 标注 |
|---|---|---|---|
| A01 | 描述经营目标后进入可修改工作稿；不强制先选专业模板 | 首页自然语言输入 → `POST /api/v2/plans` 生成草稿进入目标与范围页（无可选项模板门槛）；"从现有配置创建"为显式入口而非默认。〔本轮〕浏览器冒烟：home→形成草稿链路；`ui-home-desktop-1440.png` | 本轮 |
| A02 | 数据未准备／口径未确认时不能计算 | `service.readiness()` 拦截 + `POST /plans/<id>/jobs` 422 带 issues 清单（"计算前还需要完成 N 项"+ 去完善按钮）；CLI `plan-calc` 同样拦截。〔本轮〕tests/test_v2_http.py::test_calc_blocked_422_when_not_ready、tests/test_cli_v2.py::test_cli_plan_lifecycle | 本轮 |
| A03 | 重复月份、非法金额、缺月能定位并拒绝应用 | `ingest_detail/ingest_agg.validate_*_frame` 定位化 blocker（重复月份、非正金额含净额口径说明、订单身份一致性、零总量）→ import 422 保留用户输入；缺月/短历史进质量清单不静默。〔历史〕tests/test_plans_data.py（质量三级）、tests/test_ingest_*；〔本轮〕真实工作区四平台导入质量 blockers=[]、覆盖 24 月如实列出 | 本轮+历史 |
| A04 | 手动保存假设后，AI 读取同一修订 | AI 动作经 v2 API 读同一份草稿（`get_plan_state` 读 revision/确认/质量）；手动与 AI 修改同走 `plans/service.update_draft` 唯一入口，changes 记录 source。〔本轮〕tests/test_assistant_service.py::test_forecast_get_plan_state_branch；真实回环 tests/test_assistant_http.py::test_confirm_apply_proposal_real_loopback | 本轮 |
| A05 | AI 提案先展示差异，放弃不改方案 | `propose_plan_changes` dry-run 持久化 AIProposal（pending），UI 右栏差异卡（旧→新）；discard 零变更。G2 双轨：采纳是用户显式动作。〔本轮〕tests/test_v2_http.py::test_proposal_flow_http、tests/test_plans_proposals.py、tests/test_assistant_service.py::test_forecast_propose_branch | 本轮 |
| A06 | 提案生成后再手动修改，旧提案不能覆盖 | 任何 update_draft 将 pending 提案置 expired（G14）；apply 校验 base_revision，ConflictError 零变更；UI 冲突提示"请重新生成建议"。〔历史〕tests/test_plans_proposals.py 过期/冲突用例；〔本轮〕apply 幂等用例 | 本轮+历史 |
| A07 | 修改数据或假设后，确认失效、结果过期 | 确认按三域内容哈希读侧派生失效；结果过期=job.content_key≠当前，保存 409 stale，UI 过期横幅+保存禁用。〔本轮〕真实工作区证据：改目标→stale save 409→重算 RUN-002→去重 200；RUN-001 未被覆盖（real-workspace-e2e.json）；tests/test_plans_jobs_runs.py::test_stale_save_rejected_old_run_untouched | 本轮 |
| A08 | 三档用同一数据比较，选档不自动宣称推荐 | 一次计算三档同数据同口径（run_content_key 不含 selected——选档是讨论选择）；结果表/月度图/平台贡献；badge"情景推演 · 非预测承诺"；无推荐话术。〔本轮〕`ui-results-real-data-1440.png`（真实数据三档 989/1059/1137 万） | 本轮 |
| A09 | 计算可停止／失败，保留工作稿与旧记录 | job 线程 + cancel 旗标；cancelled/failed/unknown 三态如实展示，不写半结果；崩溃重开 running→unknown。〔历史〕tests/test_plans_jobs_runs.py::test_failed_and_cancelled_jobs_leave_no_partial、test_running_job_recovers_as_unknown；〔本轮〕UI 停止按钮存在（本轮未触发真实中断） | 部分本轮 |
| A10 | 保存方案版本与运行，重复保存不增生记录 | 内容键幂等去重（同内容+同采用档 → 200 duplicate 返回已有运行）；版本 v1.0/v2.0 铸号去重。〔本轮〕真实工作区：RUN-002 重复保存 200 duplicate；tests/test_plans_jobs_runs.py::test_save_dedup_same_content | 本轮 |
| A11 | 编辑工作稿不改历史快照与下载内容 | 运行为独立快照（result.json 深拷贝+版本+快照引用）；导出绑定 run_id 读保存副本；编辑工作稿不动 runs/。〔本轮〕真实工作区：改目标后 RUN-001 摘要不变（runs 列表两条并存）；tests/test_plans_jobs_runs.py 覆盖 | 本轮 |
| A12 | 下载的报告／CSV／JSON来自所选运行 | `GET /plans/<pid>/runs/<rid>/export/<fmt>` 绑定运行；Excel 含运行身份块（方案/版本/运行/引擎/保存时间/输入来源/快照号）；失败可重试不重新计算；同格式去重。〔本轮〕`目标测算报告-RUN-001.xlsx`（含【运行身份】sheet 块）；UI 下载成功 `ui-export-modal-1440.png`；tests/test_v2_http.py::test_full_chain_http | 本轮 |
| A13 | 刷新后找回本浏览器的草稿与运行 | 服务端持久存储（workspace/forecast/v2/）+ localStorage 仅存 UI 指针（active plan/theme）；刷新后方案/运行/结果恢复（G17 轮询恢复）；断连显示"无法连接本地测算服务"警告。〔本轮〕浏览器刷新走查（compat-walkthrough 附注）；tests/test_plans_store.py 原子写/corrupt 隔离 | 本轮 |
| A14 | 1440 桌面、390 窄屏、亮暗主题、键盘及 dialog | 〔本轮〕`ui-home-desktop-1440.png`、`ui-results-dark-1440.png`、`ui-results-dark-390.png`、`ui-export-modal-1440.png`；Escape 关 dialog（快照 0 dialog）；首 Tab=「跳到工作区」skip link；aria-current/label 保留已批准标注 | 本轮 |
| A15 | 未接入真实能力不能显示成生产执行成功 | 全量扫描：UI 无 mock/fake/占位成功面；assistant 三分态（pi/回放/standalone 无助手）如实；`_EXECUTORS` 未命中 raise 拒绝假成功（test_missing_executor_raises_no_fake_success）；合成数据全程带「演示数据」badge 与报告 DEMO 标记；旧 CLI 冻结 legacy、旧产物标注未关联新运行。〔本轮〕扫描记录见 .flow/compat-walkthrough.md §5 | 本轮 |

## 真实工作区端到端（本轮）

- 计划 `plan-20261019-a940d4`（标题：2027 全渠道目标试算（真实工作区））：workspace 四平台导入
  （orders/天猫·抖音·京东 模式A 明细 + metrics/私域 模式B 含UV），快照 `snap-72f2da7ea5ba32c7`（synthetic: false）。
- 覆盖：4 平台各 24 月（2024-10~2026-09），无缺月/无 blocker/无 confirmable。
- 主口径：三个明细平台=人；私域（有 UV）=场；货视角仅明细平台启用——数据可用性如实驱动视角启用。
- 三档结果（元）：保守 9,891,934 / 基准 10,595,392 / 挑战 11,371,973（基期年化 9,760,653）；
  交叉校验：人 vs 货差 30.2% > 5% → UI 显示"需复核"（不粉饰）。
- 运行：RUN-001（目标 1.5 亿版）→ 改目标 1100 万 → 过期拦截 → RUN-002 v2.0（gap 40.5 万）；
  重复保存去重；三格式导出成功（xlsx 47.8KB / csv 7.4KB / json 688KB）。
- 证据文件：`workspace/forecast/acceptance-smoke/real-workspace-e2e.json`。

## 未验证项（如实标注）

- **真实模型质量**：本轮未调用付费模型（无授权）；AI 链路证据 = Echo 回放契约 + sidecar 假 transport
  契约测试（node --test 13 绿）+ 真实 HTTP 回环（stage→confirm→apply→draft 落盘）。模型输出质量、
  意图识别准确率未验证。
- **kill -9 中途写入恢复**：原子写语义由 tmp+os.replace 结构保证 + corrupt 隔离/running→unknown 测试
  覆盖；真实 kill -9 进程注入未在本轮演练。
- **浏览器真实下载的 CSV/JSON 二次打开核对**：xlsx 已核对（运行身份块）；csv/json 以字节数与
  Content-Disposition 验证，内容抽查 json 688KB 结构完整，csv 未逐行核对。
- **长时间并发（多标签同时编辑）**：ConflictError 机制有测试；多浏览器并发实测未做。
