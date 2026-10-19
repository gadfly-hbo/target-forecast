# Tasks：经营目标测算正式实现（dev-flow 切片）

无 issue tracker → 落盘本文件。切片 = tracer bullet 纵切；依赖序即执行序。GRILL 地基说明：G1(口径二分)→G3(job/run)→G2(提案) 锁定域模型 schema，S2 一次性落地。

- [x] 1. 阶段A：引擎六项正确性修正 + 真实工作区 diff-map —— 证据：tests/test_engine_fixes.py 9 用例先红后绿；全仓 250 passed；diff-map 差异全部归因修正2/5（.flow/engine-diffmap/ATTRIBUTION.md）
- [x] 2. plans 域层：草稿/修订/失效/确认/提案/快照/版本/运行/导出 + 原子写与恢复 —— 31 用例（store/draft/proposals/data/jobs_runs）全绿
- [x] 3. v2 HTTP API + 计算 job 异步模型 + 上传两阶段 + CLI 薄壳 —— tests/test_v2_http.py 8 用例 + tests/test_cli_v2.py 2 用例全绿；修复中文文件名 Content-Disposition latin-1 崩溃
- [x] 4. 已批准 UI 落地：五视图接线真实 API + standalone 托管 + 旧接口退役 —— static/v2/ 四文件；Registry standalone+壳导航整页跳转；/api/state|/api/calc|/api/assistant_params 退役 404；旧静态三件删除；浏览器冒烟走通 home→示例→口径/假设确认→计算→RUN-001 保存→Excel 导出（含运行身份块）；全仓 298 passed（旧测试按 G18 重写）
- [x] 5. AI 接线：forecast 动作重做（get_plan_state/compare_runs/propose_plan_changes/apply_proposal 四动作，G2 双轨+唯一写动作走确认门）、_EXECUTORS 未命中 raise 不假成功、/health SDK 版本动态读取（0.5.3-harness.3，node --test 13 绿含契约）、真实回环 stage→confirm→apply→draft 落盘冒烟、助手面板三分态
- [x] 6. 兼容收尾：config 创建（来源哈希冻结）、workspace 导入（源副本+目录零改动）、assistant_params 迁移（差异预览→确认并入→未知字段列明）、旧产物标注、A15 扫描 —— tests/test_compat_paths.py 6 用例 + 手工走查记录 .flow/compat-walkthrough.md
- [x] 7. 验收证据：A01–A15 映射 .flow/acceptance-map.md、真实工作区四平台端到端（RUN-001→过期→RUN-002→去重→三格式导出）、Playwright 截图 9 张（1440/390/亮暗/弹窗/壳内）、coupon/ROI 壳内不变、全仓 309 passed + node 13 passed；未验证项如实标注（真实模型质量/kill -9 实测/多标签并发）

---

## 1. 阶段A：引擎六项正确性修正 + diff-map

**Blocked by**: 无
**User stories**: 9, 16 · **验收映射**: A03(部分), A08 的正确性前提；红队 kill-1

What to build:
- 修正 aggregate.consolidate 无 UV 时缺列 KeyError（全模式A 不再 500，口径标记"无UV数据"）。
- 修正 ingest_detail._assign_tiers 索引错配（按索引对齐赋值，禁 .values 错位）。
- 修正短历史年化：窗口 <12 个月时基期年化 GMV = 月均×12，输出 coverage_months 与年化标记。
- pipeline.ingest_platforms 同平台 A/B 双来源返回冲突而非静默覆盖。
- 全渠道客单改同视角分子分母（主口径GMV ÷ 主口径订单数）。
- 平台目标期对齐：共同基期末月 = max(各平台末月)，目标期 = 其后连续 12 个月；缺口平台标记。
- 修正前先对真实 workspace 跑现状 pipeline 冻结输出；修正后复跑做 diff-map，所有数值差异归因到具名修正，证据存 `.flow/engine-diffmap/`。

