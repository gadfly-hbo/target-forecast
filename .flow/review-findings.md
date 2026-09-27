# Review Findings — 测算工作台整合 P1（REVIEW round 1）

Fresh-context code-reviewer verdict: **FAIL**（VERIFY 证据独立复跑一致：125 passed；迁移逻辑无覆盖/丢数据路径）。1 BLOCKER + 5 SUGGESTION。

## BLOCKER（round 1 修复周期处理）

1. **forecast 导出端点无工作台 UI 入口，User Story 5 只交付了一半** — spec/implementation。`target_forecast/static/` 零改动，前端没有任何链接指向 `/api/export/report` 与 `/api/export/metrics/{platform}`；PRD US5「在工作台里直接下载」与 GRILL G5「前端生成链接时 encodeURIComponent」均预设前端入口存在。修复：forecast 工具页加报表 + 各平台 CSV 下载链接（encodeURIComponent），补静态断言测试。

## SUGGESTION（CONVERGE 分类后处置见下）

2. **[coupon_tool/cli.py:40,45] `--out` 默认仍为 `output/coupon`** — 与 D3 收编精神不一致，`python -m coupon_tool demo` 会把产物写回旧布局。→ 分类为 blocking（D3 实现不完整），本轮修复。
3. **[README.md:71] 表格行 4 格渲染断裂 + 残留旧路径** — 本轮修复（self-introduced defect）。
4. **[target_forecast/server.py:210-211] `%2F` 绕过斜杠过滤的路径穿越** — decode 后未校验 `/` 与 `..`。本机低风险，但属 correctness bug。→ 分类为 blocking，本轮修复。
5. **[启动*.command] `set -e` 下 migrate 崩溃导致整个启动脚本中止** — G4 fail-open 意图未覆盖迁移进程异常。→ 分类为 blocking（启动可靠性），本轮修复。
6. **[workbench/migrate.py:62] dst 为目录时 `read_bytes()` 抛 IsADirectoryError 中止整个迁移** — 数据迁移代码的健壮性。→ 分类为 blocking，本轮修复。

## 待确认（记录，不处理）

- `test_forecast_export_report` 依赖真实仓库 `workspace/forecast/output/目标测算报告.xlsx` 存在（用户删除后该测试 404 失败）——接受此耦合：本机工具的 e2e 性质，报表由 `main.py run` 重新生成。
- `workspace/coupon/` 暂无 `output/` 子目录——迁移前 `output/coupon` 本就不存在，导出时由 export_all 建目录，无问题。
- 三脚本未实际执行（bash -n + 逻辑推演通过），浏览器级 e2e 未做。

## REVIEW round 2（2026-09-27）

Fresh-context reviewer verdict: **FAIL** — round-1 六项修复中五项属实，但 #1 为假证据：导出 pane 的 tab 切换漏接（app.js 只切换 params/caliber 两个 pane），exports-pane 永不显示；原静态测试只断言字符串存在，无法捕获。

**Round-2 修复（本周期完成）：**
- app.js tab 处理器补 `$("#exports-pane").hidden = ...` 一行（真修复）
- 静态测试升级为对应性校验：index.html 每个 `data-pane` 值必须在 app.js 切换逻辑中出现
- SUGGESTION 顺手修：reload toast 旧路径文案「data/」→「workspace/forecast/」；导出 metrics 正则容忍 query string（`([^/?]+)(\?.*)?`）
- 记录不处理：migrate 对悬空符号链接的边界（行为安全、未测）；浏览器级 e2e 未做（静态已确证）

VERIFY 复跑：128 passed, exit 0。

## REVIEW round 3（2026-09-27）— PASS

Fresh-context reviewer verdict: **PASS**，无阻断项。Round-1 六项 + Round-2 tab 切换修复全部属实有效；spec 轴（US1-10、D1-D7、G1-G8）逐条覆盖。

**遗留 SUGGESTION（记录，不阻断）：**
1. `test_forecast_export_ui_entry` 的对应性校验仍是字符串存在断言——删掉 app.js 切换行的回归不会被捕获。建议改为捕获组集合比对（`hidden = btn.dataset.pane !== "([^"]+)"` 的集合 == data-pane 集合）。防 round-1/2 假证据模式复发。
2. 中间指标链接缺文件时浏览器原地展示 JSON 404（可选 UX 加固：fetch + toast）。

VERIFY 复跑：128 passed, exit 0。
