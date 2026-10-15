# Red-Team: 阶段2——提取 scan_inputs / run_platforms / build_views，收敛 main.py 与 server.py 的 pipeline 双份

**verdict 先行：GO（有条件）**。双份认定逐行复核属实，结构差异（一次性 vs 缓存+懒算）识别准确，方案方向可行且无 kill 准则已被触发。但发现**一个已实测确认的未记录地雷**（main.py 对 `cfg["caliber"]` 的原地变异是落盘报表内容的 load-bearing 依赖）、**一个按字面执行必然失效的验证计划**（demo 数据跨进程不确定 + 指名单测恰好不覆盖被重构层）、以及**一个按字面定义无法实现的共用函数**（`run_platforms` 的 "ingest+engine 循环" 与 server 的 ingest-only 缓存不兼容）。三项都是可修订的前置项，不是致命伤——但验证计划若不修，前两项漂移会静默通过。

## Top Kill-Assumptions（按 影响 × 可能性 × 测试成本 排序）

**1. 验证计划按字面执行无法发现数值漂移——demo 数据跨进程不确定，且 `pytest tests/test_core.py` 不覆盖被重构层**
- **Claim:** 验证 = `pytest tests/test_core.py` + 手动 `main.py demo` 对比输出。
- **Fails if:** 行为漂移落在这两个检查的盲区而绿灯放行。两个盲区都是实测事实：(a) demo 生成器种子是 `abs(hash(platform)) % 2**31`（`target_forecast/demo.py:56`），str hash 默认每进程随机加盐——实测同机连续两次 `hash('天猫')` 得 `-1444610003036562789` vs `5436964306567307517`，仅 `PYTHONHASHSEED=0` 下稳定。即**两次 `main.py demo` 生成的输入数据本身就不同**，"对比输出"比的是两套数据，数值漂移与数据再生噪声不可区分。(b) `tests/test_core.py` 只测 engine/aggregate/ingest 的数学不变量，全部在被重构层**之下**——`run_flow` 的编排（三视角拼接、baselines 接线、CSV 落盘、控制台输出）零覆盖；grep 确认无任何测试 import `main`。重构把 `run_flow` 改错了，`test_core.py` 照样全绿。
- **Evidence to get this week:** 已拿到（上述实测）。补一条基线：当前 `workspace/forecast/` 已有固定输入文件（gitignored 但存在），计算路径无 rng，重构前跑 `main.py run` 落盘一份基线即可。
- **Kill criterion:** 对验证条款本身：若开工前验证计划仍写"手动 demo 对比"而无固定输入基线 + 全量 pytest，判验证条款不合格。对实施：重构前后固定输入下控制台输出有任何字节差、`中间指标/*.csv` 有任何行差、xlsx 任一 sheet 有任何行差（除明确记录项），停止。
- **Cheapest test:** 重构前 `main.py run > /tmp/before.txt`，重构后再跑 diff；`diff -r` 对比 `中间指标/` 快照；xlsx 用 pandas 逐 sheet `assert_frame_equal`（报告含 `datetime.now` 时间戳，`report.py:108`，不能字节比）。全量 `pytest`（test_server.py + test_workbench.py 切片3 + test_httpkit_characterization.py 恰好钉住 server/壳两面）。总成本 < 30 分钟。

**2. main.py 对 `cfg["caliber"]` 的原地变异是 load-bearing——报表 07_参数 sheet 的 `target_months` 行靠副作用存在**
- **Claim:**（隐含）两份代码的 caliber 处理等价，可安全统一。
- **Fails if:** 共用层采用 server.calc 的拷贝式写法（`server.py:129` `{**cfg["caliber"], "target_months": ...}`）而 main.py 壳丢掉变异。证据链：`main.py:43-44` `caliber = cfg["caliber"]; caliber["target_months"] = cfg["target"]["months"]` 是**原地变异**（同一对象）；`report.write_report` 在 `report.py:137-138` 遍历 `cfg["caliber"].items()` 生成 07_参数 sheet。已实测当前落盘的 `目标测算报告.xlsx` 07_参数 sheet 第 43 行确有 `口径 / target_months / 12`——此行**仅因该副作用存在**。拷贝式统一后此行静默消失，违反硬约束 3，且无测试读 xlsx，只有手动检查可能发现——而验证计划（假设 1）恰好不可靠。
- **Evidence to get this week:** 已拿到（xlsx 实测）。开工前把此项写进提案的"明确记录项"：要么保留变异，要么把合并后的 caliber 显式传给 write_report。
- **Kill criterion:** 重构后 07_参数 sheet 与基线有任何行差（少 `target_months` 或多任何键），且该差异不在提案记录项内——停止，这是未授权漂移。
- **Cheapest test:** 假设 1 的 xlsx 逐 sheet 对比天然覆盖；单独验证只需 `pd.read_excel(..., sheet_name='07_参数')` 对比前后两次，10 秒。

