## Red-Team: 阶段4 拆分 `coupon_tool/engine.py::simulate`（只搬移、逐位不变、pytest 绿）

**结论先行：GO（附 3 项开工前置条件）。** 没有任何 kill-assumption 的 kill criterion 已被满足——搬移路径本身成立；但计划的**验证故事**已被实验证伪：现有 pytest 套件对三类真实漂移全部放行（68/68 绿）。以下是证据、排序与最廉价的修复。

**实验方法**：在 /tmp 的仓库副本上注入三个代表性"接线漂移"突变，跑全量 coupon 测试（68 项）并与逐字段指纹（sha256 of full `SimulationResult` JSON，18+1 用例）比对。基线：coupon 子集 68 passed / 0.5s；全仓 195 passed / 109.5s。

| 突变 | 内容 | pytest | 指纹 |
|---|---|---|---|
| MUT1 | 桶穿 limitation 从循环内挪到汇总段（顺序漂移） | **68 绿** | 组合用例捕获：`dad16601057c4b99`→`2ce1310d0bdf148d`，桶穿与 C₀=0 两条互换 |
| MUT2 | `topup_at_threshold` 改为"末篮子覆盖"语义 | **68 绿** | mixed-topup 用例捕获：`a9c0ad3fc12d310f`→`60e8a2c51ca0b93e`，丢一条 limitation |
| MUT3 | `l_rate` 奇偶分桶二级重聚合（浮点结合序漂移） | **68 绿** | 2/18 用例捕获：`197dbc7f09ba5813`→`b0dd529027b1d36b` 等 |

三个突变都**不是算术错误**，恰恰是"提取 helper 后接线"最容易犯的那类错——全部静默通过提案声称的安全网。

---

### Top Kill-Assumptions（按 影响×可能性×可测性 排序）

#### 1.「pytest 绿 + 黄金数值 = 逐位不变的充分验证」——**已被证伪**
- **Claim**：约束2 的安全网是 `test_coupon_engine.py` 黄金数值与 4.6 对平断言（proposal.md:26）。
- **Steelman**：黄金表容差确实紧——实际 `TOL_CENTS = 1`（tests/test_coupon_engine.py:14）和 `abs=2`（tests/test_coupon_compare.py:30），比提案写的"±100"强 50 倍；对平断言 ±1 分。能抓住任何公式级错误（元级漂移）。
- **Fails if**：漂移小于容差——MUT1/2/3 全部低于阈值。limitations 顺序无任何测试钉住（所有断言都是 `any(...)`，test_coupon_engine.py:173、test_coupon_ingest.py:86,120）；混合 `topup_amount_cents` 场景仓库里不存在；未取整浮点字段（`conversion_rate`/`delta_c`/`roi`/`orders` 系）的 1-ulp 漂移远小于 5e-6。另：`Store.replay_run` 的 M20"逐位一致"（storage.py:100）只在同一份代码内对比（test_coupon_storage.py:30-32 同进程两次计算），跨重构不设防；且 `workspace/coupon/runs/` 当前为空，**没有可用的重构前封存运行**。
- **Evidence to get this week**：上表（已取得）。
- **Kill criterion**：若流程拒绝增加指纹门禁，约束2 完全依赖实施纪律 → 该约束形同虚设。
- **Cheapest test**（~30 行、0.2s、已验证稳定）：重构前对一组候选跑 `simulate`，序列化 `{candidate, metrics, ledger, limitations, decomposition, validation}` 为 `json.dumps(..., sort_keys=True)` 取 sha256，封存；重构后必须逐 hash 相等。battery 必须**刻意组合** limitation 触发条件——我最初的 18 用例漏了"桶穿+③"组合，MUT1 一度漏网，补组合用例后才捕获。仓库有直接先例：阶段1 红队盲区转正为 `tests/test_httpkit_characterization.py`。金额字段已被 `round(…,6)` 量化（1e-6 分以下漂移在输出上本就不可观测），比特敏感面是未取整字段——指纹天然覆盖。

