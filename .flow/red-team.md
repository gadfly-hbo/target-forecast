## Red-Team: 阶段5收官批——三个"行为不变"复杂度重构 + 三项遗留 + 测试 helper 去重（7 项一揽）

> fresh-context 红队，2026-10-15。全部结论基于本机代码实读 + 可执行实验（NaN 构造、HTTP 422 复现、基线 pytest 89 passed / 52.6s，覆盖六个受影响测试文件）。行号以当前工作区为准。

### Top Kill-Assumptions (ranked)

**K1（最优先）：spec 拆分按"校验主题"命名会把非连续代码段缝在一起，静默重排 API 可见的 errors 顺序——且现有测试完全不钉顺序**

- **Claim：** 提案硬约束 2：`_check_behavior` 拆成 `_check_reach / _check_q / _check_conversion` 等小函数后"errors/warnings 顺序不变（API 可见）"。
- **Steelman：** 现函数（spec.py:171-220）的 append 顺序天然按主题分段：四名字循环（reach_base/redeem_natural/redeem_topup/churn，:177-184）→ reach_new（:185）→ q_mode/q_curve/q_table（:186-196）→ conversion（:197-208）→ new_basket 权重/逐项/缺失（:209-219）。只要**按连续代码块切**、按原顺序拼接，顺序逐条保真，纯搬移零风险。
- **Fails if：** 实施者按**领域主题**而非**连续块**切——提案自己的命名正在诱导这件事：`_check_reach` 作为领域概念应同时管 `reach_base`（:177 循环内）和 `reach_new`（:185，位于 churn 之后）。合进一个 `_check_reach` 后，"新增触达 e⁺ 必须是 [0,1]…"会从 redeem/churn 错误**之后**移到**之前**——`load_spec` 用"；"拼接成单条 SpecError（spec.py:308），`/api/compare` 422 体（server.py:80 `场景不合法：{joined}`）、`/api/demo` 的 `validation.errors` 列表（前端按序渲染）、compare 候选级 violations 文案（compare.py:269）全部变文本。而**没有任何测试钉住顺序或拼接文本**：`test_validate_spec_reports_weight_and_probability_issues`（test_coupon_engine.py:206-212）用 `any()` 成员断言；test_coupon_storage.py:40 同类；全 tests/ 无一处断言含"；"的完整错误串。重排后 pytest 全绿，硬约束 2 已被违反而门禁无感——这正是阶段4 红队用 MUT 实证过的"现有测试对静默漂移全部放行"的同款盲区，且这次**没有指纹门禁兜底**。
- **Evidence：** 已完成（本红队实读）：顺序链 = `validate_spec` 拼接 `_check_semantics + _check_cost + _check_behavior`（spec.py:225），尾部再 append 受控亏损错误（:226-227）；`_check_behavior` 内部顺序如上。另注意提案开放问题"errors 与 warnings 在同一函数里混着 append？"——**答案是没有**：三个 `_check_*` 只产 errors，warnings 全在 `validate_spec`（:228-232），拆分无需处理 warnings 混排。
- **Kill criterion：** PRD 若拍板"领域主题切分"（reach_base+reach_new 同函数）而非"连续块切分"，或动工前不补顺序钉死测试，则该项不得自称"行为不变"。
- **Cheapest test：** 动工前加一条 characterization：构造一个同时触发 ≥4 类 behavior 错误的 fixture（如 `redeem_natural=1.5` + `reach_new=1.5` + 未知 `q_mode` + 缺 `new_basket`），断言 `validate_spec(...)["errors"]` **精确等于**完整列表字面量。约 10 行。

**K2：markdown"字节级不变"是本阶段唯一写了却没有任何门禁约束的硬约束**

- **Claim：** 硬约束 2："markdown 导出字节级不变（导出文件内容）"。
- **Steelman：** `export_markdown`（exports.py:79-170）是 `run` dict + `decision` 的纯函数，无 I/O 副作用、无时间依赖；按段落切 `_section_*`、每段原样搬 `add(...)` 调用串，字节保真是机械可达的。
- **Fails if：** `_section_*` 各自管理段尾空行——重复或丢失一个空行、`---` 分隔线位置漂移、某 else 分支措辞变化，pytest 依然全绿：现有覆盖只有 substring 冒烟（test_coupon_server.py:178-179）和文件名存在性（test_coupon_cli.py:22）。
- **Kill criterion：** 若 PRD 不为该项补字节门禁就开工，硬约束 2 的 markdown 半句不可证伪。
- **Cheapest test：** 动工前封存 sha256：`build_synthetic_spec → compare → record_run → export_markdown(run, decision=两种形态)`，对 `run_id` 归一后取哈希 inline 进测试（先例：test_engine_fingerprint.py）。decision 有/无、stress 有/无至少各封一形态，约 25 行。

**K3：assistant `_execute` 的 8 条分支有 4 条零执行覆盖，表驱动重构在无人区作业**

