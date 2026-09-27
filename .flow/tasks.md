# Tasks — 测算工作台整合 P1

规格源：`.flow/prd.md`（含 GRILL 决议 G1-G8）。验收基线：`.venv/bin/python -m pytest tests -q` 存量断言零修改全绿。

- [ ] 1. 迁移纯函数 workbench/migrate.py
- [ ] 2. 双工具路径收编（forecast + coupon）
- [ ] 3. forecast 导出下载端点
- [ ] 4. 壳状态栏 + 设计语言精修
- [ ] 5. 启动脚本迁移集成 + 仓库卫生 + e2e

---

## 1. 迁移纯函数 workbench/migrate.py

**What to build:** `plan(root) -> 计划`（纯函数：枚举 move 操作与冲突清单，不动文件系统）与 `apply(root) -> 报告`（逐文件移动、冲突跳过不覆盖、搬空旧目录自底向上 rmdir、父目录自动创建）。映射：data/orders→workspace/forecast/orders、data/metrics→workspace/forecast/metrics、output/→workspace/forecast/output、coupon_data/→workspace/coupon（其子目录平移）、output/coupon→workspace/coupon/output。

**Acceptance criteria:**
- [ ] 空仓库（无旧目录）→ 计划为空、apply 无操作
- [ ] 源有数据目标无 → 全部移动，源文件消失、目标出现
- [ ] 目标已有不同内容文件 → 该文件跳过、源保留、报告列出冲突
- [ ] 目标存在源不存在 → 视为已迁移跳过
- [ ] 全部 tmp_path 单测（tests/test_migrate.py），不碰真实数据

**Blocked by:** None - can start immediately

## 2. 双工具路径收编（forecast + coupon）

**What to build:** forecast：WorkbenchState 扫描 root/workspace/forecast/{orders,metrics}；demo.generate、templates 文案、report/main.py OUT_DIR、CLI 提示指向 workspace/forecast/output。coupon：plugin.py 构造 workspace/coupon 与 workspace/coupon/output；server.serve、storage.Store、exports.export_all 默认参数同步。两工具 demo/空数据自动播种逻辑保留并写新路径。

**Acceptance criteria:**
- [ ] 存量 113 项测试零断言修改全绿（允许测试设施指向调整）
- [ ] 壳内 /t/forecast/api/state 与 /t/coupon/api/state 在「workspace 有数据」时正常（本机 e2e 在切片 5 前可用临时目录验证）
- [ ] 独立入口 `main.py serve` / `python -m coupon_tool serve` 默认路径指向 workspace

**Blocked by:** 1（先用 migrate 把测试环境数据就位）

## 3. forecast 导出下载端点

**What to build:** `GET /t/forecast/api/export/report`（workspace/forecast/output/目标测算报告.xlsx）与 `GET /t/forecast/api/export/metrics/{platform}`（中间指标 CSV，路径参数 URL decode）；文件不存在 → 404 JSON 提示先运行 main.py run。coupon 导出端点因切片 2 路径变化回归验证。

**Acceptance criteria:**
- [ ] tmp 环境预置文件：两端点 200 且 Content-Type/内容正确
- [ ] 文件缺失：404 + 提示文案
- [ ] coupon /t/coupon/api/export/{run_id}/{kind} 收编后仍正常（runs 数据在 workspace/coupon）

**Blocked by:** 2

## 4. 壳状态栏 + 设计语言精修

**What to build:** 壳底部状态栏：产品名+版本、当前激活工具、本机运行声明、数据源标记（fetch 当前工具 /t/{id}/api/state，含 demo_used 才显示「演示数据」）；Xanthil token 精修侧栏激活态与内容区底色。

**Acceptance criteria:**
- [ ] 壳页含状态栏结构（测试断言关键节点存在）
- [ ] forecast 工具 demo_used=true 时状态栏出现演示标记（前端逻辑可静态断言 + forecast state 契约测试）
- [ ] 设计语言范围不超出 PRD D7 清单

**Blocked by:** 2（依赖工具 state 契约，实际与 3 并行）

## 5. 启动脚本迁移集成 + 仓库卫生 + e2e

**What to build:** 三个 .command 起服务前执行 `python -m workbench migrate`（有迁移/冲突时输出结果，不阻断启动）；.gitignore 换 workspace/；README 目录结构与数据放置说明更新；真实仓库执行一次迁移（本机）+ 壳服务 e2e 冒烟（两工具 state、forecast 报表下载）。

**Acceptance criteria:**
- [ ] bash -n 三脚本语法通过；迁移集成后脚本可重复执行（幂等）
- [ ] 本机真实数据迁移：data/、coupon_data/、output/ 内容完整落入 workspace/，无冲突报告（或冲突已如实报告）
- [ ] 壳 e2e：/api/state、/t/forecast/api/state、/t/coupon/api/state、/t/forecast/api/export/report 全部正常
- [ ] git status 干净（workspace/ 被忽略，旧目录已清空移除）

**Blocked by:** 2, 3, 4
