# PRD — 测算工作台整合 P3：LLM 驱动（助手侧栏 + actions 声明 + 调参/解读闭环）

规格源优先级：`.flow/proposal.md`（P3）> P0/P1/P2 继承约束 > 本 PRD > 实现建议。红队：`.flow/red-team.md`（GO，K1-K5）。

## Problem Statement

工作台已有三个测算工具，但调参与解读依赖用户自己理解口径与参数：改一组增速要手动在 Inspector 里逐个输入，看结果后要自己判断「为什么保守情景差了」。用户最初的愿景是用 LLM 驱动工作台——用自然语言完成调参与解读。P0 已在插件 manifest 预留 `actions` 能力声明位，P3 是它首次落地。

## Solution

壳右侧新增可开合的**助手侧栏**：用户用自然语言说话，助手把意图转成对当前工具 API 的调用（tool calling），并用人话解读返回。三插件 manifest 补齐 `actions` JSON Schema；助手后端为**可插拔抽象层**，真身优先 pi-agent-core sidecar（与 deep-research 同栈），无 sidecar/key 时优雅降级（助手显示未配置说明，不影响工作台其他功能）。

## User Stories

1. 作为使用者，我想在壳右侧打开助手面板直接问「基准情景净贡献是多少」，得到带数字的人话回答，以便不学习 API 也能拿结果。
2. 作为使用者，我想说「把挑战情景新客增速调到 25%」并让助手改 forecast 的参数，以便免手动找输入框。
3. 作为使用者，我想对写操作有确认门（参数变更列表 + 我点确认才生效），以便 LLM 误调不直接落地。
4. 作为使用者，我想问「为什么保守情景全渠道 GMV 下降」得到基于当前数据的解读，以便理解结论成因。
5. 作为维护者，我想 actions 声明从 manifest 机械生成 LLM tool 定义，以便第四工具接入时助手自动会用它。
6. 作为维护者，我想无 LLM key / 无 sidecar 时助手优雅降级而不是报错，以便工作台离线可用性不被破坏。
7. 作为维护者，我想助手全链路有回放后端驱动的回归测试，以便 LLM 不确定性不摧毁测试纪律。
8. 作为维护者，我想 key 配置走 env 或本地 gitignore 文件，以便凭证不进仓库。

## Implementation Decisions

### D1 — 架构：助手后端抽象层 + sidecar 优先（diff 门核心，吸收红队 K1）

- `workbench/assistant/` 包：`backend.py` 定义后端协议（`chat(messages, tools) -> 回复+tool_calls`）；`tools.py` 从全插件 manifest 的 actions 生成 tool 定义；`service.py` 编排一轮「LLM 调用 → tool 执行（走 /t/{id}/api/ 内部直调或 HTTP）→ 结果回灌」。
- **后端优先级**：`PiSidecarBackend`（HTTP 调本机 Node sidecar，sidecar 内用 pi-agent-core + pi-ai，复用 deep-research 的 provider 配置形态）→ `OpenAiCompatBackend`（stdlib urllib 直连 OpenAI 兼容 API）→ `EchoBackend`（回放/测试用，从预录响应驱动，**明确标注非真 LLM**）。
- sidecar 代码放 `assistant-sidecar/`（独立 package.json，`@earendil-works/pi-agent-core`），Python 壳不 import 它、只代理；启动脚本在 node 可用时自动起 sidecar，不可用则降级。
- **关键取舍（diff 门确认）**：此形态把 node 工具链接入本仓库。备选：纯 Python 直连形态（不引入 sidecar，pi-agent 留作未来后端）。

### D2 — actions 声明（diff 门确认粒度）

每工具 2-3 个 action，JSON Schema 参数，语义对齐现有 API：

- **forecast**：`get_state`（只读）；`calc`（提交情景参数 → 三视角结果，参数结构对齐 /api/calc）；`set_scenario_params`（调参意图 → 生成参数补丁，写操作）。
- **coupon**：`get_state`；`compare`（scenario 全文测算）；`list_runs`（封存运行清单）。coupon 场景全文复杂，P3 只开放只读与「指定 scenario_id 重算」，不写场景。
- **roi**：`get_state`；`calc`（plans+scenarios）；`set_plan_params`（单计划参数补丁，写操作）。

写类 action（set_*）在助手侧栏渲染确认门：列出将变更的字段与新值，用户点击确认才执行（K4）。

### D3 — 助手端点与壳前端

- 壳新增 `POST /api/assistant/chat`：请求 {message, history, tool_id} → 响应 {reply, tool_calls:[{action, args, result_summary}], pending_confirmation?}。后端不可用时返回 503 + 配置说明文案。
- 壳前端右侧助手面板（可开合，宽度 ~320px，Xanthil token）：消息列表、输入框、写操作确认卡。助手操作后若影响 iframe 内展示，通过 iframe reload（`frame.contentWindow.location.reload()`）刷新，**不做跨 iframe 状态桥**（K5）。
- 助手上下文注入：当前工具 id + 该工具 /api/state 摘要（数值太大时只注入 totals/基线级摘要），控制 token。

### D4 — key 与配置（吸收 K2；用户已确认：小米 MIMO，复用 ZCode 配置）

