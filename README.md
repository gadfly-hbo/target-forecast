# 零售目标测算（线上 · 人货场三视角）

按「人 / 货 / 场」三个维度对线上零售 GMV 做目标测算：**一套测算引擎、两种数据入口、每平台独立核算、顶层全渠道汇总**。

```
[输入层]                     [指标层]                     [测算层]                [输出层]
订单明细(平台A) ─聚合┐                                  ┌→ 平台A测算(人/货) ─┐
订单明细(平台B) ─聚合┼→ 统一月度指标表(每平台一套) ─→  ├→ 平台B测算(人/货) ─┼→ 全渠道汇总
聚合指标(平台C) ─映射┘  月×新老客×品类×梯队            └→ 平台C测算(人/场) ─┘  Excel报表
```

三个视角对同一笔 GMV 负责，互为校验：

| 视角 | 公式 | 主口径条件 |
|---|---|---|
| 人 | GMV = 新客数×新客客单 + 老客数×复购频次×老客客单 | 模式A（订单明细，无UV） |
| 场 | GMV = UV × 转化率 × 客单 | 模式B且填报了UV |
| 货 | GMV = Σ(品类×梯队 × (1+梯队增速)) | 模式A（作为校验视角） |

## 快速开始

**双击 `启动测算工作台.command` 即可**（Finder/终端均可，双端通用）：首次运行自动建虚拟环境装依赖，起本机服务后自动打开浏览器；默认端口 8300，被占用时自动换空闲端口（`PORT=xxxx` 可覆盖），Ctrl+C 退出。工作台左侧导航切换各测算工具。

旧的 `启动目标测算.command` / `启动优惠券测算.command` 仍可用：壳服务已在运行时只打开对应工具页，未运行时启动同一个工作台后直达对应工具。

命令行方式：

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt

.venv/bin/python -m workbench serve  # 启动测算工作台（http://127.0.0.1:8300，左侧导航切工具）
.venv/bin/python main.py demo        # 目标测算：生成演示数据并跑通全流程（先看这个）
.venv/bin/python main.py run         # 目标测算：用 workspace/forecast/ 下的正式数据测算
.venv/bin/python -m coupon_tool demo # 优惠券测算：合成演示场景端到端
.venv/bin/python -m pytest tests -q  # 全部测试（核心不变量 + 工作台冒烟）
```

## 测算工作台底座（workbench/）

两个测算工具跑在同一套底座上：**单一壳服务（单端口）+ 工具注册表 + 导航壳**。壳负责路由分发（`/t/{tool_id}/...` 剥离前缀后交给工具）、静态托管、工具导航；各工具的测算引擎与前端业务逻辑独立自治。新增测算工具（如投放 ROI）只需写一个引擎包 + `plugin.py` manifest（id/name/icon/static_dir/handle_get/handle_post，可选 seed_demo），在 `workbench/server.py` 注册表中登记即可，不改底座。

```
启动测算工作台.command            唯一入口（旧 .command 为兼容直达入口）
workbench/                       底座：壳 server + 注册表 + 导航壳前端
├── server.py                    / 壳页、/api/state 工具清单、/t/{id}/ 前缀分发
├── registry.py                  插件协议（Tool Contract）
└── static/                      壳前端（侧边栏导航 + iframe 装载 + ?tool= 深链）
target_forecast/plugin.py        目标测算插件适配（/t/forecast/）
coupon_tool/plugin.py            优惠券测算插件适配（/t/coupon/）
roi_tool/plugin.py               投放 ROI 测算插件适配（/t/roi/）
```

**新增测算工具三步**（roi_tool 是范例）：① 写引擎包（纯函数，无 IO）+ `server.py`（route_get/route_post 模式，API 全相对路径）+ `static/` 前端；② 写 `plugin.py` 暴露 manifest（id/name/icon/handle_get/handle_post，可选 seed_demo/actions）；③ 在 `workbench/server.py` 的 `build_default_registry` 登记一行。壳的导航、状态栏、深链、前缀分发自动生效，底座其余代码零改动。

### 投放 ROI 测算（roi_tool/）

多投放计划的盈亏测算：单计划按「点击=消耗÷CPC → 订单=点击×CVR → GMV=订单×客单 → 净贡献=GMV×(1−退款)×毛利率−消耗」核算，输出 ROI、保本转化率与净贡献结论（「净亏损」允许成为结论）；保守/基准/挑战三档情景对转化率与客单施加增速，检验结论对假设的敏感度；多计划并排比较、按净贡献排名。**演示计划为合成假设，非行业真值、非经营建议。**

各工具的独立入口（`main.py serve`、`python -m coupon_tool serve`）保留可用，前端 API 全部相对路径，独立运行与壳内运行行为一致。manifest 预留 `actions` 字段（机器可读能力声明），为未来 LLM 驱动（pi agent sdk）接入预留接口。

**数据布局**：所有工具数据收编在 `workspace/{tool_id}/` 下（`workspace/forecast/{orders,metrics,output}`、`workspace/coupon/{scenarios,runs,…,output}`），不入 git。旧版顶层的 `data/`、`coupon_data/`、`output/` 在首次启动时由启动脚本自动无损迁移（`python -m workbench migrate`，幂等；目标已存在且内容不同的文件会跳过并提示，绝不覆盖）。导出下载统一在 `/t/{id}/api/export/...`：目标测算报表与中间指标、优惠券三格式导出均可直接在浏览器下载。

## 测算助手（P3，LLM 驱动）

壳右下「🤖 助手」打开对话侧栏：用自然语言问数（「基准情景净贡献是多少」）或调参（「把挑战情景新客增速调到 25%」）。助手把意图转成对当前工具的 API 调用（tool calling，能力清单来自各插件 manifest 的 `actions` 声明），**修改参数的调用必须经你点击确认才生效**，确认后参数落盘（`workspace/{tool}/assistant_params.json`）并刷新工具页。

**LLM 后端**（自动探测，启动日志明示当前后端）：

1. **pi-agent sidecar**（首选）：`assistant-sidecar/` 用 `@earendil-works/pi-ai` 驱动小米 MIMO（与 deep-research 同栈）；壳在 node 可用且已构建（`cd assistant-sidecar && npm install && npm run build`）时自动拉起 127.0.0.1:8321。
2. **OpenAI 兼容直连**：无 sidecar 但有 key 时由 Python 壳直连。
3. **回放模式**：两者皆无时的兜底，界面明示「回放模式（非真 LLM）」，响应来自预录脚本。

**key 配置**（三选一，自动探测按序）：`workspace/assistant.env` 写 `WORKBENCH_LLM_API_KEY=...`（可选 `BASE_URL`/`MODEL`）→ 复用 ZCode 配置的小米 MIMO provider（`~/.zcode/v2/provider_config.json`，自动读取）→ env 变量。默认模型 `mimo-v2.6-pro`（`https://token-plan-cn.xiaomimimo.com/v1`，实测 chat/completions 可用）。凭证不入 git。

