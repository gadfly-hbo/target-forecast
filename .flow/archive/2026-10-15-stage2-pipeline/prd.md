# PRD：重构阶段2 — target_forecast pipeline 收敛

> 规格来源：`.flow/proposal.md`。红队报告：`.flow/red-team.md`（GO，三个开工前修订已全部采纳进本 PRD）。

## Problem Statement

`main.py`（CLI 一次性流程）与 `target_forecast/server.py`（工作台缓存+懒算）维护同一段业务逻辑的两份拷贝：config 加载、输入扫描、模式 A/B ingest 循环、三视角 concat 汇总。改汇总口径要改两处且必然漂移；红队实测确认其中一处（`cfg["caliber"]` 原地变异喂给报表 07_参数 sheet）已经是"靠副作用才正确"的脆弱状态。

## Solution

在 `target_forecast/` 内新建 `pipeline.py`，提取四个共用函数，两个调用方（main.py CLI、server.py WorkbenchState/calc）变成薄壳；server.py 的公开符号（`load_cfg`/`WorkbenchState`/`route_*`/`make_handler`/`serve`）保持不变，壳插件与测试零改动。

## User Stories

1. As a 维护者，I want 输入扫描（glob xlsx 排除 ~$）只有一份实现，so that 改输入约定只改一处
2. As a 维护者，I want 模式 A/B 的 ingest 循环只有一份实现，so that 新增 ingest 模式不会只在一端生效
3. As a 维护者，I want 三视角 concat + consolidate + platform_annual 只有一份实现，so that 汇总口径永远一致
4. As a 维护者，I want server 的"缓存 ingest、按需 calc"两段式不被破坏，so that `/api/state` 不需要跑引擎、`reload=1` 的失败面不扩大
5. As a 维护者，I want main.py 的逐平台进度打印与警告回放逐字节不变，so that CLI 用户体验零漂移
6. As a 维护者，I want `main.py run` 落盘的 xlsx 07_参数 sheet 保留 target_months 行，so that 报表内容零漂移
7. As a 维护者，I want 空输入策略分叉保留在两壳（main.py sys.exit / server 自动生成 demo），so that 两个入口的既定语义不变
8. As a 审查者，I want 固定输入下的基线 diff（控制台 + CSV + xlsx 逐 sheet），so that "零漂移"是可证伪的断言而非口头承诺

## Implementation Decisions

1. **新建 `target_forecast/pipeline.py`**（红队口径：放 aggregate.py 还是新模块无正确性差异；新建 pipeline.py 语义最准——ingest 编排不是 aggregate）。四件套：
   - `scan_inputs(root) -> (detail, agg)`：两目录 glob `*.xlsx` 排除 `~$`。只扫描，不含空输入策略（分叉留在调用方）。
   - `ingest_platforms(detail, agg, caliber, on_progress=None) -> platforms`：模式 A（load_detail→classify_new→order_level→to_unified→goods_structure）与模式 B（load_agg→to_unified）循环；**只 ingest 不算引擎**。`on_progress(platform, mode, unified)` 回调供 main.py 进度打印（点位与现状咬合顺序一致）。返回 `{platform: {"mode", "unified", "structure"}}`——正是 server 缓存的形状。
   - `run_engine(platforms, scenarios, caliber) -> results`：逐平台 `engine.run`，返回 `{platform: {"mode", "unified", **engine.run(...)}}`——正是 main.py run_flow 内 results 的形状。
   - `build_views(results) -> dict`：三视角 concat（main_view 选择）+ baselines + `aggregate.consolidate` + `aggregate.platform_annual` + `report._build_check_sheet` + `report._build_goods_sheet`，返回 main.py 与 server.calc 都消费的字典。
