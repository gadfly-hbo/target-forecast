# 任务清单：重构阶段2 — target_forecast pipeline 收敛

> 来源：`.flow/prd.md`（含 GRILL 第 1 轮决议）。无 issue tracker，本文档即任务总线。
> 硬要求：任务 1 的基线必须先于任何代码改动建立；行为逐字节等价（无 deliberate-change）。

- [x] 1. 建立固定输入基线快照（改代码前） — 证据：workspace/baseline-stage2/ 含 console.before.txt/.err（stderr 0 行）、中间指标.before/、report.before.xlsx；07_参数 44 行含 target_months 行（pandas 实读确认）
- [x] 2. 新建 `target_forecast/pipeline.py` 四件套 + test_pipeline.py — 证据：pytest test_pipeline.py 1 failed(AST守卫按预期红)+6 passed in 37.62s
- [x] 3. main.py 薄壳化 — 证据：import main 通过；AST 守卫失败点仅剩 server._scan（main 侧已绿）；6 passed
- [x] 4. server.py 薄壳化 — 证据：import target_forecast.plugin 通过；test_pipeline 7 passed in 38.99s（AST 守卫翻绿）
- [x] 5. 基线 diff 对比 + 全量回归 — 证据：console stdout/stderr diff 逐字节相同；中间指标 diff -r 相同；xlsx 8 sheets 逐 sheet assert_frame_equal 全同（07_参数 44 行含 target_months）；全量 pytest 187 passed

---

## 1. 建立固定输入基线快照（改代码前）

## What to build

当前 `workspace/forecast/` 已有固定输入（orders 京东/天猫/抖音.xlsx + metrics 私域.xlsx）。在任何代码改动前：

1. `.venv/bin/python main.py run > workspace/baseline-stage2/console.before.txt 2> workspace/baseline-stage2/console.before.err`
2. 复制 `workspace/forecast/output/中间指标/` 整目录与 `目标测算报告.xlsx` 到 `workspace/baseline-stage2/`
3. 记录基线 xlsx 的 07_参数 sheet 含 target_months 行（红队实测第 43 行）

## Acceptance criteria

- [ ] `workspace/baseline-stage2/` 含 console.before.txt/.err、中间指标快照、xlsx 快照
- [ ] 快照目录不被 git 追踪（workspace/ 在 .gitignore）
- [ ] 此任务完成前不改任何 .py

## Blocked by

None - can start immediately

---

## 2. 新建 `target_forecast/pipeline.py` 四件套 + test_pipeline.py

## What to build

新建 `target_forecast/pipeline.py`（无调用方切换，本任务只加不改）：

- `scan_inputs(root) -> (detail, agg)`：扫 `root/"workspace"/"forecast"/"orders"` 与 `.../metrics`，glob `*.xlsx` 排除 `~$`，目录缺返 `{}`。不含空输入策略。
- `ingest_platforms(detail, agg, caliber) -> platforms`：模式 A/B ingest 循环（无 on_progress——GRILL Q1），返回 `{platform: {"mode", "unified", "structure"}}`（= server 缓存形状）。
- `run_engine(platforms, scenarios, caliber) -> results`：逐平台 engine.run，返回 `{platform: {"mode", "unified", **engine.run(...)}}`（= main.py results 形状，保持插入序）。
- `build_views(results) -> dict`：返回且仅返回 `{"consolidated", "platform_annual", "check", "goods", "baselines"}`（GRILL Q2）。
- docstring 记录 caliber 变异不对称的原因（write_report 07_参数 依赖 main.py 壳的原地变异）。

新建 `tests/test_pipeline.py`（GRILL Q5/Q6）：

1. 手写最小 xlsx：一个模式 A 平台（~4 个月十来个订单）+ 一个带 UV 的模式 B 平台（钉 main_view 人/场分叉）
2. scan_inputs 排除 `~$`、缺目录返 `{}`
3. ingest_platforms 返回形状、模式 B `structure is None`
4. run_engine 并入 engine.run 键且保持插入序
5. build_views 五键、consolidated 行数 == 情景数 × target_months
6. AST 守卫：main.py 不再定义 `_collect_inputs`、server.py 不再定义 `_scan`、两者都 import pipeline（本任务阶段对现状红，任务 3/4 完成后绿——按 TDD 红先行的预期失败处理）
7. 空输入分叉：monkeypatch main.ROOT=tmp_path + SystemExit（main 侧）；WorkbenchState(tmp).load() → demo_used=True（server 侧）

## Acceptance criteria

- [ ] pipeline.py 四件套齐备，docstring 记录 caliber 不对称原因
- [ ] test_pipeline.py 1-5、7 绿；6（AST 守卫）此时红属预期（任务 3/4 后翻绿）
- [ ] 既有全量 pytest 不受影响

## Blocked by

- 任务 1

---

## 3. main.py 薄壳化

## What to build

- 删除 `_collect_inputs`、本地 `load_cfg`（改 import server.load_cfg）
- `run_flow` = `scan_inputs(ROOT)` → 空输入 sys.exit（原位保留）→ `cfg["caliber"]["target_months"] = cfg["target"]["months"]` 原地变异（原位保留，07_参数 依赖）→ `ingest_platforms` → `run_engine` → 按 results 插入序逐平台补打整行进度（GRILL Q1：精确复刻 `[{p}] 模式X … 历史 … 共N月 · 主口径[X]`）→ `build_views` → 写 CSV/报表 → 控制台摘要（`baselines` 从 build_views 返回值取）
- `warnings.catch_warnings` 包裹在 main() 原位不动

## Acceptance criteria

- [ ] main.py 无 `_collect_inputs`、无本地 `load_cfg`
- [ ] 控制台输出与基线 console.before.txt 逐字节相等（任务 5 统一执行对比）
- [ ] 全量 pytest 绿

## Blocked by

- 任务 2

---

## 4. server.py 薄壳化

## What to build

- 删除 `_scan`；`WorkbenchState.load` 改调 `scan_inputs` + `ingest_platforms`（demo 自生成与 `demo_used` 逻辑原位保留；load 不跑引擎）
- `calc()` 引擎循环改调 `run_engine`，汇总段改调 `build_views`（拷贝式 caliber 原位保留）
- 公开符号签名全部不变：load_cfg / WorkbenchState / route_get / route_post / make_handler / serve / calc

## Acceptance criteria

- [ ] server.py 无 `_scan`；AST 守卫（任务 2.6）翻绿
- [ ] `python -c "import target_forecast.plugin"` 通过
- [ ] 全量 pytest 绿（test_server / test_workbench 切片3 / characterization）

## Blocked by

- 任务 3

---

## 5. 基线 diff 对比 + 全量回归

## What to build

1. 重构后 `main.py run > workspace/baseline-stage2/console.after.txt 2> console.after.err`
2. `diff` console before/after（stdout/stderr 分开）——必须逐字节相等
3. `diff -r` 中间指标 before/after——必须相等
4. pandas 逐 sheet 对比 xlsx：00_说明 掩码 `生成时间：…` 行（GRILL Q3），其余 7 sheet verbatim `assert_frame_equal`（重点：07_参数 的 target_months 行存在）
5. 全量 `pytest`

## Acceptance criteria

- [ ] console/CSV/xlsx 三项对比零差异（除掩码行）
- [ ] 全量 pytest 绿
- [ ] 对比脚本与结果记录到 VERIFY 证据

## Blocked by

- 任务 4