## 本地工作台（main.py serve）

浏览器打开 `http://127.0.0.1:8300`（`--port` 可换端口）。数据与测算全部在本机完成，`workspace/forecast/` 为空时自动生成演示数据。

- **左栏**：全渠道 / 各平台视图切换（标注模式A/B）
- **中央**：情景切换（保守/基准/挑战）、交叉校验横幅（任一视角与主口径差 >5% 会 ⚠）、KPI、月度 GMV 堆叠图（新客/老客）、三视角校验表、商品结构、月度明细
- **右栏 Inspector**：当前情景的人/场/货三组增速参数，改动后防抖自动重算（调参 → 看数 → 校验的核心闭环）；「口径说明」页签常驻各条口径
- **底部状态栏**：数据源、演示/正式标记、最近测算时间、本机运行声明

后端为标准库 `http.server` + JSON API（`/api/state`、`/api/calc`），无新增依赖；前端无框架、无 CDN 依赖，离线可用。

## 两种数据模式

| | 模式A：订单明细 | 模式B：聚合指标 |
|---|---|---|
| 放置目录 | `workspace/forecast/orders/{平台}.xlsx` | `workspace/forecast/metrics/{平台}.xlsx` |
| 必填字段 | 日期、订单号、用户ID、商品ID、实付金额（选填：品类、件数、原价金额） | 月份、新客数、新客客单、老客数、老客复购频次、老客客单（选填：UV、新客订单数、转化率、GMV） |
| 派生能力 | 新老客自动识别、款梯队帕累托划分、品类结构 | GMV由人公式派生；填UV则启用场视角 |
| 主口径 | 人（场公式缺UV，无法从订单内算出） | 场（UV×转化×客单） |

同一平台只能用一种模式（以文件所在目录为准）；不同平台可以混用。模板见 `templates/`，内有示例行和填数说明。

## 口径说明（改代码前先读）

1. **GMV口径**：实付金额之和 = 支付口径净额（应已扣退款）。抖音等高退货平台务必用净额，用下单口径会虚。
2. **新客定义**：下单前 365 天内无购买（滚动口径，`config.yaml` 可调）。用户当月新老身份由当月首单决定。
   明细数据存在**左截断**：数据起点之前的购买不可见，首单一律记新客——所以历史期首月的新客占比会偏高，建议历史期尽量给足（≥24个月）。