- **Claim：** 提案：`_execute`（11/15）"action 分发改表驱动"。
- **Steelman：** 确认门（G2）与写标志判定全在 `chat()`（service.py:61-69），`_execute` 是纯执行层——表驱动不碰确认门。且 3 条分支有精确断言（roi__calc 摘要逐字钉住、roi__set_plan_params 兜底回归、写暂存顺带只读查询回归）。
- **Fails if：** 表驱动丢失无覆盖分支的隐藏语义：(1) 分发键不统一——首分支按 `x-action` 元数据（get_state，service.py:156-157），其余 7 条按全名；(2) 每分支特有编排：forecast__set_scenario_params 4 次 HTTP+合并+`.replace("挑战", sc)` 字符串技巧；roi__calc 省参时双取默认；coupon__list_runs 对 list/dict 双形状容错；兜底 `return f"已执行 {name}"` 是未来 action 的安全网。而这 4 条（get_state×3、forecast__calc、coupon__list_runs、coupon__compare）**没有任何 fixture 驱动**（EchoBackend FIXTURES 只含 3 个 action；FakeHttp 对未预期路径 AssertionError）。
- **Kill criterion：** 表驱动 diff 触及 4 条无覆盖分支且未先补执行测试——该项剔除或降级为"只拆函数不改分发结构"。
- **Cheapest test：** 动工前照 `test_roi_set_plan_net_none_guard` 模式补 4 条：每条一个 Echo fixture + FakeHttp 分叉，断言摘要串与调用序列，每条约 12 行。

**K4：helper 去重的事实前提本身是错的——GET 有三种语义，不是两种，且其中"不捕获 HTTPError"是被 404 测试依赖的行为**

- **Claim：** 提案：三文件 `_post`/`_get` 去重，"test_coupon_server 的 `_get` 返回 bytes、test_workbench/_assistant_http 的返回 parsed JSON"。
- **Steelman：** `_post` 家族确实同构：四份（coupon_server `_post`/`_post_raw`、workbench `_post`、assistant_http `_post`）都是 timeout=60、JSON 体、HTTPError 捕获后返回 `(e.code, json.loads(e.read()))`——去重零风险。落点上 pytest prepend 模式把 tests/ 挂进 sys.path（无 `__init__.py`），兄弟模块 `tests/_http.py` 可直接 import，比 conftest fixture diff 更小。
- **Fails if：** 按提案的错误地图"统一 `_get` 返回 JSON"动手。实测真相是**三种** GET：coupon_server `_get`（:26-28）与 workbench `_get`（:69-71）都返回 **bytes 且不捕获 HTTPError**（提案说 workbench 返回 JSON——错）；assistant_http `_get`（:63-65）返回 **JSON 也不捕获**；coupon_server `_get_json`（:51-56）返回 JSON **且捕获**。"不捕获"是被依赖的语义：test_workbench.py:111-120 两条 404 测试用 `pytest.raises(urllib.error.HTTPError)` 包住 `_get`。
- **Kill criterion：** 去重方案把"抛异常 GET"与"捕获 GET"折叠成同一函数，即违反硬约束 4。
- **Cheapest test：** 保留三个命名清晰的 GET（`_get_raw` / `_get_json` 抛异常版 / `_get_json_or_error` 捕获版）或每文件留薄包装，`_post` 四合一。

### What's Well-Reasoned

- **NaN 负向测试不仅可构造，而且有免 mock 的合法输入配方——提案开放问题直接关闭（红队已端到端复现）。** `_check_semantics` 只查 `amount_cents > 0`（spec.py:133）无上界：`synthetic_spec_dict()` 改 `baskets[0]["amount_cents"] = 2*10**306`，`load_spec` strict 通过；`pi_coupon` 与 `pi0_total` 各自浮点 silent 溢出为 `inf`，`delta_pi = inf − inf = nan`（实测 `incremental_contribution_cents = nan`）；`json_bytes(allow_nan=False)` 抛 `ValueError`（httpkit.py:25），被 `route_post` 捕获（server.py:334-335）。真机 HTTP 实测：**422 `{"error": "请求不合法：Out of range float values are not JSON compliant"}`**——正是阶段1 deliberate-change #5 的语义。注意配方边界：让**乘积**溢出（单项 float ≤1.8e308 可正常转换），别让转换本身溢出——`t = 10**309` 会在 engine.py:148/:298 抛 `OverflowError`，不在 route_post 捕获元组里，结果是无响应/连接重置而非 422（**本批范围外的既有空洞**，只在交接卡记录，不顺手修）。
- **e_pi_after 删除是本仓可证零漂移的最好案例。** 全仓 grep：仅三处出现（engine.py:288 初始化、:306 未启用路径 `+=`、:316 启用路径 `+=`），零读取；`_aggregate_ledger` 收的是 `e_pi0`；tests/ 无引用。两条写路径都被 battery 覆盖（`golden_no_coupon` 走 :306，启用用例走 :316）。指纹门禁 19/19 是第二重保险。
- **numpy 导入确认死代码。** `target_forecast/server.py:17`，文件内无任何 `np.` 使用。一行删除安全。
- **基线绿。** 六个受影响测试文件 89 passed / 52.6s，重构起点无暗债。

### What I Couldn't Assess

- 实施者纪律——K1-K3 的门禁都只有十几行，但"先门禁后动手"能否顶住 7 项一揽的完成压力。缓解：**每项独立提交 + 各自门禁先行**。
- 前端对 errors 顺序的展示假设（按最保守口径处理：顺序即用户可见）。
- 复杂度降幅目标数未验证。

### 结论：GO（附先决条件）

1. **动工前补三组门禁**（K1 顺序钉死测试、K2 markdown sha256 封存、K3 四条分支执行测试），先对现状跑绿。
2. **spec 拆分按连续块切，不按领域主题切**；`_check_reach(reach_base+reach_new)` 命名诱导必须显式否决。
3. **helper 去重以实测地图为准**（三种 GET 语义 + 四份同构 `_post`），修正提案第 7 项的错误描述；落点 `tests/_http.py` 纯函数模块。
4. **NaN 测试用已验证配方**（`amount_cents = 2*10**306`，断言 422 + "请求不合法"），不走 mock；OverflowError 空洞只记录不修。
5. **每项独立提交**，e_pi_after 与 numpy 两项零风险可先行。