#### 2.「limitations 列表可跨 4 个区域共享、顺序天然保住」——顺序是用户可见输出，且无测试钉住
- **Claim**：开放问题（proposal.md:42）在"就地 append"与"各自返回再合并"之间未定，仅倾向前者。
- **Steelman**：就地 append 传引用确实零顺序风险；提案也明确拒绝了"顺手修重复 append 模式"（proposal.md:38）。
- **Fails if**：实现者选了"返回新列表再合并"（开放问题的另一半）——桶穿条目（engine.py:191-195，循环内）与 ③ 的条目（engine.py:212,218）及汇总段条目（engine.py:254-265）的相对顺序即漂移。该顺序在 compare 行级 `limitations`（compare.py:276）、前端 warn-card（static/app.js:295,421）、导出摘要"已知限制"（exports.py:153）三处用户可见。
- **Cheapest test**：组合用例（桶穿 + C₀=0）进 battery。
- **Kill criterion**：方案必须现在把开放问题定死为"就地 append 传引用，或 append 全部留在 `simulate`、helper 纯函数"，**禁止返回-合并**。

#### 3.「`topup_at_threshold` 是普通局部标志，随 helper 返回即可」——它是跨循环迭代的粘性 OR
- **Steelman**：合成场景所有篮子都缺省（全 True），任何合理接线都得到 True。
- **Fails if**：`_basket_branches` 返回"本篮子标志"而 caller 直接赋值不 OR（engine.py:179-180 现为 `= True` 粘性赋值）——混合 `topup_amount_cents` 场景（部分篮子显式、部分缺省）丢失"恰好凑单"limitation（MUT2 证明 68 绿、指纹捕获）。仓库无任何测试构造混合场景。
- **Cheapest test**：battery 加两个 mixed-topup 用例（首篮缺省 / 末篮缺省）。
- **Kill criterion**：接线必须 `topup_at_threshold = topup_at_threshold or flag_i` 或该标志赋值原样留在 caller 循环内。

#### 4.「只搬移 ⇒ 浮点结果天然不变」——对，但风险全在"接线"而非"搬移"
- **Steelman**：成立。CPython 提取函数不改变 FP 语义；`sum(gen)` 左折叠 == 顺序 `+=`；只要每条语句的求值序不变，结果逐位相同。真正的敏感累加是 `e_pi0`（→`pi0_total`，engine.py:244）、`l_rate`（→retention/delta_c）、`_sum(key)` 与 `_delta_vs_pi0`（均按 **ledger 行序**求和）。
- **Fails if**：接线时重聚合——分组小计、`math.fsum`、"先收集各组再相加"、或任何 ledger 行序变化（`_sum`/decomposition/导出 CSV `export_ledger_csv` exports.py:58-68 全按行序）。MUT3 证明 1-ulp 级漂移全套件静默。
- **Cheapest test**：指纹盯未取整字段（MUT3 被 18 用例中的 2 例捕获，覆盖已够）。
- **Kill criterion**：实现规约明写三条红线：不引入 fsum/分组求和；不重排 ledger；每个累加器的加法项序逐句保持。

#### 5.「五个 helper 签名照提案写即可」——签名草稿有字面缺陷
- **Fails if**：照抄实现。`_conversion_response(spec, c0, retention, enabled, limitations)` **缺 `t`、`f`**——相对模式 `s_plus = min(k·(f/t), s_max)` 必需 F/T（engine.py:214）；`_decompose(ledger, pi0_by_basket)` **缺 `k_cost`**（`fixed_costs = -float(k_cost)`，engine.py:290）；桶穿检查悬在 ②/③ 边界之间，`limitations` 参数的归属未写明；`_validate_candidate` 需**返回 `(enabled, t, f)`** 并保留 `f = candidate.get("face_value_cents", 0) or 0` 的 None→0 强转与"候选校验先于 `validate_spec(spec)`"的顺序（compare.py:267-271 的 per-candidate catch 依赖 SpecError 从 simulate 内抛出；该先后顺序目前无测试钉住，保持即可）。
- **Cheapest test**：开工前修签名草稿——比照本清单逐参数核对一遍（10 分钟）。
- **Kill criterion**：无——这是可修缺陷，不是路径问题。

