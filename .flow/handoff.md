# 交接卡：阶段2 pipeline 收敛（完成于 2026-10-15）

## 已完成

- 提交 `d58e3fc`（main → origin/main）：`target_forecast/pipeline.py` 四件套（scan_inputs / ingest_platforms / run_engine / build_views）；main.py 与 server.py 薄壳化，净删 149 行业务代码
- 行为逐字节等价：固定输入基线 diff（console stdout/stderr、中间指标 CSV、xlsx 8 sheets）零差异；07_参数 sheet 的 target_months 行保留
- 验证：全量 `pytest` 187 passed（含新增 test_pipeline.py 7 条）；真实 xlsx 输入的等价性由基线 diff 证实
- REVIEW：PASS 无 blocking（**降级模式**：子代理因配额 403 不可用，按 dev-flow 规定内联执行，客观证据均独立复跑）

## 开放依赖 / 下一批前置

- 重构方案剩余阶段（未动工）：
  - 阶段3：P1 coupon server 路由表化（route_post 圈复杂度 29/认知 105）
  - 阶段4：P2 coupon engine.simulate 拆分（33/54；只搬移不改算术）
  - 阶段5：P2 其余（spec._check_behavior、exports.export_markdown、assistant service._execute）+ P3 测试 helper 去重
- 阶段1 遗留（`.flow/archive/2026-10-15-stage1-httpkit/review-findings.md`）：
  - S3：deliberate-change #5 的负向测试（构造 NaN 引擎输出 → coupon /api/compare 回 422）仍未补

## 已知事实 / 技术债

- `target_forecast/report.py:77-86` 存在第三份 concat 拷贝（write_report 内部）——阶段2 PRD 决策 5 显式划出范围外，后续如收敛需单独 flow
- `target_forecast/server.py` 的 `import numpy as np` 为存量无用导入（阶段1 前已存在，两阶段均未顺手清理，避免混入 diff）
- demo 生成器种子 `hash(platform)` 跨进程随机（`demo.py:56`）——对比验证必须用固定输入文件，不能跑两次 demo
- 进度打印改为引擎跑完后统一输出（字节流不变，多平台慢数据下"实时感"略有差异，GRILL Q1 已决）

## 过程备注

- 基线快照在 `workspace/baseline-stage2/`（gitignored），保留供后续阶段复用对比方法
- REVIEW 降级为内联执行的根因是子代理配额（403 五小时窗口）；下一批 flow 如配额恢复应回到 fresh-context 子代理