Acceptance criteria:
- [ ] 6 个最小合成业务期望测试先红后绿（tests/test_engine_fixes.py）
- [ ] diff-map 报告中每个数值变化可归因到具名修正；不可归因 → 停（kill-1）
- [ ] 既有 tests 全绿（coupon/ROI 不动）

## 2. plans 域层（唯一业务更新入口）

**Blocked by**: 1（运行内容键含引擎版本；保持 diff-map 归因干净）
**User stories**: 2, 4(部分), 10, 12, 13, 18, 19, 22, 24, 25, 26 · **验收映射**: A04, A06, A07, A10, A11, A13 的业务层

What to build: `target_forecast/plans/` 包（models.py / store.py / service.py），按 PRD D1/D2 + G1–G5、G8、G11–G14：
- PlanDraft（三失效域 data_coverage/caliber/assumptions 内容哈希确认）、DataSnapshot（含 ingest 期口径冻结值、映射、质量三级清单、源文件副本、来源与 sha256、synthetic 标记）、PlanVersion（不可变）、RunRecord、JobRecord、ExportRecord、AIProposal（pending/applied/discarded/expired）。
- store：workspace/forecast/v2/ 布局；tmp+os.replace 原子写；base_revision 乐观并发（ConflictError）；启动 corrupt 隔离；running job 重开 → unknown。
- service：create_plan（含 from_config 来源冻结）、update_draft（变更即过期 pending 提案+按域失效确认）、confirm、import_data（检查→快照）、resolve_source_conflict、propose_change（dry-run 落 AIProposal）、apply_proposal（revision 校验+幂等+零变更拒绝）、discard_proposal、start_run/cancel_run/save_run（内容键幂等去重）、export_run（绑定+重试不重新计算+同格式去重）。
- 内容键规范化（G11）；所有出参 NaN 清洗（httpkit allow_nan=False 约束）。

Acceptance criteria:
- [ ] pytest：草稿 CRUD/修订冲突/三域失效/提案四态与过期/保存去重/导出绑定与重试/原子写 kill -9 恢复/corrupt 隔离/running→unknown
- [ ] 同一方案手动改参后 AI 提案 apply 立即一致；过期提案拒绝零变更

## 3. v2 HTTP API + job 异步 + 上传两阶段 + CLI 薄壳

**Blocked by**: 2
**User stories**: 5, 6, 7, 8, 14, 15, 20, 21, 26 · **验收映射**: A02, A03, A09, A12 的接口层

What to build:
- forecast 插件 v2 路由（PRD G10 全表）：state/plans CRUD/confirm/uploads/import/jobs(202+轮询+cancel)/runs 幂等保存/proposals apply|discard/runs 导出。
- job 注册表：线程执行、平台间取消旗标、失败/取消不写半结果、崩溃重开 unknown。
- 上传：原始字节+X-Filename→_staging；import 检查→快照→清 staging；ingest 同步无取消；staging 24h 清理。
- 错误分类 400/404/409/422/500，业务可读、保留输入、指向下一步。
- main.py 新增薄壳子命令 plans/plan/plan-create/plan-calc/plan-save/plan-export（全走 service 层）；旧子命令不动。

Acceptance criteria:
- [ ] serve_background HTTP 测试：上传→检查→快照→确认→job→保存→导出全链；409/422 语义；幂等
- [ ] CLI 子命令与 HTTP 读同一份存储（同方案同运行）
- [ ] 取消/失败/unknown 三态可见且不产生半结果

## 4. 已批准 UI 落地（五视图接真实 API）

**Blocked by**: 3
**User stories**: 1–22, 29, 31 · **验收映射**: A01–A03, A05, A07–A15 的界面层；ui-contract.md 全表

