# target-forecast 作为固定插件接入 JuanerAI · 启动文档（转交 Mac mini）

| 项 | 内容 |
|---|---|
| 性质 | 任务转交文档 + 供应侧事实表（对齐输入，非规格；权威标准在 JuanerAI 宿主仓） |
| 来源 | 用户 2026-10-19 指令：经 MacBook 侧接入前核查后转交 Mac mini 执行 |
| 流程归属 | **Mini-led Plugin Integration**（`docs/governance/product-change-execution-policy.md`）：Mini 主导 plugin/host 研究、集成方案、产品输入准备与获准工程交付 |
| 固定身份 | 仓库 `https://github.com/gadfly-hbo/target-forecast.git`，origin/main @ `df5acd6`（本任务文档所在提交之前的业务基线，含经营目标测算 v2 正式实现，8321756..df5acd6 六提交） |
| 授权边界 | 研究/规划权限**不授权**安装、实施、Provider 调用或外部效果；每一步越权项须标注「未授权/未执行」 |

---

## 0. 必读（先读再动；缺入口则停止并如实报告，不得臆造宿主合同、不得声称符合）

1. JuanerAI 仓 **main** `docs/engineering/plugin-integration/` 三件套：
   `README.md` → `standard.md`（§3 八信息项 / §5 五步接入 / §6 固定交付）→
   `report-studio-reference-adapter.md`（参考链路）→ `acceptance-checklist.md`（C01–C12）。
   注意：标准 2026-10-17 经 PR #93/#94 发布，本机旧工作树可能没有，以 main 为准。
2. `docs/governance/product-change-execution-policy.md`：「Mini-led Plugin Integration」
   +「Product Input and Engineering Intake」。
3. 供应侧先例（同形态产品 2026-10-19 发起接入，信息项表/缺口披露格式可直接借鉴）：
   `/Users/huangbo/Dev/Projects/metric-factory/docs/juanerai-integration-kickoff-2026-10-19.md`。

## 1. 接入形态与对象

- **形态** = 整个产品作为固定插件随 JuanerAI 打包交付（参照 Report Studio 链路）：同机自有
  进程跑 127.0.0.1 HTTP 服务；宿主 Adapter 装配 child 进程 + IPC ready/HTTP 握手 +
  owner token + loopback/origin 守卫；业务实现在原仓维护、独立可运行。
- **对象仓库**：`https://github.com/gadfly-hbo/target-forecast.git`
- **产品构成**：workbench 壳（单端口 + 工具注册表 + 导航）+ 三工具（目标测算 forecast v2
  整页工作区、优惠券 coupon、投放 ROI roi）+ assistant-sidecar（可选 AI，pi 全托管）。
- **范围待用户裁决**（研究阶段出对比后提请用户决定，不先行实施）：
  - A) 整工作台随包（推荐——三工具共享壳/运行时/存储布局）；
  - B) 仅目标测算（产品输入收窄为单工具装配，coupon/ROI 不随包、原仓不动）。

## 2. 供应侧已核查事实（MacBook 2026-10-19 逐项实读复核；即 standard §3 信息项素材）

- **用途与入口**：经营目标测算五步闭环（目标 → 数据 → 假设 → 计算比较 → 保存运行 → 导出）；
  入口 `python -m workbench serve`（壳 :8300）与 `main.py serve`（目标测算 standalone）；
  bind 127.0.0.1（`tools_common/httpkit.py`）。用户任务与成果语义归宿主。
- **运行依赖**：Python 3.9 + pandas/openpyxl（`requirements.txt`）；assistant-sidecar Node，
  pi-agent-runtime 依赖（现状为 `file:` 符号链接，见 §3 缺口 2b）。
- **调用/输入/输出**：输入为用户 xlsx（订单明细模式A / 平台月度指标模式B，两阶段导入 +
  质量三级）；输出为方案版本 + 运行快照 + Excel/CSV/JSON 导出（绑定运行身份，含【运行身份】
  块）。不传业务数据库；原始订单不进 LLM 上下文。