**3. `run_platforms` 按字面定义（"ingest+engine 循环，main.py 和 WorkbenchState.load 共用"）与 server 两段式缓存不兼容——共用函数不存在**
- **Claim:** 模式 A/B 的 ingest+engine 循环是两处共有逻辑，可提取为一个共用函数。
- **Fails if:** 按字面实现。`server.py:68-78` 的 `WorkbenchState.load` **只 ingest 不算引擎**（缓存 `unified`/`structure` 原始数据），engine.run 在 `calc()`（`server.py:131-132`）按请求情景懒算；且 `state_payload`（`server.py:88-96`）依赖缓存里的 `unified` 出 history。一个 ingest+engine 的共用函数若被 server.load 使用，必须用 cfg 默认情景在装载期跑引擎——结果是死计算（calc 反正重算）、启动/重载失败面扩大（engine 错误从首次 calc 提前到 `serve()` 启动）、且 server 缓存形状被迫改变。提案开放问题摸到了边（"run_platforms 返回到哪一层"）但没给结论；唯一不泄漏的解是拆成**两个**函数：`ingest_platforms(detail, agg, caliber, on_progress=None)`（两处共用，server 缓存其返回）+ `run_engine(platforms, scenarios, caliber) -> results`（main.py 与 calc 共用）——即提案点名的 `run_platforms` 应按"ingest 半段"重新定义，否则方案在动工第一天就要返工。
- **Evidence to get this week:** 无需更多证据，这是设计决策。在提案中把函数清单改写为 scan_inputs / ingest_platforms / run_engine / build_views 四件套，并写明 server.load 只共享 ingest 半段。
- **Kill criterion:** 若实施中共用函数要求 `WorkbenchState.load` 执行 `engine.run`（可观察判据：serve 启动或 `/api/state?reload=1` 的耗时/失败面扩展到引擎错误），停止——拆分设计错了。
- **Cheapest test:** 设计层面零成本（改写提案一节）；实施后可观察验证：独立 server 起一次 + `curl /api/state`，行为与耗时应与现状无差别。

**4. main.py 控制台输出与警告捕获的交织顺序——共用层不得重排操作或吞警告**
- **Claim:** "注意保留 main.py 的进度打印（可传回调）"（提案已点到，但未定价其精确性要求）。
- **Fails if:** 回调点位不全或共用层改变操作顺序/警告过滤。现状精确形状：`main.py:48,54` 每平台两行打印**咬合在同一行**（前句 `end=" "` 在 ingest 前，后句在 engine 后）；`main.py:116-126` 在 `main()` 里以 `catch_warnings(record=True)` + `simplefilter("always")` 包住整个 `run_flow`，⚠ 行在**全流程结束后**统一回放。若共用层把 ingest 与 engine 拆成两个循环（假设 3 的拆法若被粗暴应用到 main.py 壳），打印顺序从"逐平台咬合"变成"先全 ingest 后全总结"——控制台输出即漂移。警告同理：共用层任何 `warnings.filterwarnings` 或操作重排都会改变 ⚠ 清单的内容/顺序。
- **Evidence to get this week:** 假设 1 的字节级控制台 diff 即证据。
- **Kill criterion:** 固定输入下控制台输出有任何字节差（含 ⚠ 行的数量与顺序），停止。
- **Cheapest test:** 与假设 1 同一个 diff，零边际成本——前提是假设 1 的基线已建。

