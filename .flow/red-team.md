## Red-Team: OverflowError 空洞修复提案——spec/engine 加 float 范围上限 + route_post 兜底捕获

红队基线：全部结论以本机对当前代码（main @ 7c66ee6）的实测与逐行阅读为准，不依赖提案自述。以下探针均已在 `.venv` 实际执行。

### Top Kill-Assumptions (ranked)

**1. 「兜底层 route_post 加 OverflowError 是 belt-and-braces / 防御未来」——错误定位，它是主承重墙。**
- **Claim：** 提案 §修复方案-2 称兜底层仅"防御未来新的转换点"，真正的修复在 `_int_cents` 与 `_validate_candidate` 两处输入校验。
- **Fails if：** 兜底层被审查者按"防御性、可裁剪"砍掉——那么以下今天同样连接重置的路径**全部继续裸奔**，且 `_int_cents` 上限一个也救不了，因为它们不是整数分、不经过 Basket，而是 `load_spec` 内部的 float 强转（`coupon_tool/spec.py:264,269-277,282,296`）：`baseline.conversion_rate`、`cost.margin_base_rate / margin_addon_rate / merchant_share_rho / fixed_fee_cents / fee_rate / return_adj_cents / fixed_activity_cost_cents`、`behavior.reach_new`、`constraints.min_incremental_contribution_cents`，共 10 个字段。实测：conversion_rate=10**309 / margin_base_rate=10**309 / reach_new=10**309 → load_spec 内 OverflowError（spec.py:323 的 except 元组接不住 ArithmeticError）→ 今天就是连接重置。同一兜底还是这些路径的唯一覆盖：`q_table[].q`（engine.py:46，实测崩溃）、`new_basket[].weight`（engine.py:328，实测崩溃）、`_breakeven` 的 `amt * m_j`（compare.py:163，在 per-candidate catch 之外）、`/api/import` 行内巨大整数（ingest.py:66,82 只接 TypeError/ValueError）、q_curve 的 lam/d_ref、conversion 的 k/s_max/delta_c_plus。
- **Kill criterion：** 若实现只落层 1 不落层 2，任一上述字段注入 10**309 仍 RemoteDisconnected——提案按其一句话目标即告失败。
- **Cheapest test：** 修复后注入 `conversion_rate=10**309` 与 `q_table[0].q=10**309`，断言 422 而非断连。

**2. 「复现证据：四条路径全部」——范围低估约 3 倍，且修复路径的响应形状不一致。**
- **Claim：** 崩溃面就是表格里的四条 int-cents 路径。
- **Fails if：** 按四条写回归矩阵——10+ 字段无一入矩阵；且修完后同一类坏输入出现三种 HTTP 形状：篮子金额 → 422"场景不合法"；候选 t/f → 200+coupon_legality 不可行行（app.js:269 已能渲染）；new_basket/q 值/conversion_rate → 422"请求不合法：int too large to convert to float"（英文内部文案面向中文工作台）。`_validate_candidate` 的 200 行语义经查证正确：与 F≥T 同机制，`/api/stress`、`/api/run` 经同一 compare() 安全继承（stress.py:71-72 跳过 metrics=None 行）；stress 会静默丢弃该候选行而 compare 展示不可行行——可接受，写进行为说明。
- **Cheapest test：** `load_spec` 的 except 元组加 OverflowError 并 `raise SpecError(...) from exc`——一行，让 load_spec 内溢出归入"场景不合法"文案族；矩阵补 conversion_rate、q_table.q、new_basket.weight、/api/import 四条。

**3. 「指纹门禁天然保持绿」——结论对，但两个实现级地雷。**
- **Fails if：** (a) 顺手 bump ENGINE_VERSION——指纹覆盖 SimulationResult.engine_version，19/19 全红；(b) 新 SpecError 文案对 t 做 float 除法——实测 `10**311/100 → OverflowError`（商超范围时 int/int 真除会溢出），异常在 raise 路径内再次溢出，炸穿 compare 的 per-candidate catch，200 行语义退化为兜底 422。
- **Kill criterion：** 任一指纹红，或 t=10**311 时未走 200 语义。
- **Cheapest test：** 改后跑指纹测试；加一条 t=10**311 断言 200+不可行行（钉死文案不含 float 除法，用 `//` 或原值插值）。

**4. 开放问题 2 的前提错误：桶界 10³⁰⁹ 经 t/100 除法溢出——不成立。**
- 实测 `10**309 / 100 = 1e+307`（可表示，无异常），完整 compare 正常跑完；真溢出阈值是商超 float 范围（桶界 ≥ ~1.8e310，实测 10**312 → OverflowError 由兜底接住变 422）。该面在 10³⁰⁹ 量级不是崩溃路径，≥1.8e310 由兜底覆盖——本批不纳入对，但理由按实测改写，防后人按错误前提补修。

**5. 硬约束 1 与 sys.float_info.max 比较——steelman 通过。**
- CPython int/float 比较精确不抛：`10**400 > sys.float_info.max → True`；不存在通过上界却 float() 失败的整数（上界只比必要条件严一格，无害）；2×10³⁰⁶ ≤ max 成立，NaN 配方与改动不相交；route_post 元组加 OverflowError 不改任何已钉文案（grep 证实无路径以 OverflowError 产生 pinned 消息，SpecError 优先分支次序不动）。

### What's Well-Reasoned

- 篮子 choke point 选点正确（Basket.__post_init__ 是 amount/topup 统一入口，崩溃点 engine.py:99/148/329 与代码逐行相符）。
- 候选 t/f 的 200+不可行行语义正确且全链路一致（compare.py:266-271；label 的 `满{t // 100}` 整数地板除不炸）。
- 硬约束机械保障：battery 最大 20000 分 vs 上界 1.8e308；顺序钉死测试用普通值绕过构造路径。
- 周边已核清：壳复用 route_post、assistant 走回环（兜底自动覆盖）；/api/review params_patch 先 load_spec 后 save 不留半成品；CLI 对 SpecError 已 exit 2（开放问题 4 关闭）。

### What I Couldn't Assess

- 兜底文案归属是产品措辞决策——若采纳 load_spec 内 OverflowError→SpecError 一行改进，scenario 字段族自然归位"场景不合法"，问题大半消解。
- CLI 对修复前已落盘的含巨大值 scenarios/*.json 仍裸 traceback（兜底只在 HTTP 侧）——极窄残余，记"限制"一节不加码。

**裁决：GO**（无 kill criterion 已满足）。准入条件：① 层 2 改标为**必选主修复**，回归矩阵至少补 conversion_rate、q_table.q、new_basket.weight、/api/import 四条；② 不 bump ENGINE_VERSION，新 SpecError 文案禁止对 t/f 做 float 除法（用 `//` 或原值插值）；③ 桶界前提按实测改写（本批不纳入）。
