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

## 遗留（non-blocking，已记录）

- N1：多写 run 的 _relay_orchestrated 只透传 staged[0]（单 pending 设计 + PRD 单写范围；多写支持留后续）
- 摘要有损为既有缺口（后续增强：exec_read 响应加 result 原文字段）
- audit.jsonl 为进程内内存 BudgetStore + 文件审计；标准建议的持久预算账本留后续（单用户本地场景下内存版已满足台账意图）
- (c)-resume checkpoint 重放（写确认后免模型调用）为可选增强

## 运维注意

- sidecar 依赖 `~/Dev/Projects/pi-agent-runtime`（file: 链接，机器本地）；无此仓/无 node/dist 的机器自动降级 Echo
- key 在 workspace/assistant.env（来源 ~/.pi/agent/auth.json [xiaomi-token-plan-cn]，gitignored）
- 冒烟教训：`kill %1` 在新 shell 无效——清理服务器用 `lsof -ti :端口 | xargs kill`
