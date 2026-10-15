# 任务清单：重构阶段5（收官批）

> 来源：`.flow/prd.md`（含红队 5 先决 + GRILL 7 决议）。交错提交序（Q7）：gate→refactor 逐区推进。

- [x] 1. — f9e3e1c 31 passed gate(A1)：spec errors 顺序钉死测试（五块 fixture）
- [x] 2. — 50a49ff 65 passed 顺序钉死绿 A1：_check_behavior 连续块拆分（四函数，块①+②合并为 _check_reach_and_churn——REVIEW F1 修正）
- [x] 3. — 8c69422 3 passed gate(A2)：test_exports_seal.py 三形态 sha256
- [x] 4. — 9c3ab2b 封存3/3绿+22 passed A2：export_markdown 段落拆分
- [x] 5. — a2bdd9d+2c9f213 12 passed gate(A3)：assistant 4 分支执行测试
- [x] 6. — 0ff2049 27 passed A3：_execute 两级表驱动
- [x] 7. — 20fe419 62 passed 四文件 C1：tests/_http.py 去重（四文件，含 Q6 两行修正）
- [x] 8. — 8929dc1 16 passed B1：NaN 负向测试（2×10³⁰⁶ 配方）
- [x] 9. — 2f3fc81 指纹前后 19/19+66 passed B2+B3：e_pi_after 删除（指纹前后）+ numpy 删除
- [x] 10. — 图谱：_check_behavior 19/31→1/1 helper≤5/10；export_markdown 15/31→2/2 section≤5/12；_execute 11/15→2/2 executor≤2/2；全量 223 passed in 104.46s 复杂度复查 + 全量回归
