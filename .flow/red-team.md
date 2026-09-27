# Red-Team: 测算工作台 P3 — LLM 驱动（助手侧栏 + actions 声明 + 调参/解读闭环）

## Top Kill-Assumptions (ranked)

### K1 —「引入 pi agent sdk」与纯 Python 仓库的工具链冲突
- **Claim:** 可以用 pi-agent-core 驱动工作台助手。
- **Steelman:** pi-agent-core 是用户已验证的栈（deep-research 生产在用）；sidecar 形态（Node 小服务 + Python 壳代理）是成熟解耦模式；助手后端抽象层让 sidecar 可插拔。
- **Fails if:** 用户不接受本仓库引入 node/npm（双机都要装、要同步 node_modules、启动脚本变复杂），或者 sidecar 的运维成本超过其价值——尤其是 P3 首要闭环（调参+解读）其实只需要「一次 LLM 调用 + 工具调用」，pi-agent 的完整 agent 循环在此阶段收益有限。
- **Evidence（已取）:** 本仓库 requirements.txt 仅 pandas/openpyxl/PyYAML/pytest，全部 stdlib server；sibling 项目证明 pi 栈可用但均为 TS 项目；双机同步现状是 git 同步代码 + 各自维护数据——node_modules 不入 git，双端要各自 npm install。
- **Kill criterion:** 用户在 diff 门否定 node 工具链引入 → 改走「Python 直连 OpenAI 兼容 API + 后端抽象层」形态，pi-agent 降级为未来的可选后端。
- **Cheapest test:** diff 门直接问（架构是 scope 级决策，有明确备选，符合升级条件）。

### K2 —没有可用的 LLM key，P3 的真身闭环无法在本环境验证
- **Claim:** 自然语言调参/解读闭环可交付且可验证。
- **Steelman:** key 可能存在于用户交互式 shell（env 探查受非交互限制）；即使无 key，也可交付「后端抽象 + 录制回放后端」，回放后端用预录 LLM 响应驱动完整闭环并通过测试。
- **Fails if:** 交付物在任何真实环境都跑不起来（key 配置路径不通），或回放后端被误当成真 LLM。
- **Evidence（已取）:** 非交互 shell env 无任何 ANTHROPIC/OPENAI key；deep-research 的 key 来源未确认。
- **Kill criterion:** 配置路径无法实现「env 或本地文件供 key，不入 git」→ 停下来定配置形态。
- **Cheapest test:** 回放后端驱动端到端助手测试；真身联调列为用户侧验收（README 写明）。

### K3 —actions 声明与三工具 API 的真实对齐
- **Claim:** manifest 的 actions（JSON Schema）能真实生成可用的 LLM tool 定义。
- **Steelman:** 三工具 API 是扁平 JSON，tool 定义可机械生成；forecast 已有 demo_used、roi 已有参数默认值，输入结构清晰。
- **Fails if:** 某些自然语言意图需要的参数（如 forecast 的情景结构、coupon 的 scenario 全文）超出「单次工具调用」的整洁边界，actions 变得要么太粗（无用）要么太细（LLM 填不动）。
- **Kill criterion:** 某工具的 action 设计需要改动其 API 行为 → 只加只读/兼容端点，不改行为；仍不行则该工具 actions 留空并记录原因。
- **Cheapest test:** 切片 1 为每工具写 2-3 个 action 的 JSON Schema 草案 + 工具生成器的单元测试（schema 完整性、可序列化）。

### K4 —LLM 调参的写操作安全
- **Claim:** 助手可以替用户调参（写操作）。
- **Steelman:** 本地单机工具、无共享状态、改错可撤销（刷新即恢复默认）。
- **Fails if:** 用户不接受 LLM 直接改参数（误调成本虽低但信任成本高），或写操作无确认门导致「LLM 连环误调」。
- **Kill criterion:** 用户在 diff 门要求只读 → 助手 P3 只保留解读与导航，调参推迟。
- **Cheapest test:** diff 门确认 + 实现时写操作必须经用户确认点击（前端确认门，非 LLM 自律）。

### K5 —助手侧栏与壳的共存
- **Claim:** 右侧助手面板不破坏现有三栏/iframe 布局与工具自治。
- **Steelman:** 壳前端是自有代码，加可开合 aside 不碰工具 iframe；P1 状态栏模式可复用。
- **Fails if:** 助手需要穿透 iframe 感知工具内部状态（如 forecast 当前选中的情景）——跨 iframe 状态桥是 P0 G1 明确推迟的复杂度。
- **Kill criterion:** 助手需要 iframe 内状态才能回答 → 改为「助手操作通过 API 完成并刷新 iframe」，iframe 内状态由工具页自己呈现，助手不感知。
- **Cheapest test:** 助手全部动作走 `/t/{id}/api/`（现有网关），零 iframe 桥接。

## What's Well-Reasoned

- 「先自然语言调参+解读闭环、自主多步延后」的 P0 路线判断——单轮 tool-call 闭环已能覆盖大部分价值，agent 编排是独立深坑。
- actions 从 manifest 生成的设计（P0 预留）意味着 P3 不需要新的工具发现机制。
- 回放后端作为测试基建是诚实做法：这个仓库的测试哲学（黄金值、不变量）与 LLM 不确定性天然冲突，回放让回归可测。

## What I Couldn't Assess

- 用户是否有稳定的 LLM key 来源（只能 diff 门问）。
- pi-agent-core 在助手场景的 token 成本与延迟是否可接受（用量小，预计无感）。

**Verdict: GO** — K1/K2/K4 都是「diff 门一次问清」的决策型假设，有明确备选与推荐；无已满足 kill criterion 的死亡假设。
