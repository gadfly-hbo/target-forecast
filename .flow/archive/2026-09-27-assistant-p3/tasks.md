# Tasks — 测算工作台整合 P3（LLM 助手）

规格源：`.flow/prd.md`（含 GRILL 决议 G1-G7）。验收基线：`.venv/bin/python -m pytest tests -q` 存量 145 项断言零修改。

- [x] 1. actions 声明 + tools 生成器
- [x] 2. assistant service 编排 + Echo 后端
- [x] 3. 壳端点 /api/assistant/chat + 降级
- [x] 4. 壳前端助手面板
- [x] 5. pi-agent sidecar + 接线 + README + e2e

---

## 1. actions 声明 + tools 生成器

**What to build:** 三插件 manifest 补 `actions`（forecast: get_state/calc/set_scenario_params；coupon: get_state/list_runs/compare；roi: get_state/calc/set_plan_params，JSON Schema 按 PRD D2）；`workbench/assistant/tools.py` 从注册表 actions 生成 OpenAI tools 定义（含 tool_id 命名空间）；fixture 预录放 `workbench/assistant/fixtures/`。

**Acceptance criteria:**
- [x] 每工具 2-3 个 action，schema 必填/类型/枚举合法，可被 json.dumps
- [x] 生成器输出与 manifest 一一对应；写类 action（set_*）带 `"x-write": true` 标记（确认门依据）
- [x] tests/test_assistant_tools.py 覆盖上述 + 存量测试零修改

**Blocked by:** None - can start immediately

## 2. assistant service 编排 + Echo 后端

**What to build:** `workbench/assistant/`：`backend.py`（后端协议 + EchoBackend 回放 + OpenAiCompatBackend stdlib urllib + 自动探测）、`service.py`（一轮闭环：上下文注入（G3 裁剪）→ chat → tool_calls 执行（G7 内部 HTTP 回环）→ 结果回灌；写操作 pending_confirmation 两步协议（G2）；会话内存态（G4））。

**Acceptance criteria:**
- [x] Echo 回放驱动 3 个 fixture 意图端到端：解读类断言数字入回复；调参类断言先 pending 不执行、确认后执行且 summary 含新值；越界类断言拒答说明
- [x] 写操作未确认前工具零副作用（断言）
- [x] 后端不可用 → 结构化 503 文案（含配置指引）
- [x] tests/test_assistant_service.py 全绿

**Blocked by:** 1

## 3. 壳端点 /api/assistant/chat + 降级

**What to build:** workbench/server.py 增加 `POST /api/assistant/chat`（壳层端点，非工具前缀），调 service；serve 时 sidecar 探测与子进程管理（G5）；tests/test_workbench.py 增补 HTTP 冒烟（echo 后端下端到端、503 降级）。

**Acceptance criteria:**
- [x] POST /api/assistant/chat 返回 {reply, tool_calls, pending_confirmation?}
- [x] 无后端可用时 503 + 中文配置指引
- [x] 存量测试零修改；壳其余行为不变

**Blocked by:** 2

## 4. 壳前端助手面板

**What to build:** workbench/static 三文件扩展：右侧可开合助手面板（宽度 ~320px，Xanthil token）、消息列表、输入框、写操作确认卡（G2 两步）、助手动作后刷新 iframe；后端 503 时面板显示配置指引。

**Acceptance criteria:**
- [x] 壳页含助手面板结构（测试断言关键节点）
- [x] 确认卡渲染逻辑可静态断言（pending_confirmation → 确认按钮 → confirm 请求）
- [x] 存量测试零修改

**Blocked by:** 3

## 5. pi-agent sidecar + 接线 + README + e2e

**What to build:** `assistant-sidecar/`（package.json 依赖 @earendil-works/pi-agent-core + pi-ai；chat 端点跑 runAgentLoop，provider 自定义 baseUrl+apiKey 按 D4 解析顺序；参照 deep-research live.ts）；README 助手章节（配置方法、后端降级链、合成响应标注）；e2e 冒烟（node 可用时 sidecar 起、壳探测成功；echo 降级路径）。

**Acceptance criteria:**
- [x] sidecar `npm install && npm run build` 可构建（本机实测）
- [x] 壳启动日志明示当前后端（sidecar/openai/echo）
- [x] README 含 key 配置三路径与 MIMO 实测参数
- [x] e2e：node 可用时 chat 端点经 sidecar 可达（或记录降级原因）

**Blocked by:** 3（与 4 并行）