2. **`cfg["caliber"]` 原地变异显式保留在 main.py 壳**：`run_flow` 开头继续 `cfg["caliber"]["target_months"] = cfg["target"]["months"]`（红队实测：write_report 的 07_参数 sheet 遍历 `cfg["caliber"]`，该行靠此副作用存在）。server.calc 保持拷贝式（`{**cfg["caliber"], ...}`）不动。此不对称在 pipeline.py docstring 中记录原因。
3. **main.py 薄壳**：`_collect_inputs` 删除改调 `scan_inputs`；`load_cfg` 删除改 import server 的（server.load_cfg 保留原位，plugin.py 与测试 import 不变）；run_flow = scan → 空输入 sys.exit（保留）→ caliber 变异 → ingest_platforms(on_progress=打印) → run_engine → build_views → 写 CSV/报表 → 控制台摘要。`warnings.catch_warnings` 包裹保持在 main() 现状位置，共用层不得含 warnings 过滤。
4. **server.py 薄壳**：`WorkbenchState.load` 的扫描+循环改调 `scan_inputs` + `ingest_platforms`（demo 自生成与 `demo_used` 逻辑保留在 load 内原位）；`calc()` 的引擎循环改调 `run_engine`，汇总段改调 `build_views`。公开符号签名全部不变。
5. **目标表述修正**（红队"What I Couldn't Assess"）：report.py 内 `write_report` 还有第三份 concat 拷贝（report.py:77-86），本阶段不动它——目标精确化为"**调用方薄壳化**"，不是"全仓库 concat 只剩一份"。
6. **零行为漂移清单**（除以下外不允许任何差异）：无 deliberate-change——本阶段要求行为逐字节等价。

## Testing Decisions

- 好测试 = 固定输入下的可证伪对比；本阶段以"基线 diff"为主验证（重构是等价变换）。
- **开工前先建基线**（红队修订①，因 demo 种子 `hash(platform)` 跨进程随机、test_core.py 不覆盖编排层）：
  1. 当前 `workspace/forecast/` 已有固定输入文件——重构前跑 `main.py run`，保存控制台输出、`中间指标/*.csv` 快照、xlsx 逐 sheet pandas 快照（含 07_参数 sheet；xlsx 有 datetime 时间戳不能字节比）
  2. 重构后同样跑 `main.py run`，控制台 diff 必须逐字节相等、CSV `diff -r` 相等、xlsx 逐 sheet `assert_frame_equal`
- 全量 `pytest`（不是单文件）：test_core（引擎数学不变量）+ test_server（main_view/consolidated 形状/参数效应）+ test_workbench 切片3（壳内 forecast 全链路）+ test_httpkit_characterization（load_cfg/WorkbenchState fixtures）
- 新增一条编排层测试（`tests/test_pipeline.py`）：用 tmp 合成的最小输入跑 scan_inputs/ingest_platforms/run_engine/build_views 四件套，断言形状与关键不变量（防止未来再长出第三份拷贝）
- 空输入分叉冒烟：tmp 空目录下 `main.py run` 应 exit 报错；server `WorkbenchState.load` 应 demo_used=True

## Out of Scope

- engine / aggregate / report 内部数学与报表布局
- report.py 内第三份 concat 拷贝（见决策 5）
- demo.py 种子不确定性（记录为已知事实，不修——修它属于行为变化）
- coupon_tool / roi_tool / workbench 壳
- 阶段3-5

## Further Notes

- 阶段1 产物（tools_common/httpkit）已就位，本阶段不涉及 HTTP 层。

## PRD diff gate（相对 proposal.md 的差异）

proposal 硬约束全部保留。差异点：

1. **函数清单修正**（proposal 开放问题 2 的收敛）：`run_platforms`（ingest+engine 合一）→ 四件套 `scan_inputs / ingest_platforms / run_engine / build_views`，server.load 只共享 ingest 半段。（红队条件③，证据：server 两段式缓存）
2. **提取目标拍板**：新建 `pipeline.py`（proposal 开放问题 1；红队：无正确性差异，语义优先）。
3. **caliber 原地变异**（proposal 未提）：显式保留在 main.py 壳并记录原因。（红队条件②，07_参数 sheet 的 load-bearing 副作用）
4. **验证条款重写**：固定输入基线 diff（控制台字节级 + CSV + xlsx 逐 sheet）+ 全量 pytest，替换"test_core.py + 手动 demo 对比"。（红队条件①，demo 种子跨进程随机）
5. **目标表述修正**：从"消除双份"精确化为"调用方薄壳化"（report.py 内第三份 concat 本阶段不动）。
6. **新增**：空输入策略分叉显式留在两壳（红队 kill-assumption 5b）；plugin.py 为第三消费面，server.py 公开面不变（5a）。