**5. "两处调用方"少算了一处，空输入策略分叉未列入——壳插件与 load_cfg 消费面**
- **Claim:** 双份逻辑有"两处调用方"（main.py、server.py），收敛后两壳变薄。
- **Fails if:** (a) 行为面实为**三处**：`target_forecast/plugin.py:15-16` 的 workbench 壳插件直接消费 `server.load_cfg` + `WorkbenchState` + route_get/route_post（`tests/test_workbench.py` 切片3 钉住壳内 state/calc/export）。只要 server.py 的公开面不变即安全，但 `load_cfg` 收敛（提案重复表第一行）牵动 plugin.py 及两个测试文件的 import（`tests/test_server.py:21`、`tests/test_httpkit_characterization.py:63`）——若挪走不留别名，须同步改三处 import，而提案点名的 `test_core.py` 单测**不会**发现这个断裂。(b) 空输入策略分叉：main.py 无输入时 `sys.exit`（`main.py:40-41`），server 无输入时自动生成 demo 并置 `demo_used`（`server.py:60-64`）。这个分叉必须留在两壳各自手里，不能被"顺手"收进 scan_inputs。
- **Evidence to get this week:** 全量 pytest 已覆盖（test_workbench.py 切片3 + characterization fixtures）——又一次指向假设 1：验证必须跑全量而非单文件。
- **Kill criterion:** 实施 diff 若改动 server.py 公开符号签名（load_cfg/WorkbenchState/route_*/make_handler/serve）而未同步 plugin.py，或 scan_inputs 吸收了 demo 自生成/sys.exit 任一策略，停止。
- **Cheapest test:** `python -c "import target_forecast.plugin"` + 全量 pytest 绿；空 workspace 下分别跑 `main.py run`（应 exit 报错）与 server（应 demo_used=true）。

## What's Well-Reasoned

- **双份认定属实**：提案表格四行的行号全部与实码对得上（load_cfg、scan、汇总拼接逐行同构）。唯一瑕疵是第三行把 server 的 ingest-only 循环标成"ingest+engine 循环"——标签误差而非理解误差，结构差异段落（proposal L21）自己已纠正。
- **结构差异的识别准确且被正确地立为中心约束**——这正是假设 3 的出处，提案诚实记录了这个开放问题。
- **server 侧现有测试网比提案自述的厚**：test_server.py 钉住 main_view 选择（私域=场/天猫=人）、consolidated 形状（3×12）、参数效应方向、垃圾输入钳制；test_workbench.py 切片3 钉住壳内 forecast 全链路；characterization fixtures 直接用 load_cfg/WorkbenchState。全量 pytest 下 server/壳两面覆盖够用——**盲区只在 main.py CLI 面**，这精确界定了补验证的范围。
- **已拒绝替代判断正确**：子进程方案引入进程边界确实违背本地一体化；不动 engine/aggregate 内部符合既定约束。
- **build_views 的对称性真实**：`main.py:64-77` 与 `server.py:134-147` 逐行同构，提取无设计风险。

## What I Couldn't Assess

- 实际运行中哪些警告会被 `catch_warnings` 捕获（未执行完整 run_flow；⚠ 回放路径在典型输入下可能是死代码）——影响假设 4 的权重而非其有效性。
- 是否有下游程序化消费 07_参数 sheet——影响假设 2 的爆炸半径，不影响漂移事实。
- 第三份 concat 拷贝藏在 `write_report` 内部（`report.py:77-86`）：build_views 落地后它仍残留，"消除双份"的目标表述应修正为"调用方薄壳化"——这是表述问题，不构成立项风险。
- 提取目标放 `aggregate.py` 还是新建 `pipeline.py`——口味问题，无正确性差异。

## Verdict

**GO**，以三个开工前修订为条件：

1. **验证条款重写**：固定输入基线 diff（控制台字节级 + `中间指标/*.csv` + xlsx 逐 sheet pandas 对比）+ **全量** pytest，替换"手动 demo 对比 + test_core.py 单文件"；或至少 `PYTHONHASHSEED=0` 钉住 demo 种子。
2. **`caliber` 原地变异列为已记录行为项**：明确决定保留变异或显式传 caliber 给 write_report，07_参数 sheet 的 `target_months` 行不得静默消失。
3. **函数清单改写**：scan_inputs / ingest_platforms / run_engine / build_views 四件套，写明 server.load 只共享 ingest 半段，engine 保持在 calc 懒算。

无任何 kill-assumption 的 kill 准则已被触发（全部是"若实施/验证不修订则会触发"的条件式），故不判 KILL。
