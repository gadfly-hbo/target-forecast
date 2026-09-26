# Review Findings（REVIEW 阶段产出，子代理原文）

## 审查结论

**FAIL** — 引擎与账本核心质量高：四子模型分支表、黄金基准表（±1 分实测吻合）、M01–M20 大多有真实断言，验证证据（90 passed）复跑一致；但存在 1 个阻断性问题（K>0 时无券候选违反 M01）与 2 个影响决策/复盘正确性的主要问题。审查范围 = 基线 f5ac830 以来的全部新增未跟踪文件（`coupon_tool/`、`tests/test_coupon_*.py`、`.flow/`），tracked 文件零改动（`git diff f5ac830` 为空），target_forecast 未被触碰，符合声明。

仓库根：`/Users/bendandebaba/DevWorkSpace/Projects/target-forecast`

## 阻断性问题（BLOCKER）

- [coupon_tool/engine.py:242] K 被记到无券候选头上，K>0 时直接违反 M01
  证据：`pi_coupon = _sum("contribution_cents") - c.fixed_activity_cost_cents` 对 `enabled=False` 的候选同样扣 K。实测复现：合成场景设 `fixed_activity_cost_cents=50000` 后，无券候选 `incremental_contribution_cents = -50000.0`，且被 compare.py:97-108 判为 `incremental_contribution` 违例、`feasible=False`。
  后果：违反提案 §4.5（"K 只含相对无券方案新增的固定活动费用"，Π₀ 不含 K）与 §5.1/M01（"无券候选直接使用完整基准、ΔΠ=0"）。只要用户填了任何活动固定费用（真实场景常态），"不发券"结论被系统性压低 K 元，最坏时四类结论误报"无券基准也不满足业务目标"，误导发券决策。现有 M01 测试（tests/test_coupon_engine.py:81）只测 K=0，未覆盖。
  建议：`enabled=False` 时不扣 K（K 仅属于券方案），并补一条 K>0 的 M01 参数化测试。
  复检判据：K=500 元、无券候选 simulate 后 ΔΠ 必须为 0。
  上游：spec（§4.5/§5.1/M01）+ implementation

## 主要问题（MAJOR）

- [coupon_tool/review.py:53-57] 复盘的预测基准固定为 ranking[0]，无视人工确认的选择
  证据：`top = ranking[0] ... m = top["metrics"]`，`predicted` 全部取排序第一；已保存的 `decisions/{run_id}.json` 从未被读取，`/api/review`（server.py:225-243）与 app.js 的复盘流也不传 choice。
  后果：提案 §8.3 明确"人工选择不要求与排序第一一致"（可为其他候选或"暂不发券"）。当人工确认方案 ≠ 排序第一时，复盘的 predicted/diffs 全部基于错误方案，七类偏差归因与参数新版本建议随之失真，破坏门禁 D。
  建议：`create_review` 接受 chosen label（默认回退 ranking[0]），并从决策记录读取。
  复检判据：保存 choice="满159减5" 的决策后复盘，`predicted` 应来自满159减5 的 metrics。
  上游：spec §8.3/§9.2、prd story 23、task S8

- [coupon_tool/compare.py:303-306] 均衡模式归一化尺度从当前候选集自动推导，违反 §5.2
  证据：`profit_scale = float(params.get("profit_scale") or max(abs(v) for v in pis) or 1.0)`（conv_scale 同理），未显式给尺度时取当前可行集 max|ΔΠ|/max|ΔC|，且不写回场景。
  后果：提案 §5.2 要求"尺度/权重/方向存入场景，不因临时极端候选自动改变归一化尺度"。当前实现加入一个极端候选会改变所有其他候选的 Score 相对关系与排序，跨候选集比较失真。
  建议：未提供尺度时要求显式填写（校验错误），或固定存入场景的缺省尺度。
  复检判据：同一 objective_params 下增删一个极端候选，其余候选 Score 应保持不变。
  上游：spec §5.2

## 次要问题（MINOR）

