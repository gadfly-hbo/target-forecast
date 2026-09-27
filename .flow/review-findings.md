# Review Findings — 测算工作台 P2（REVIEW round 1）

Fresh-context reviewer verdict: **FAIL（spec 轴）/ PASS（code 轴）**；VERIFY 证据复跑一致（144 passed）；底座接触确认为「注册表一行 + 缺陷修复（含其注释）」，K1 守住。

## BLOCKER（本周期修复）

1. **演示计划集不满足 GRILL G1，且 demo.py 注释与实算相反** — 计划③京东快车 G1 要求「基准边界」，实算 base net=+9088.89；计划④小红书聚光 G1 要求「基准亏、挑战转正」，实算 base net=+8287.5 三档全正。注释「基准情景贴边」「基准亏、挑战转正」为不实陈述；测试只验合法性未守护 G1 行为意图。修复：重调 ③④ 参数使叙述成立 + 测试断言叙述 + 注释与实算一致。

## SUGGESTION（本周期顺手修复——均为 PRD 明文条目或正确性小缺）

2. 引擎缺「跨情景结论稳定性」输出（PRD D2 明示）→ 补 stability 映射 + 前端翻转标记。
3. G4 契约缺「参数默认值」字段 → state_payload 补 param_defaults，前端添加计划改用之。
4. 删除全部计划后结果表残留旧数据且无提示（正确性小缺）→ 修。
5. test_roi_shell_pages 的 "recalc" in js 为字符串存在断言 → 换 fetch("api/calc 调用点检查。

## 待确认（记录）

- 缺陷修复行的注释是否占用「底座一行」配额：按「修复+注释=一个缺陷修复」认定合规。

## REVIEW round 2（2026-09-27）— PASS

Fresh-context reviewer verdict: **PASS**，无阻断。Round-1 blocker 为真修复（实算 ③ base −53.33 贴边、④ base −1027.5/挑战 +5120.4，注释与实算一致）；四项 SUGGESTION 全部落地可验证；底座接触面独立复核 = 恰好注册表一行 + 缺陷修复（含注释）；K3 断言冻结守住。

**遗留 SUGGESTION（记录，不阻断）：**
1. 畸形请求体容器类型（scenarios 非 dict 等）触发 AttributeError → 连接重置而非 422；与 coupon 服务端既定模式同款，前端无路径产生此类请求体。修复方向：catch 元组加 AttributeError。
2. 重名计划的 stability/ranking 以名为键会互相覆盖（G6 允许改出重名）；cosmetic 边界。