**实测确认（ASSESS 探针，两 API 均 200）**：MIMO base `https://token-plan-cn.xiaomimimo.com/v1`，模型 `mimo-v2.6-pro`（1M 上下文，reasoning 模型，chat/completions 与 responses 两形态均可用）。ZCode key 位置：`~/.zcode/v2/provider_config.json` → `providerConfigRules.providerRules` 中 `providerName: 小米` 条目的 `config.access.apiKey`（本机可读）。

- **key 解析优先级**：`workspace/assistant.env`（gitignored，用户手写覆盖）→ 读 `~/.zcode/v2/provider_config.json` 的小米条目 → env `WORKBENCH_LLM_API_KEY`/`BASE_URL`/`MODEL`。
- sidecar 用 pi-ai 的 **openai-completions** API 形态（deep-research 同款适配路径，tool calling 走 chat/completions 的 tools 字段；MIMO 实测支持）。
- 后端选择：自动探测（sidecar 可达 → sidecar；有 key → openai-compat 直连；否则 echo 回放）；可用 env `WORKBENCH_LLM_BACKEND` 强制。
- 无 key 时助手面板显示配置指引（503 降级文案含路径说明）。

### D5 — 回放后端与测试

- `EchoBackend` 从 `workbench/assistant/fixtures/` 预录响应（message → reply + tool_calls 脚本）驱动，测试用它走完整链路（意图→tool 执行→确认门→回复）。
- 单测：tools 生成器（schema 完整、可序列化、与 manifest 对齐）、service 编排（一轮闭环、写操作确认门、后端降级 503）、各后端适配器（Echo 全链路；OpenAI 适配器 mock HTTP）。
- 存量 145 项测试零断言修改。

## Testing Decisions

- **主 seam：service 编排纯函数**（tests/test_assistant_service.py）：Echo 后端注入 → 问「净贡献」→ 断言 tool_call 选对 action、结果数字进入回复；写操作 → 断言返回 pending_confirmation 且未执行；确认后执行并返回 summary。
- **tools seam**（tests/test_assistant_tools.py）：三工具 actions 存在、JSON Schema 合法（必填/类型/枚举）、生成器输出可被 json 序列化。
- **HTTP seam**（tests/test_workbench.py 增补）：/api/assistant/chat 端到端（Echo 后端下）、后端不可用 → 503 降级文案。
- **回归 seam**：全部存量测试零断言修改。

## Out of Scope

- 自主多步测算 / agent 编排（P3 之后演进，P0 路线原文）。
- 跨 iframe 状态感知、工具页内部状态桥（K5 kill criterion）。
- coupon 场景全文写操作、真实数据源接入。
- LLM 真身联调（key/sidecar 的实机验收列为用户侧；本 flow 交付回放后端 + 适配器 + 配置路径）。

## GRILL 决议（自我拷问，2026-09-27）

约束：P3 proposal 与继承决策不重新讨论；以下均为 PRD 未细化开放点，按推荐自答，无升级项。

**G1 — sidecar provider 接线：** `assistant-sidecar/` 为最小 Node 服务（express 不引入，stdlib http 或 pi 生态惯例——实现期参照 deep-research `src/adapters/live.ts` 的 `runAgentLoop` + `getBuiltinModel` 用法）；自定义 provider 传 baseUrl+apiKey（openai-completions 形态），model 默认 `mimo-v2.6-pro`，可用 env/assistant.env 覆盖。sidecar 端口 8321。

**G2 — 写操作确认门协议：** 两步——助手响应可带 `pending_confirmation: {call_id, action, args, preview}`（preview=将变更的字段/值摘要），此时**不执行**；前端确认卡经第二次请求 `{confirm: call_id}` 才执行并返回最终 summary。只读 action 直接执行。call_id 一次性、与会话绑定。

**G3 — 上下文注入裁剪：** 助手请求的 system 上下文只注入轻量摘要（工具名/平台清单/demo_used/默认参数），全量数值一律经 tool_call 现取，控制 token（reasoning 模型 prompt 费不可忽视）。

**G4 — 会话历史：** 存前端内存（刷新即新会话），无服务端持久化——本地单人工具，不做账号级会话（K5）。

**G5 — sidecar 生命周期：** 壳 `serve` 时探测 `node` 与 sidecar 构建产物（`assistant-sidecar/dist/server.js`），可用则以子进程拉起、退出时回收；探测失败自动降级 openai-compat/echo，启动日志明示当前后端。启动脚本不变（壳统一负责）。

**G6 — echo 回放 fixtures：** 3 个预录脚本——①解读类（问净贡献→get_state/calc→数字进入回复）②调参类（改增速→pending_confirmation→确认→summary）③越界类（要求改 coupon 场景→回复不支持并说明）。回放文件标注「合成响应，非 LLM 输出」。

**G7 — 工具执行路径：** 助手 service 在壳进程内直接调用插件 route 函数层不现实（需构造 handler），改为内部 HTTP 回环（urllib 打本壳 /t/{id}/api/ 端点，随机端口场景用壳实际端口）——与外部路径完全一致，行为无分叉。

## Further Notes

- sidecar 的最小形态：一个 `chat` 端点，内部 runAgentLoop 带 tools（与 deep-research 的 LiveModelConfig 同构）；pi-ai provider 配置沿用用户已有习惯。
- 若 diff 门改选纯 Python 形态，sidecar 目录与相关后端不建，D1 其余不变（抽象层本来就允许多后端）。