---

### What's Well-Reasoned

- **接缝真实存在**：①②③④+4.6 的注释块与代码块对齐（engine.py:165/174/204/233/267），沿边界拆是最小 diff 路径。
- **范围控制正确**：拒绝"顺手重构成类/管道"、拒绝"顺手修 limitations 重复 append"（proposal.md:37-38）——正是本报告第 2 条要求的纪律。
- **公共 API 面干净**：grep 证实只有 `compare.py:11`、`stress.py:13`、`__init__.py:9` 导入 engine，且只取 `simulate`/`SimulationResult`——约束3 无暗礁。
- **验证网比提案自述的更强**（±1 分而非 ±100 分）——抓公式级错误绰绰有余，缺口只在比特级。
- **浮点搬移本身安全**（见 K4 steelman）——这是该计划敢于承诺逐位不变的正当理由。

### What I Couldn't Assess

- 实施者纪律——只能靠指纹门禁兜底，无法事前评估。
- 复杂度实际降幅：提案未给目标数（阶段3 先例 29/105→4/6，可预期但未承诺）。
- "~50 行编排"是否达成：依赖签名修正后的参数列表长度（`_aggregate_ledger` 需要 ledger、n_visitors、c0、e_pi0、l_rate、d_c_plus、enabled——开放问题已自认）。
- `e_pi_after` 的处置：它是**死累加器**（engine.py:140,158,202 只写不读；`pi_coupon` 实际来自 ledger 的 `_sum`）。提案未提。建议本阶段原样搬（守住"只搬移"字面），删除留待阶段5 单独提交。

### 开工前置条件（GO 的组成部分）

1. **指纹门禁**：重构前生成并封存 battery 指纹（下表 19 用例 + 桶穿+C₀=0 组合用例），重构后逐 hash 相等才算完成；照 `tests/test_httpkit_characterization.py` 先例转正为测试。注意 hash 绑定本机 Python/FP 平台，需在重构当次生成。
2. **修签名**：③ 补 `t,f`；`_decompose` 补 `k_cost`；② 写明桶穿 limitation 归属；`_validate_candidate` 返回 `(enabled, t, f)`。
3. **三条接线红线 + 一条保留**：limitations 就地 append（禁返回合并）；topup 标志跨篮子 OR；禁 fsum/分组求和/ledger 重排；`e_pi_after` 原样保留。

**基线指纹（2026-10-15，本机 .venv，重构后须逐个相等）**

```
golden:无券 16634525229d2f2e   golden:满79减5 299c771b592a7f7d
golden:满99减10 77e4165f6c2998d0   golden:满109减5 440df9f9dca3d613
golden:满129减5 4859a42dcd4d4edd   golden:满139减5 5220de8e50cc8550
golden:满139减10 197dbc7f09ba5813  golden:满139减20 151cc7fa2cc724fa
golden:满159减5 487b0502d959979c   golden:满159减10 450c92b8c786c3a2
noN f9b06638d064eb8f    c0zero 32360df478aed4d2    absbig 34306f00cb131d2f
straddle+fees 100a9b19088c207a   mixed-topup-0default a9c0ad3fc12d310f
mixed-topup-4default bc0f9797f934faa3   multinew b4b145c2e0badbc27
qtable 06d4df090b846b6d   [组合用例 桶穿+C₀=0] dad16601057c4b99
```

（battery 覆盖：黄金表 10 候选、无 N、C₀=0、绝对 ΔC⁺ 超限、桶穿+费用+K、两个混合 topup、多新增篮子、q_mode=table、桶穿+C₀=0 组合。生成脚本即"对每用例 serialize 全量 SimulationResult 取 sha256"，约 30 行，二次运行已验证稳定。）

**Verdict: GO** —— 无 kill criterion 已满足；所有已证缺口（验证门禁、签名草稿、接线红线）都有当天可完成的廉价修复，且修复后该计划的风险面收敛到"纯机械搬移"。