3. **款梯队**：单款GMV降序、累计占比 ≤78% 为爆款；末段 ≤20% 为尾部；其余腰部。首次售卖距基期末 ≤90 天记为**新品**，不参与帕累托、单列。梯队按最近 12 个月滚动重划。
4. **复购频次**：老客订单数 ÷ 老客人数（月内口径）。
5. **全渠道汇总**：平台口径加总，用户**跨平台不去重**（打通需 unionid，另立项）。比率类指标用分子分母重算：全渠道客单 = ΣGMV÷Σ订单数，全渠道转化率 = Σ订单数÷ΣUV，不能对平台值求平均。
6. **UV 不在订单里**：流量数据在生意参谋/抖音罗盘。模式A想要场视角，需另给流量数据（改用模式B填法即可）。

## 测算方法

- **基线**：最近 `baseline_months`（默认12）个月——流量型指标（新客数、老客月活、UV）取月均，价值型指标（客单、频次、转化）取加权均值。
- **目标**：基线 × (1+情景增速)；流量型按历史GMV月度季节占比分摊到月（大促形态自动继承），价值型平推。
- **三档情景**：保守/基准/挑战，参数在 `config.yaml`，按人/场/货三组分别调。
- **交叉校验**：任一视角与主口径年化差 >5% 会在报表「04_交叉校验」打 ⚠——说明该组参数假设与其他视角矛盾，需要复核（这正是三视角的价值）。

## 输出（workspace/forecast/output/）

- `目标测算报告.xlsx`：00 说明 / 01 总盘 / 02 客群结构 / 03 商品结构 / 04 交叉校验 / 05 全渠道汇总 / 06 平台年度汇总 / 07 参数
- `中间指标/月度指标_{平台}.csv`：统一指标层的月度明细，供核对口径

## 目录结构

```
target-forecast/
├── config.yaml                  # 口径 + 三档情景参数（改这里调目标）
├── main.py                      # CLI：serve / demo / run / templates
├── target_forecast/
│   ├── schema.py                # 字段定义与统一指标层
│   ├── ingest_detail.py         # 模式A：明细→月度指标 + 货结构
│   ├── ingest_agg.py            # 模式B：聚合指标→月度指标
│   ├── engine.py                # 测算引擎：基线/季节性/三视角/情景
│   ├── aggregate.py             # 全渠道汇总（加总 vs 重算）
│   ├── report.py                # Excel 报表
│   ├── server.py                # 本地工作台：静态页 + JSON API
│   ├── static/                  # 工作台前端（index.html / style.css / app.js）
│   ├── demo.py                  # 演示数据生成（含新品上架模拟）
│   └── templates.py             # 输入模板生成
├── templates/                   # 两种填数模板
├── workspace/forecast/          # orders/（模式A）、metrics/（模式B）
├── tests/                       # test_core.py 核心不变量 + test_server.py 工作台冒烟
└── workspace/forecast/output/   # 报表与中间指标（工作台内可直接下载）
```

---

## 优惠券测算工具（coupon_tool/）

独立的满减券情景测算与比较工具：判断“是否发券、满多少减多少、需要多大转化提升才回本、结论对哪些假设敏感”。与 `target_forecast` 互不依赖；金额口径为**本次券前可用商品金额**，全部指标出自同一分支账本，允许“不发券”成为结论。

**一键启动**：双击仓库根的 `启动优惠券测算.command`（首次运行自动建 venv 装依赖并播种演示场景 → 起本机服务 → 打开浏览器；Ctrl+C 退出；重复双击只聚焦已开实例）。

```bash
.venv/bin/python -m coupon_tool demo      # 合成演示场景端到端（复现方案文档黄金表，产出三格式导出）
.venv/bin/python -m coupon_tool serve     # 本地工作台 http://127.0.0.1:8310（四页签，离线）
.venv/bin/python -m coupon_tool templates # 生成分桶/订单明细 XLSX 导入模板到 templates/
.venv/bin/python -m coupon_tool console --scenario coupon-demo-001   # 测算已保存场景
```

核心库接口：`load_spec / validate_spec / simulate / compare / stress_test / create_review`。要点：

- **四子模型**（命中与核销、凑单与流失、转化响应、统一账本）实现自《优惠券测算工具 v2.0 方案》§4，分支概率合计=1、贡献拆解与 ΔΠ 对平是引擎不变量。
- **黄金案例**：第七节合成场景的 10 行基准表与压力表 6 值作为验收测试（容差 ±1 分）。
- **决策层**：无券候选始终参与；预算为过滤约束（不截断成本）；输出四类结论而非强行推荐冠军。
- **可追溯**：运行封存（输入快照+配置+引擎版本）不可变、可只读重放；导出 Markdown/CSV/JSON 三格式。
- **复盘**：预测 vs 实际 + 偏差七类；参数新版本需人工确认，旧版本永不覆盖。
- 演示参数为合成假设（synthetic_assumptions），非行业真值、非经营建议。

测试：`.venv/bin/python -m pytest tests/test_coupon_*.py -q`（98 项，含 M01–M20 验收）。