- **权限/效果/外发**：无外发写入；AI 仅提案 dry-run（提案双轨，采纳是用户显式动作）；
  LLM 调用为唯一外部效果（MIMO 端点），须按宿主合同显式建立，**不因随包自动继承独立版**。
- **状态与停止**：计算 job 三态（cancelled/failed/unknown 与 done 分开）、不写半结果、
  内容键过期拦截（保存 409 stale）、重复保存幂等去重。
- **数据与历史**：`workspace/forecast/v2/` 原子写（tmp+os.replace）、corrupt 隔离、
  running→unknown 恢复、旧运行不改绑；`workspace/` 不入 git。
- **兼容/更新/回滚**：`ENGINE_VERSION=forecast-engine-1.1` 随运行记录；内容键幂等；旧接口已
  退役（`/api/state|/api/calc|/api/assistant_params` → 404 code=retired）；旧 CLI 冻结 legacy。
- **验证基线**（提交态实测）：pytest **309 passed** + sidecar `node --test` **13 passed**；
  A01–A15 业务验收映射 `.flow/acceptance-map.md`；UI 合同 `.flow/ui-contract.md`（用户批准
  钉入，基线副本 `.flow/ui/`）；浏览器验收物在 `workspace/forecast/acceptance-smoke/`
  （gitignore，本机取证）。另 `.flow/compat-walkthrough.md`、`.flow/engine-diffmap/`。

## 3. 已知缺口与对齐项（checklist 五档口径：未授权/未执行不得写 N/A 或 PASS）

1. **就绪/停止协议缺失**：无 `/health` 就绪端点、无 IPC ready/owner token。按参考 Adapter
   由宿主装配；供应侧配合暴露最小钩子（如 `/api/health`），属中立修复回原仓。
2. **凭据发现冲突**（首要对齐项，同 metric-factory kickoff §4.1）：
   `workbench/assistant/runtime.py` 的 `resolve_llm_config` 三级发现含 `~/.zcode/v2/`
   文件夹自动发现。集成形态必须禁用文件夹发现，凭据走宿主批准通道（env/secret 显式注入）；
   改动属中立修复回原仓。
3. **pi-agent-runtime 钉版**（用户裁决：**归本任务处置**，MacBook 不先行修）：
   - 事实：pi-agent-runtime **已接入 JuanerAI**——主仓 vendor `0.5.1`（tgz 文件名含
     SHA-256）+ `adapters/agent-pi/` 装配 + standard.md 明文「使用LLM → 经已有共享
     pi-agent-runtime……固定实际SDK」。版本并存是允许的（「不统一不同任务的SDK或物理账本」）：
     metric-factory 钉 `0.4.3`、JuanerAI 主仓钉 `0.5.1`、Report Studio 内嵌 `0.4.1`。
   - 缺口：target-forecast assistant-sidecar 现为 `file:../../pi-agent-runtime` **符号链接
     浮动**，不符合「固定实际 SDK」。实证：2026-10-19 当日运行时 main 由 `0.5.3-harness.3`
     推进到 `0.5.3-simplification.2`，target-forecast 未改代码即换了 SDK（`/health` 动态
     报版可读回；13 项 sidecar 测试对 simplification.2 实测通过）。
   - 处置：① 集成物料按宿主模式钉版（vendor tgz + SHA-256 文件名 + `file:` pin，参照
     JuanerAI 主仓 `package.json` 的 0.5.1 写法），版本基线由集成任务裁决并记录理由
     （候选：`0.5.3-harness.3` 验证基线 / `0.5.3-simplification.2` 当前 main 实测 /
     `0.5.1` 与宿主主仓对齐）；② 八信息项表「固定来源与物料」记录 runtime 精确版本、
     来源 commit/tgz SHA、兼容声明（未知版本 fail-closed）；③ C01 正例 = `/health` 读回
     版本与钉版一致，负例 = 版本不符/缺失拒绝启动。