- [tests/test_coupon_stress.py:10] 压力黄金值容差被放宽 100 倍 — `TOL = 100`（±1 元），PRD Testing Decisions 明确"压力表 6 值……容差 ±1 分"。我独立复算：6 值实际偏差 0.00–0.39 分，收紧到 ±1 分仍全过，故当前未掩盖失败，但属被削弱的验收断言。复检：TOL 改 1 后测试仍绿。上游：prd/verify
- [coupon_tool/storage.py:76] 运行记录封存的 `validation` 是硬编码空表 — `json.loads(_canonical({"errors": [], "warnings": []}))`，非 `validate_spec` 真实结果；warnings（如"加购毛利率未显式设置""缺 N"）在封存记录中丢失，违反 §10.3"封存校验结果"。复检：带 warning 的场景 record_run 后 run JSON 的 validation.warnings 非空。上游：spec §10.3
- [coupon_tool/compare.py:101-102] 受控亏损开启但未设 max_loss 时静默退化为 floor=0 — `floor = -(cons.max_loss_cents or 0.0)`；§5.3 要求"主动开启+设最大损失"，未设上限应报错或警告而非静默忽略。复检：allow_controlled_loss=True、max_loss=None 时应有校验错误。上游：spec §5.3
- [coupon_tool/engine.py:216 vs coupon_tool/compare.py:177] 两处"可触达上限"口径不一致 — 引擎 ΔC⁺ 上限用 `(1−C₀)e⁺`（§4.4 原式），盈亏平衡用 `(1−C₀R)e⁺`；churn>0 时后者更大，ΔC⁺_BE 可能被判"未超限"而引擎自身无法产生该量。复检：churn>0 场景下两 cap 应取同一公式或文档化差异。上游：implementation
- [coupon_tool/engine.py:191-195] M15 只落 limitations，无 validation warning — GRILL G3 与 tasks.md S4 验收均写"对该候选给 validation warning + limitations 标注"，测试（tests/test_coupon_ingest.py:86）也只断言 limitation。实质可见性达成，形式与决议不符。复检：穿桶候选的 validation 段含该警示或决议修订留痕。上游：task/grill
- [coupon_tool/synthetic.py:21-31 vs coupon_tool/cli.py:17-21] 同包内两套不兼容的压力变体格式 — `STRESS_VARIANTS`（section 级 dict）直接喂 `stress_test` 实测抛 `SpecError: 缺少新增结果分布 vⱼ`（整段 behavior 被覆盖）；`build_stress_spec`（synthetic.py:101）已导出却无任何调用方。复检：统一为点路径格式或删除未用入口。上游：implementation
- [coupon_tool/compare.py:292,343-344] 每个可行启用候选被 simulate 两次 — compare 主循环一次、`_breakeven(spec, cand, _resim(spec, cand))` 又一次；`_resim` 是纯委托包装（Middle Man）。候选多时比较耗时翻倍。复检：breakeven 复用 row 已有的 metrics/ledger。上游：implementation
- [coupon_tool/storage.py:99-114] replay_run 先写新 run 文件再把返回 dict 的 run_id 改回旧 id — 返回记录与其落盘文件 id 不一致，调用方按该 id 引用会命中旧运行。复检：返回 run_id 与新写文件名一致，或明确只读对比不落盘。上游：implementation
- [coupon_tool/stress.py:64,78-79] `budget_exceeded` 固定用原 spec 预算 — 若变体本身改了 constraints.merchant_coupon_budget_cents，行内 feasible（用变体）与 budget_exceeded（用原值）口径分裂。复检：变体改预算时两者同源。上游：implementation

## NOTE（提示，不计为问题）

