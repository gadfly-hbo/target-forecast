# PRD：重构阶段5（收官批）

> 规格来源：`.flow/proposal.md`。红队报告：`.flow/red-team.md`（GO，5 项先决条件全部采纳；含 NaN 配方实证与 GET 语义事实纠错）。

## Problem Statement

重构方案剩余三个复杂度热点（spec._check_behavior 19/31、exports.export_markdown 15/31、assistant service._execute 11/15）+ 三项历史遗留 + 跨测试文件的 HTTP helper 重复。红队实证：三个"行为不变"重构中两个（spec errors 顺序、markdown 字节）没有任何现有测试钉住其行为面，一个（assistant）有 4/8 分支零执行覆盖——照搬前四阶段"先门禁后重构"的纪律是本批成立的前提。

## Solution

七项任务、每项独立提交、门禁先行：三组 characterization/封存测试对现状先绿（spec 顺序钉死、markdown sha256、assistant 分支执行），随后三项行为不变重构 + 两项零风险清理 + NaN 负向测试 + helper 去重（以红队实测的三种 GET 语义地图为准）。

## User Stories

1. As a 维护者，I want `_check_behavior` 按连续块拆成小函数，so that 校验规则可局部阅读且 errors 顺序零漂移
2. As a 运营用户，I want 导出的决策摘要 markdown 字节级不变，so that 历史对比与归档不失效
3. As a 助手用户，I want assistant 的 8 条 action 分发语义不变，so that 问答/调参行为零变化
4. As a 审查者，I want 三组门禁（顺序字面量 / markdown sha256 / 分支执行测试）先行封存，so that "行为不变"可证伪
5. As a 维护者，I want HTTP 测试 helper 只有一份，so that 新测试不复制第三种 GET 语义
6. As a 维护者，I want NaN 引擎输出被 422 拒绝的行为有测试钉住，so that 阶段1 deliberate-change #5 的语义不回退

## Implementation Decisions

1. **A1 spec._check_behavior 拆分**：**按连续代码块切**（红队 K1：领域主题切分会把 reach_new 从循环错误后移到前——errors 顺序即 API 文案）。切分边界：①四名字概率循环（:177-184）②reach_new（:185）③q_mode/q_curve/q_table（:186-196）④conversion（:197-208）⑤new_basket（:209-219）。五个块函数按原顺序在 `_check_behavior` 内依次 extend；**门禁先行**：构造触发 ≥4 类错误的 fixture，断言 `validate_spec(spec)["errors"]` 精确等于完整列表字面量。errors 与 warnings 无混排（红队确认：warnings 全在 validate_spec）。
2. **A2 export_markdown 拆分**：按输出段落拆 `_section_*` 渲染函数；`add("")` 空行与 `---` 分隔线归属跟随段落；**门禁先行**：sha256 封存（decision 有/无 × stress 有/无 ≥2 形态，run_id 归一后 inline 哈希）。
3. **A3 assistant _execute 表驱动**：**门禁先行**：先补 4 条零覆盖分支的执行测试（get_state×3 工具共享分支、forecast__calc、coupon__list_runs 双形状、coupon__compare），照 `test_roi_set_plan_net_none_guard` 模式（Echo fixture + FakeHttp 分叉 + 摘要断言）。表形状：`{(tool_id, action): handler}` 或按现有 `x-action` 元数据 + 全名两级查键——保留 get_state 元数据优先判定顺序与兜底 `已执行 {name}`。
4. **B1 NaN 负向测试**（阶段1 遗留）：红队实证配方——`baskets[0]["amount_cents"] = 2*10**306` 经 `/api/compare` → 422 且 error 以"请求不合法"开头。**OverflowError 空洞（threshold=10**309 → 无响应）只记录交接卡不修**（范围外既有行为）。
5. **B2 e_pi_after 删除**（阶段4 红线保留项）：三处写零读，删除后指纹 19/19 必须仍绿（第二重保险）。
6. **B3 numpy 导入删除**：`target_forecast/server.py:17` 一行。
7. **C1 helper 去重**：新建 `tests/_http.py` 纯函数模块（prepend 模式可直接 import；不用 conftest fixture——放大 diff）。**以红队实测地图为准**：`_post` 四合一（timeout=60、JSON、捕获 HTTPError）；GET 保留**三种**命名清晰的语义——`get_raw`（bytes、抛 HTTPError）/ `get_json`（JSON、抛 HTTPError）/ `get_json_or_error`（JSON、捕获）——三文件改 import，各自调用点不改语义。**"抛异常 GET"是被 test_workbench 404 测试依赖的语义，禁止折叠**。
8. **提交粒度**（红队条件⑤）：每项独立提交——三组门禁测试可合一个 `test` 提交或随各自重构提交先行；顺序建议：门禁→A1→A2→A3→C1（test-only）→B1（test-only）→B2+B3（零风险清理，一个提交）。