---

## GRILL 决议

### 第 1 轮（author-blind 子代理，2026-10-15，6 个已决问题包）

- **Q1（修订决策 1/3）进度打印**：删除 `on_progress` 回调设计。main.py 壳在 `run_engine` 之后按 results 插入序逐平台补打整行（`[{p}] 模式X … 历史 {min}~{max} 共{n}月 · 主口径[{main_view}]`），字节流与现状相等。依据：现状"实时进度"是幻觉（`end=" "` 无 flush，管道块缓冲）；`main_view` 来自 engine.run 返回，ingest 期物理上不可得。警告回放不受拆分影响（全链路唯一 warn 在 ingest_agg.to_unified，基线数据下为死代码）。备选 (c) 单平台原语推翻四件套 API，否决。
- **Q2 build_views 返回键钉死**：返回且仅返回 `{"consolidated", "platform_annual", "check", "goods", "baselines"}`。calc 组装段变纯挑键；main.py 的 `baselines` 也从返回值取（避免第四次派生）。不返回 `*_all` 中间帧（无壳内消费者；write_report 内部自做 concat，已钉不动）。
- **Q3 xlsx 对比掩码**：00_说明 sheet 的 `生成时间：…` 单元格（分钟精度）读入后正则归一化再 `assert_frame_equal`；其余 7 个 sheet（含 07_参数的 target_months 行）verbatim 对比。这是对比窗口归一化，非 deliberate-change。
- **Q4 基线快照位置**：`workspace/baseline-stage2/`（gitignored、持久、贴数据；不进 `.flow/` 因其受版本控制且快照含业务数据衍生物）。流程：改前 `main.py run > workspace/baseline-stage2/console.before.txt 2> console.before.err` + 复制 `中间指标/` 与 xlsx；改后同法得 after；stdout/stderr 分开 diff、CSV `diff -r`、xlsx 带掩码对比。不钉 PYTHONHASHSEED（run 路径无 hash 依赖）。
- **Q5 test_pipeline.py 合成方式**：手写最小 xlsx（不跑 demo.generate）——模式 A 必填仅 5 列（schema.py:7）、模式 B 必填 6 列（schema.py:11，加 UV 触发场视角）；engine 容忍 <12 月历史。一个模式 A 平台 + 一个带 UV 的模式 B 平台，断言：scan 排除 `~$`/缺目录返 `{}`；ingest 返回 `{mode, unified, structure}` 且 B 的 structure 为 None；run_engine 并入 engine.run 六键且保持插入序；build_views 五键、consolidated 行数=情景数×target_months。另加 AST 守卫（先例：test_httpkit_characterization.py）：main.py 不再定义 `_collect_inputs`、server.py 不再定义 `_scan`、两者都 import pipeline。
- **Q6 空输入分叉冒烟自动化进 pytest**：main 侧 `monkeypatch.setattr(main, "ROOT", tmp_path)` + `pytest.raises(SystemExit)` 调 run_flow（首个 import main 的测试，已确认 main() 在 `__main__` 守卫内，import 安全）；server 侧 `WorkbenchState(tmp_path, cfg["caliber"]).load()` → demo_used is True 且 platforms 非空。AST 守卫顺带钉住"scan_inputs 不吸收 sys.exit/demo 自生成"。
- **已钉死无需提问**：caliber 变异不对称（决策 2，证据链闭合）；四件套返回形状与两侧消费面逐键对上；calc 拷贝式 caliber 与 run_engine 交互（engine/ingest 对 caliber 只读）；load_cfg 收敛（server.load_cfg 原位保留，无 main.load_cfg 消费者）；warnings 过滤不进共用层；report.py 第三份 concat 不动；server 公开符号冻结。
