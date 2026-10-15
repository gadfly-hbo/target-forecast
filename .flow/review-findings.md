# REVIEW 发现（阶段2，2026-10-15）

> **降级模式声明**：本阶段 REVIEW 因子代理配额限制（403，两次尝试均失败）按 dev-flow 规定降级为**主代理内联执行** matt-code-review 两轴审查，非 fresh-context。独立复跑的客观证据（pytest / 基线 diff）均真实执行，但主观审查的对抗距离弱于标准模式，DONE 摘要中将披露。

## Verdict: **PASS**（无 blocking 发现；3 条 non-blocking）

## VERIFY 证据复核——无不一致

- 复跑 `.venv/bin/python -m pytest -q` → **exit 0, 187 passed in 99.44s**（记录：187 passed in 107.57s；数量与退出码精确一致）
- 复比 `console.before.txt` vs `console.after.txt` → identical；`diff -r 中间指标.before/after` → identical
- xlsx 逐 sheet（00_说明带生成时间掩码）8/8 IDENTICAL，07_参数 44 行含 target_months 行

## Spec 轴

逐项核对 `.flow/prd.md`（含 GRILL 决议）：

- ✅ 四件套签名与返回形状（scan_inputs 无空输入策略 / ingest_platforms 只 ingest / run_engine 保持插入序带 unified / build_views 恰好五键）——`target_forecast/pipeline.py`
- ✅ Q1：on_progress 已删，main.py 壳在 run_engine 后按插入序补打整行；console 基线字节级相同（独立复比证实）
- ✅ caliber 不对称按 PRD 决策 2 保留：main.py:29-30 原地变异（带注释），server.calc 拷贝式；07_参数 sheet 44 行含 target_months（pandas 实读）
- ✅ 空输入分叉留在两壳：main.py:26-27 sys.exit 原位；server.load:53-58 demo 自生成原位；scan_inputs 未吸收任一策略
- ✅ server 公开符号冻结：load_cfg/WorkbenchState/state_payload/calc/route_*/make_handler/serve 签名不变；`import target_forecast.plugin` 通过
- ✅ WorkbenchState.load 仍不做引擎工作（只 scan+ingest；引擎在 calc 懒算）
- ✅ warnings 捕获留在 main() 原位；共用层无 warnings 过滤
- ✅ 测试证据链：test_pipeline.py 7 条全绿（手写最小 xlsx、AST 守卫、空输入分叉自动化）
- ✅ 无范围蔓延：diff 仅 main.py / server.py / pipeline.py（新）/ test_pipeline.py（新）+ .flow 过程文件

## Standards 轴（smell 基线）

- 无新增 Duplicated Code（本阶段目标即消除两份拷贝，已达成；diff -368/+219 净删 149 行）
- 命名清晰、无 Middle Man、无 Speculative Generality

## Non-blocking 发现

| # | 发现 | 分类 | 处置 |
|---|---|---|---|
| S1 | report.py:77-86 的第三份 concat 拷贝仍在（write_report 内部自做）——PRD 决策 5 已显式划出范围外 | non-blocking（已记录的范围界定） | 不处理，留待后续阶段 |
| S2 | 进度打印的墙钟交织变化：原"逐平台边算边打"，新"算完后统一打"——字节流相同（GRILL Q1 已决），仅实时性差异在多平台慢数据下可感知 | non-blocking（PRD 已记录） | 不处理 |
| S3 | `target_forecast/server.py:17` `import numpy as np` 为**存量**无用导入（本 diff 未触碰、阶段1 时已存在） | non-blocking（存量问题，不混入本次 diff） | 留待阶段3+ 顺手或单独清理 |

## 复核准则

- S1：`grep -n "main_parts" target_forecast/report.py` 仍命中——满足（范围外确认）
- S2：console 基线 diff identical——满足
- S3：`git diff target_forecast/server.py` 不含 numpy 行——满足