## Testing Decisions

- 好测试 = 外部可观察行为（errors 列表字面量、markdown sha256、摘要串与调用序列、HTTP 状态码与错误文案）。
- 三组门禁对现状先绿后再动各自的生产代码；指纹门禁（tests/test_engine_fingerprint.py）在 B2 前后各跑一次。
- 回归：全量 `pytest`（当前基线 214 passed；本批新增约 8-10 条测试）。
- 复杂度复查：图谱 query_graph，三个目标函数拆分后无 ≥15 残留。

## Out of Scope

- OverflowError 空洞修复（记录）
- report.py 第三份 concat（阶段2 已划出）
- 前端静态文件、引擎数学、compare 的候选级 SpecError 吞噬语义
- 校验规则表驱动化（原方案"可选不必做"）

## PRD diff gate（相对 proposal.md 的差异）

proposal 硬约束全部保留。差异：

1. **A1 拆分方式修正**：提案开放问题 1 的"按校验主题"被**显式否决**——按连续块切（红队 K1：主题切分重排 errors 文案，无测试钉住，属违反硬约束 2 的诱导）。
2. **A3 增加前置**：4 条分支执行测试先行（红队 K3：无人区作业禁止）。
3. **C1 事实修正**：提案"两种 GET"错误——实为三种语义且"不捕获"被测试依赖；落点拍板 `tests/_http.py`（红队 K4）。
4. **B1 配方拍板**：红队实证的 2×10³⁰⁶ 配方，否决 mock 路线；OverflowError 空洞显式记录不修。
5. **新增**：每项独立提交的粒度要求（红队条件⑤）。

## GRILL 决议

### 第 1 轮（author-blind 子代理，2026-10-15）

- 见附录（若与本 PRD 正文冲突以正文为准）。

### 第 2 轮（主代理）

- 枚举零新增开放问题（七项的门禁、边界、提交序全部由红队条件+本 PRD 钉死）——**GRILL converged after 2 rounds**。

---

## GRILL 决议（替换占位）

### 第 1 轮（author-blind 子代理，2026-10-15，7 包全按推荐 (b) 采纳）

- **Q1 门禁A1 fixture**：五块全覆盖 + 块内多错误——`build_synthetic_spec()` 后**直接改 dataclass**（绕开 load_spec 的 float() 强转陷阱）：`redeem_natural=1.5, reach_new=1.5, q_mode="banana", q_curve={q_cap:1.5,lam:-1,d_ref:-1}, conversion={mode:relative,k:-1,s_max:-1}, new_basket=[{weight:0.6,amount_cents:"x",redeem:2}]`；断言 `validate_spec(spec)["errors"]` 精确等于完整字面量（基线/cost/constraints 干净 → errors 恰为 _check_behavior 输出）。
- **Q2 门禁A2 归一**：`run["run_id"] = "run-SEALED"` 在 dict 层覆写后再调 export_markdown（单点归一、无行格式耦合）；created_at 不渲染，run_id 是唯一非确定性。
- **Q3 门禁A2 形态**：3 形态——对角两形态（stress+decision 全开 / 全关）+ top 缺席形态（`{**run, "results": {**r, "ranking_rows": []}}` 手工截断——export_markdown 是 run dict 纯函数，合法 characterization）；新文件 `tests/test_exports_seal.py`；top 内部 else 分支（breakeven/decomposition/neighbors 缺席）记为接受的残余（substring 冒烟覆盖）。
- **Q4 A3 表形状**：两级——保留 `x-action == "get_state"` 元数据快路径原样，仅把 6 条全名 if/elif 换 `{name: handler}` dict（handler 为 `(service, args) -> str`），兜底 `已执行 {name}` 不变。action id 跨工具不唯一（forecast/roi 都有 calc），单键表否决。
- **Q5 C1 模块 API**：`tests/_http.py` 导出 `post(url, obj)` + `post_raw(url, data)`（共享响应处理）+ 三种 GET（get_raw / get_json 抛异常 / get_json_or_error 捕获）；`_post_raw` 不做 isinstance 多态合并。
- **Q6 C1 范围修正（两行）**：`tests/test_server.py` 的 `_get`（与 get_raw 语义逐字节相同）改 import get_raw；其**抛异常**的 `_post` 保持本地（无人需要的第 4 种语义）。这是对 PRD"三文件"的唯一范围扩展，随本决议批准。
- **Q7 提交序**：交错式——gate(A1)→A1→gate(A2)→A2→gate(A3)→A3→C1→B1→B2+B3，每个封存对未重构代码可审计先绿（阶段4 先例）。
- **已钉死无需提问**：B1 配方、B2 三写零读、B3、A1 五块边界（红队已核行号）、FakeHttp 模式、214 基线算术。

### 第 2 轮（主代理）

零新增开放问题——**GRILL converged after 2 rounds**。
