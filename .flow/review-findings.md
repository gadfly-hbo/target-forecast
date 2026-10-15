# REVIEW 发现（阶段3，2026-10-15）

> **降级模式声明**：子代理配额（403）在本阶段全程未恢复（红队、GRILL 第1轮、REVIEW 三处均降级内联）。REVIEW 由主代理按 matt-code-review 两轴内联执行：独立复跑验证命令、逐点对照 `git show cc3d40a:coupon_tool/server.py` 的旧 if/elif 链与新表实现。对抗距离弱于 fresh-context，DONE 摘要披露。

## Verdict: **PASS**（无 blocking 发现；2 条 non-blocking）

## VERIFY 证据复核——无不一致

复跑 `.venv/bin/python -m pytest -q` → **exit 0, 195 passed in 101.13s**（记录：195 passed in 102.40s；数量与退出码一致）。

## Spec 轴（逐点对照旧实现）

| 等价点 | 旧实现 | 新实现 | 结论 |
|---|---|---|---|
| compare/stress/run 内层 SpecError | 422 + "场景不合法：" 前缀 + return True 短路 | `_load_spec_or_422`（server.py:76-81）返回 None，handler early-return | ✅ 仅这三路由使用 |
| scenario/save 的 load_spec | 无内层 catch → 外层 422 str(exc) 无前缀 | `_h_scenario_save` 直调 load_spec，注释标明走外层 | ✅ 未误用助手 |
| 外层异常包裹 | 双 except 罩全部分支 | `route_post` 查表后 try 罩 `handler(app, r)`，双 except 原文 | ✅ |
| review 内层三异常 | (ValueError, FileNotFoundError, SpecError)→422 | `_h_review` 内层保留（server.py:290） | ✅ FileNotFoundError 不进外层 |
| 锁粒度 | demo 锁 save_spec；run 锁封存+导出整块；export 无锁；scenario/{id} 锁 load | 逐 handler 原样（grep 抽查 10 处 with app.lock 位置一致） | ✅ |
| body 读取 | demo 不读 body | dispatch 仅 `POST_ROUTES.get(path)`，各 handler 自读 | ✅（characterization 1 钉住 200） |
| GET 两段匹配 | elif 链：精确在前、正则按序 | GET_EXACT 先查、GET_PATTERNS 顺序 fullmatch | ✅（characterization 6/7 钉住两种 404 体） |
| 公开面 | route_get/route_post (app,h,path)->bool；make_handler/plugin/serve | 签名不变、后三者零改动 | ✅（import plugin ok） |
| 响应体字段 | dict 字面量 | 逐字搬移 | ✅（15 条 server 测试 + workbench 分发测试） |

复杂度目标达成（任务 4 证据）：route_post 29/105 → **4/6**，route_get 21/56 → **4/7**，26 个函数最大 _h_review 4/6——远优于 ≤15 目标。

## Standards 轴

- 表驱动分发符合仓库既有风格（阶段1 的 make_dispatch_handler 同构）；无新框架依赖。
- 新增 characterization 均断言外部可观察行为（状态码/响应体文案），无实现复述。

## Non-blocking 发现

| # | 发现 | 分类 | 处置 |
|---|---|---|---|
| S1 | "缺少 run_id" 422 在 _h_review 与 _h_decision 各出现一次（2 处，锁环境不同）——可再提取 `_require_run_id`，但仅 2 处且语义带各自锁边界，提取收益边际 | non-blocking（judgement call） | 不处理 |
| S2 | `handler(app, r, m) if m is not None else handler(app, r)` 表达式式分支略密；可统一 GET handler 签名为 `(app, r, m=None)` 消除 | non-blocking（judgement call） | 不处理——统一签名会把 m=None 渗进 7 个精确 handler |

## 复核准则

- S1：`grep -c "缺少 run_id" coupon_tool/server.py` == 2——满足
- S2：route_get 内该行存在——满足（记录）