- 被禁测试检查：未发现"面额越大收益一定越小""门槛单峰最优"类通用测试（合规）；tests/test_coupon_compare.py:53 的 test_m09 是提案 M01–M20 中 M09 明确要求的比较静态断言（加购毛利下调→贡献不得反向提高），属规格要求而非被禁性质。
- 测试内死代码：tests/test_coupon_engine.py:173-177 `for bad in [...]: pass`、tests/test_coupon_server.py:53 `... if False else (None, None)` —— 无断言作用的残留；tests/test_coupon_ingest.py:112 `load_spec.__globals__["validate_spec"]` 的绕道调用。未使用导入：coupon_tool/compare.py:8 `copy`、engine.py:11 与 stress.py:9 的 `field`。
- 黄金值同源性核查：tests/test_coupon_engine.py:26 的期望值取自 coupon_tool/synthetic.py 的 GOLDEN_TABLE，我逐行比对 proposal §7.2/§7.3 原文，10 行基准表与 6 个压力值全部一致；期望字段不参与 spec 构建，非同义反复（tautological）断言。

## 待确认（UNVERIFIED）

- M20"导出与界面数值一致"的精度边界：exports.py:44-46 候选表 CSV 金额列 `:.0f` 取整分，JSON 保留 6 位小数分，半分级差异是否在"统一定义输出精度"允许范围内，需作者确认口径。
- 帕累托集包含不可行候选（compare.py:314-315，tests/test_coupon_compare.py:90 有意断言"满139减20 ΔΠ<0 但非支配"入集）——是否需要给 pareto 输出附可行性标记，属产品判断。

## 覆盖确认

- 已检查：`coupon_tool/` 全部 14 个 py 文件全文；`tests/test_coupon_*.py` 全部 8 个文件全文；`coupon_tool/static/app.js` 比较表/决策卡/复盘段；`.flow/` 三份冻结工件（proposal/prd/tasks）；在仓库根复跑 `.venv/bin/python -m pytest tests -q` → **90 passed (3.98s)**，与记录（90 passed, 3.92s）一致；额外只读复算三项：K>0 无券候选行为、压力 6 值实际偏差（≤0.39 分）、`STRESS_VARIANTS` 直喂 `stress_test` 的行为。
- 未检查：`coupon_tool/static/index.html`、`style.css` 全文（仅经服务器测试与关键词抽查）；未做浏览器端 UI 手工走查；`.flow/red-team.md`、`state.json` 内容细节（非代码）；XLSX 模板在真实 Excel 中的呈现（roundtrip 测试已覆盖解析）。

---

# Review Findings · 第二轮（修复复核）

## 审查结论：**PASS**

第一轮全部 12 条发现（1 BLOCKER + 2 MAJOR + 9 MINOR）均已正确修复且有测试覆盖；在仓库根复跑 `.venv/bin/python -m pytest tests -q` → **97 passed (3.88s)** 与记录一致；独立只读复算 6 项 + 复盘 5 条路径全部通过。规格轴抽查发现 1 个边缘缺陷（自定义无券标签时"暂不发券"决策的复盘基准回退到排序第一，UI 主路径不可触发）与 1 个延续的精度口径待确认项，均不构成阻断。

## 建议改进（SUGGESTION，二轮后已由主线顺手修复并补回归测试）
- review.py "暂不发券"按 enabled=False 识别无券行（tests/test_coupon_review.py::test_review_no_coupon_decision_with_custom_label 覆盖）
- app.js 复盘结果展示 selected_label/chosen_source（预测基准与来源可见，支撑门禁 D 审计）

## 待确认（UNVERIFIED，处置说明）
- 导出精度口径：候选表 CSV 金额列取整分、JSON 保留 6 位小数分——已定义为"统一定义输出精度"的既定口径（CSV 供人读、整分；JSON 供机器复核、全精度），M20 断言基于 JSON 与界面 metrics 全等。此处置记录在案。

## 复检明细
1. M01/K>0：`k_cost = ... if enabled else 0.0`；K=50000 时无券 ΔΠ=0、有券 fixed_costs=−50000 且分解对平逐位一致；测试参数化覆盖。✅
2. 复盘人工选择：显式 > 决策记录 > 排序第一；5 条路径实测通过。✅
3. 均衡显式尺度：缺失即 SpecError；objective_params 经 load_spec→to_dict 往返保留；增删"满159减30"其余 Score 逐位不变。✅
4. MINOR×9（容差/封存校验/受控亏损上限/上限同式/M15 行警示/死代码清理/replay 只读/变体预算/帕累托限可行）：全部修复确认。✅
