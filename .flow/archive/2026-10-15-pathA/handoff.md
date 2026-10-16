# 交接卡：Path A 助手全托管迁移 pi-agent-runtime（完成于 2026-10-15）

## 已完成

- 五提交（c6f2985→72268b1→c48dd42→64ba6dc→8ffb1c7，均推 origin/main）：
  1. 前置：WORKBENCH_SHELL_URL/ROOT 传递 + exec_read/stage 端点（名门禁）+ ChatResult.orchestrated
  2. 核心：sidecar 全量重写于 pi-agent-runtime@0.4.3（file: 链接），产品代码零 pi-ai import（标准规则 1 合规）
  3. 收尾：taskId 按工具集派生（config hash 含工具定义）+ 冒烟修复
  4. REVIEW B1 修复：PiSidecarBackend 解析 orchestrated（真实路径双登记真 bug）
  5. 文档与审查记录
- 架构：runAgent 托管工具循环；读工具代理 /exec_read（复用 Python 中文摘要，行为等价）；写工具代理 /stage 仅登记——真实写效果永不发生在 run 内，Python 用户确认后执行（P3：浏览器确认即授权）；护栏=共享内存 BudgetStore+稳定 taskId+uncapped 五元组+140s run signal+串行队列+audit JSONL（启动 5MiB 轮转）
- 验证：pytest 234 passed；node --test 6/6；**真实 MIMO 有界冒烟全链路**（读问多工具循环+摘要回流；写提案→stage→pending 重建→确认→执行→落盘；audit 48 事件；确认门语义零弱化）
- 前端 app.js 零改动；Echo 回放链零改动

## 遗留状态（b8f28f4 已修前三项）

- ~~N1 多写只透传首个~~ **已修**：透传首个 + 其余取消 + 如实告知（pytest 钉住）
- ~~摘要有损~~ **已修**：exec_read 返回 {summary, result}，真实冒烟验证模型可列出计划名明细
- ~~持久预算账本~~ **已修**：budget-store.ts（内存版语义对齐 + JSON 原子写跨重启累计，node 测试验证）
- **(c)-resume 暂缓**（决策记录）：需 createSessionRuntime 0.4.0 重契约（storage/acquireWriter/reconcile）+ 写效果移入 run 内（TS 移植 Python 写舞步）+ 确认即恢复协议——属另一场架构迁移而非增强；当前确认路径的单次模型调用是描述效果结果的语义需要。要做的开 /dev-flow

## 运维注意

- sidecar 依赖 `~/Dev/Projects/pi-agent-runtime`（file: 链接，机器本地）；无此仓/无 node/dist 的机器自动降级 Echo
- key 在 workspace/assistant.env（来源 ~/.pi/agent/auth.json [xiaomi-token-plan-cn]，gitignored）
- 冒烟教训：`kill %1` 在新 shell 无效——清理服务器用 `lsof -ti :端口 | xargs kill`