What to build:
- `target_forecast/static/v2/`：按 ui-contract.md 落已批准 UI（布局/五视图/右栏 AI/弹窗/toast/亮暗/窄屏/键盘），demo→production 替换表逐项执行；api.js 相对路径 fetch 封装；model.js 演示计算/localStorage 删除（仅存 UI 指针）。
- Registry manifest 加 `standalone` 白名单；壳导航对 forecast 整页跳转（同标签）；coupon/ROI iframe 行为不变；`?tool=forecast` 深链有效；v2 顶栏"← 返回工作台"（同源壳时显示）。
- 真实文件选择/映射/质量清单/来源冲突/覆盖确认；无 UV 场视角"缺少流量数据，未启用"。
- job 轮询 800ms；停止=cancel；过期横幅；保存禁用+解释；运行列表查看快照/导出；导出失败重试。
- 旧 forecast 静态页与 /api/calc、/api/state 退役（D8）；旧 /api/export/* 保留但页面标注"旧版产物，未关联新运行"。

Acceptance criteria:
- [ ] ui-contract.md 负案例 17 条全部不成立
- [ ] 浏览器走查：五视图主链、未保存保护、过期拦截、保存去重、导出绑定、1440/390、亮暗、键盘/dialog
- [ ] coupon/ROI 壳内行为逐屏比对不变

## 5. AI 接线（同一更新入口）

**Blocked by**: 4
**User stories**: 23–28 · **验收映射**: A04, A05, A06, A15

What to build:
- forecast actions 重做：get_plan_state（修订+确认+质量+最近运行摘要）、compare_runs、propose_plan_changes（dry-run 持久化 AIProposal）、apply_proposal（write，确认门+revision 校验+幂等 call_id）。
- assistant service：_EXECUTORS 未命中改 raise（不假成功）；forecast 旧 get_state 快路径退役；_preview 适配新动作。
- sidecar /health 的 sdk 版本改为动态读取真实安装版本（0.5.3-harness.3）。
- 新 UI 助手面板接壳 /api/assistant/*；三分态文案（已配置/回放或不可用/standalone 无助手）；原始订单不进上下文。
- 真实模型不调用；契约测试：sidecar 假 transport + service FakeSidecar + 真实冒烟（stage→confirm→exec_write→draft 落盘）。

Acceptance criteria:
- [ ] node --test 全绿 + 新增提案修订绑定/幂等用例
- [ ] pytest assistant 用例绿；采纳后 GET plan 立即一致；过期提案 409；重复确认不重复写

## 6. 兼容收尾（E 交叉）

**Blocked by**: 4
**User stories**: 4, 29, 30 · **验收映射**: A15、方案 §7

What to build:
- 新建方案"从现有配置创建"：来源记录+取值展示+冻结。
- "从工作区目录导入"：读 workspace/forecast/orders|metrics → 同一快照管道；源文件复制进快照；目录本身不动。
- assistant_params.json 存在时：差异预览→确认并入→未知字段列明（当前不存在的路径也要实现并测）。
- 旧 output/ 产物在新 UI"旧版产物"区列出可下载，明确未关联新运行；不伪造版本链。
- A15 全量扫描：未接入能力无假成功展示。

Acceptance criteria:
- [ ] 兼容路径 pytest + 一次手工走查记录
- [ ] 旧文件零移动/零删除（git 状态与目录哈希前后一致）

## 7. 验收证据

**Blocked by**: 5, 6
**User stories**: 全量 · **验收映射**: A01–A15 映射表

What to build:
- A01–A15 逐条映射正式实现证据（`.flow/acceptance-map.md`）。
- 真实 workspace 四平台端到端（HTTP 链路全走一遍）。
- Playwright+真实 Chrome 验收脚本与截图（桌面/窄屏/亮暗/弹窗/键盘）。
- coupon/ROI/全仓回归绿；区分本轮实际结果/历史证据/未验证项（真实模型质量 = 未验证）。

Acceptance criteria:
- [ ] acceptance-map 逐条有证据或明确未验证标注
- [ ] 截图与下载物核对（绑定运行身份）
- [ ] `.venv/bin/python -m pytest -q` 全绿

---

切片自批准记录（auto）：7 片纵切、依赖线性；S1 先收敛正确性（红队 kill-1），S2 锁域模型地基（GRILL 包1→3→2），S3/S4 先手动主流程后 AI（方案阶段 B→C→D 序），S6/S7 收尾与验收。
