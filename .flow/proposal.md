# Proposal — 测算工作台整合（统一底座）

来源：2026-09-27 会话讨论稿，用户认可方向后启动 dev-flow（gated）。本文件为后续所有阶段的最高规格源。

## 用户原始需求（逐字要点）

- 现仓库中「目标测算」和「优惠券测算」是两个独立工具，要整合到一个工作台。
- 未来还会有其他测算工具增加（如投放 ROI 测算），**不可能每个测算工具都做一套底座**，要打通成一套底座。
- 未来还要引入 pi agent sdk + LLM，用 LLM 驱动测算工作台。
- 用户确认：「认可这个方向，直接走 dev-flow」——即认可下方整合规划，本 flow 执行其中的 P0。

## 现状（代码事实）

- 两工具技术形态一致：标准库 `http.server` + 无框架静态前端（index.html/app.js/style.css）+ JSON API + CLI；端口 8300 / 8310 各自独立。
- 测算引擎均为不依赖 HTTP 层的纯 Python 模块（target_forecast/engine.py 等、coupon_tool 的 simulate/compare/stress_test 等）。
- 重复部分：HTTP 骨架、静态页服务、端口/启动脚本（两个 .command）、演示播种、模板/导出下载。
- 数据布局不同：目标测算用 `data/` + `output/`；优惠券用 `coupon_data/` + `output/coupon`。
- 存量测试：tests/ 下目标测算 + 优惠券共 98+ 项，全部绿色（VERIFY 基线命令 `.venv/bin/python -m pytest tests -q`）。

## 已确认的整合规划（方向性决策，后续阶段不得推翻）

### 架构目标

```
┌─ 启动测算工作台.command（唯一入口，一个端口 8300）
└─ workbench/                    ← 底座（所有工具共用）
   ├── shell server              标准库 http.server，工具注册表 + 路由分发
   ├── shell frontend            壳页面：左侧工具导航 + 工具挂载区 + 全局状态栏
   ├── shared services           端口回退 / 演示播种 / 模板与导出下载 / 健康检查
   └── tool contract             插件协议
├─ tools/target_forecast/        ← 现有包迁移为插件（引擎不动）
├─ tools/coupon_tool/            ← 同上
└─ tools/roi_tool/               ← 未来新工具：只写引擎 + manifest
```

### 插件协议（Tool Contract）

每个工具一个包，入口暴露描述对象：id（URL 前缀 /api/{tool_id}/...）、name、icon、static 目录、register_routes、seed_demo（可选）、actions（机器可读 action 清单，为 LLM 预留，先空）。壳服务只做：按 id 分发 API、托管 /tools/{tool_id}/ 静态资源、渲染带导航的壳页面。工具前端仍是各自的 index.html/app.js，从整页应用变为壳内页签。

### 为 LLM 驱动的预留（现在只留接口，不实现）

1. 单一 API 网关 = 单一 LLM 工具面：LLM 未来调用的就是前端用的同一套 JSON API。
2. manifest 的 `actions` 字段（JSON Schema）作为未来 function-calling 的 tool 定义来源，P1 先留空占位。
3. 引擎纯函数化已是事实，LLM 编排层可进程内直调引擎。
4. 运行封存与可追溯提升为底座级约定（LLM 测算必须可回放、可审计）。

### 分期路线

- **P0（本 flow）**：抽底座 workbench/（壳服务 + 注册表 + 壳前端 + 统一启动脚本）；两工具迁移为插件（URL 加前缀）；旧 .command 保留为薄壳或替换为单一入口；存量测试全部保持绿色。验收：一个端口、一次双击，两个工具都能用。
- P1：统一数据目录布局、统一导出下载、统一状态栏与设计语言（壳 UI 按全局 DESIGN.md 基线）。
- P2：投放 ROI 测算验证插件协议（新工具不改底座一行代码）。
- P3：引入 pi agent sdk + LLM（助手侧栏、补 actions 声明、先自然语言调参+解读闭环）。

### 风险与取舍（已确认）

- 前端整合深度：壳 + 工具自治前端，不强行合并单页应用；视觉统一靠共享 CSS token。
- URL 变更：旧书签/脚本里的 8300/8310 路由失效，启动脚本做兼容提示；本地工具影响小。
- 不过度设计：底座只做当前两工具真实需要的能力，actions/热加载只留接口不实现。

## 本 flow（P0）范围边界

做：workbench 壳、插件协议、两工具迁移、统一启动入口、测试保持绿色。
不做：P1 数据目录收编（除非迁移必需的最小调整）、ROI 工具、LLM 接入、actions 内容填充、引擎任何改动。

## 开放问题（留给 GRILL/实现期）

- 壳前端形态：iframe 隔离 vs 直接挂载工具 DOM。
- 旧 .command 脚本：保留薄壳转发 vs 直接替换为单一 `启动测算工作台.command`。
- 工具包是否物理移动到 tools/ 目录，还是保持现有顶层包名（target_forecast/、coupon_tool/）仅注册为插件。
- 壳导航与全局状态栏的最小 UI 范围（P0 做到什么程度）。
