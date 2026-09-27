# Review Findings — 测算工作台整合 P0（REVIEW round 1）

Fresh-context code-reviewer verdict: **PASS**（两轴核查通过，VERIFY 证据独立重跑一致：113 passed）。以下为随附 SUGGESTION 级发现（非阻断，CONVERGE 决议：记录，不在本 flow 行动）。

1. **[tests/test_workbench.py:218-224] 深链 `?tool=` 无测试覆盖** — implementation/verify。app.js 的 `?tool=` 选择逻辑无外部可观察断言；G5 深链是旧脚本转发的依赖，回归风险实际存在。
2. **[workbench/server.py:34-37] `except ImportError: continue` 静默吞插件内部导入错误** — implementation。插件依赖损坏时壳静默缺工具启动，无法区分「包不存在」与「插件坏了」。
3. **[workbench/server.py:108-113] `serve_background` 无调用方** — implementation。测试自建 server，脚本走 CLI；属 PRD 外的预留函数，可删。
4. **[README.md:26-33] CLI 示例块漏了 `main.py templates`** — PRD/task 5。命令本身仍可用，纯文档遗漏。
5. **[启动优惠券测算.command] 旧脚本的 coupon 演示数据播种被移除** — spec(G2)/implementation。空 `coupon_data/` 首启不再自动播种，需在工作台点「加载演示」生成。与旧习惯有行为差异（非回归——PRD D6 要求数据原位不动、G2 未要求播种）。

## 待确认（审查者无法离线验证）

- 壳 CSS 与全局 DESIGN.md 其余 token 未逐条比对（仅验证了底色）。
- iframe 内工具交互（导出下载/弹窗）未做浏览器级验证，仅静态/HTTP 层证据。