4. **接入物料待产出**（本任务首要交付）：按 standard §3 补齐八信息项表（可直接套用
   metric-factory kickoff §3 自填表格式）+ C01–C12 适用性/正负例/证据映射。建议适用项参照
   metric-factory：C01 固定身份/兼容、C02 双交付、C03 生命周期、C05 秘密/数据归属（含
   zcode 发现负例）、C07 状态/取消、C08 产物与来源、C09 持久/恢复、C10 LLM、C11 业务
   正确性、C12 更新/回滚。
5. **真实模型质量 = 未授权未执行**（无付费模型授权）：AI 链路证据为契约测试 + 真实 HTTP
   回环（stage→confirm→apply→draft 落盘）；C10 用合成 transport 契约，真实 Provider 调用
   需另行用户授权。
6. **kill -9 中途写入实测、多标签并发实测未做**（C06/C09 相关证据为结构性保证+测试）。
7. **证据时效说明**：`.flow/acceptance-map.md` 记录的 pi 版本 `0.5.3-harness.3` 是当时
   事实，现已被 symlink 漂移超出（见缺口 3）；引用验证基线时以本节事实为准。

## 4. 治理与流程（按序执行；PASS ≠ 用户批准）

1. **盘点/对齐研究**（不授权安装实施）：plugin/host 兼容性研究 → 集成方案 + 八信息项表 +
   C01–C12 映射 + 范围 A/B 对比。
2. **Product Input Package**（模板 `docs/templates/PRODUCT_CHANGE_AUTHORITY_PACKAGE.template.md`）：
   用户路径、范围/非目标、UI Contract（以 `target-forecast/.flow/ui-contract.md` 为基准；
   说明：已批准 demo 已转为正式 UI 实现（替换表见 ui-contract.md），新增可见行为仍需
   用户 UI Gate）、插件/宿主职责、版本/数据/权限/生命周期边界、验收与已知缺口；绑定
   Blueprint v4.2（`docs/planning/2026-10-04/juanerai-product-development-blueprint-v4.2.md`）
   与 target-forecast 固定提交（精确 SHA 随附）。
3. **Product Plan Development-Readiness Gate**（新鲜只读复审，作者不自审）。
4. 用户批准 → 冻结 Product Input → **Engineering Intake** → SDD/TDD（RED→GREEN）→
   受影响回归 → 独立 Validator → Engineering Acceptance → 用户 Product Acceptance →
   PR/CI/squash。
5. **能力登记**：`docs/planning/capability-coverage/register.md`，「方案/代码/接通/验收」
   分开记。
6. **固定交付纪律**（standard §6）：不追随 latest、不覆盖旧包、活动/UNKNOWN 任务不热换；
   每次升级做最小差异表；构建/封装/安装/运行采用分别证明，不以清单存在标通过。

## 5. 非目标

- 不做 SAP/语义资产交换（metric-factory 独立线，本次接入 ≠ 资产消费）
- 不做 MCP 形态；不做通用插件平台/公共抽包/第二插件（standard §7 排除项）
- 不改共享 pi-agent-runtime 本体与 metric-factory/JuanerAI 其他仓（如需变更另立任务；
  §3 缺口 3 的钉版是对本仓依赖的固定，不改 runtime 仓）
- coupon/ROI 若不在范围：不迁移、不删除，原仓保持独立可运行

## 6. 回执要求

- 每步完成条件与证据按 standard §5 记入既有 OpenSpec/验证/交接章节，不新增状态台账
- 结果口径五档：N/A（须说明原因）/ 未授权未执行 / 旧证据复用 / 新 PASS-FAIL / 用户接受未实测
- 供应侧事实如有出入（版本、依赖、行为），以 target-forecast 仓固定提交实读为准并回执差异
