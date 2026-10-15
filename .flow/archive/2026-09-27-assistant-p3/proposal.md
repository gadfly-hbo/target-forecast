# Proposal — 测算工作台整合 P3：LLM 驱动（助手侧栏 + actions 能力声明）

来源：2026-09-27 会话，用户指示「P3」。本文件为 P3 flow 的最高规格源。P0/P1/P2 交付事实见 `.flow/archive/workbench-p{0,1,2}/`。

## 用户原始需求（最初愿景，逐字要点，2026-09-26）

「未来还要引入 pi agent sdk + llm 等，用 llm 驱动测算工作台。」

P0 分期路线对 P3 的定义（继承，不可推翻）：**P3：引入 pi agent sdk + LLM（助手侧栏、补 actions 声明、先自然语言调参+解读闭环，再考虑自主多步测算）**。

## 环境探查事实（ASSESS 取得，约束 P3 形态）

1. **pi agent sdk 已确证为 `@earendil-works/pi-agent-core`（npm/TypeScript）**，配套 `@earendil-works/pi-ai`（provider 抽象：anthropic-messages / openai-completions API，`getBuiltinModel` 内置模型表，`runAgentLoop` 代理循环）。用户 sibling 项目 deep-research（`src/adapters/live.ts`）与 flow-center（「pi-agent 工作流套壳工作台」）已在生产使用此栈——**不是假想依赖**。
2. **本仓库是纯 Python（stdlib）栈**，无 node/npm 构件；引入 pi-agent-core 意味着引入 Node sidecar 或换栈。
3. **本 shell 环境未发现 LLM API key 环境变量**（ANTHROPIC/OPENAI 均无）；deep-research 的 key 来源未确认（可能在交互式 shell 配置）。
4. 三工具 manifest 的 `actions` 字段均已留空（P0 预留），插件协议其余部分对助手场景完备（单 API 网关 `/t/{id}/api/`、状态栏、深链）。

## 本 flow（P3）范围

### 方向（细节在 PRD diff 门确认）

- **助手侧栏**：壳右侧可开合的助手面板，对话式交互；上下文 = 当前激活工具。
- **actions 能力声明填充**：三插件 manifest 补 `actions`（JSON Schema 描述可调用的测算能力），壳或助手后端据此生成 LLM tool 定义——P0 预留位的首次落地。
- **自然语言调参 + 解读闭环（P3 首要交付）**：用户对助手说「基准情景新客增速调到 20%」「解读一下为什么保守情景全渠道 GMV 下降」，助手调用工具完成并用人话回复。**自主多步测算是 P3 之后的演进，不在本 flow**（P0 路线原文）。
- **LLM 后端**：诚实面对栈差异（见红队 K1），推荐「助手后端抽象层 + pi-agent-core Node sidecar 为真身 + 离线降级」的分层形态，diff 门由用户拍板。

### 明确不做

- 自主多步测算/自动 agent 编排（P3 之后）。
- 更换现有三工具的技术栈；对 forecast/coupon/roi 业务逻辑的任何改动（actions 声明与必要的只读辅助端点除外，diff 门披露）。
- 真实广告平台/数据源接入。

## 开放问题（留给 PRD/GRILL）

- 架构：Node sidecar（pi-agent-core 真身）vs Python 直连 OpenAI 兼容 API vs 分层双后端——**含对本仓库引入 node 工具链的取舍**。
- LLM key 的配置形态（env / 本地配置文件，不入 git）。
- 助手的能力边界：只读解读 + 调参，还是也允许触发测算/导出（写操作确认门）。
- actions 的 Schema 粒度（每工具 3-6 个 action 为宜）。
