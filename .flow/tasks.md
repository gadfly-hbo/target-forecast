# Tasks：优惠券测算工具 P0 拆解（tracer-bullet 纵切片）

- [x] 1. S1 引擎核心纵切：ScenarioSpec → simulate() → 黄金案例复现
- [x] 2. S2 候选比较、约束过滤与四类结论 + 盈亏平衡：compare()
- [x] 3. S3 敏感性与压力情景：stress_test()
- [x] 4. S4 数据导入与质量检查：手工分桶/CSV/XLSX → DataSnapshot
- [x] 5. S5 存储快照、运行封存与三格式导出
- [x] 6. S6 CLI 入口与合成演示场景
- [x] 7. S7 本地工作台 UI（单页四页签 + JSON API）
- [x] 8. S8 复盘闭环与参数版本

> 依赖：1→2→3；1→4；5 依赖 1-4；6→7→8 串行。执行按编号顺序。
> 规格溯源：每片验收标准对应 `.flow/prd.md` 用户故事编号与提案 M01–M20 验收条目。

---

## S1 引擎核心纵切：ScenarioSpec → simulate() → 黄金案例复现

### What to build
从结构化场景输入到单候选模拟结果的完整纵切：领域对象（ScenarioSpec：baseline/candidates/cost/behavior，金额整数分）+ 基础 validate（0<F<T、权重守恒、概率合法、非整数分阻断）+ 四子模型引擎（4.2 命中核销分支、4.3 凑单流失五分支、4.4 转化响应与新增分布 vⱼ、4.5 统一账本）+ 4.6 贡献拆解对平。simulate() 返回 metrics/ledger/validation/limitations 四段。内置合成案例场景常量（第七节参数）。

### Acceptance criteria
- [ ] 黄金基准表（无券 + 9 个券方案）的转化率/商家券补/总贡献/增量贡献全部复现，容差 ±1 分、转化率 ±0.0001
- [ ] M01 无券候选与完整基准一致 ΔΠ=0；M03 核销率 0 不扣券补；M04 分支概率合计=1；M05 vⱼ 合计=1 且新增收益不乘基准命中率；M06 账本订单/N=展示转化率∈[0,1]；M07 全自然达标时贡献变化=−商家券补；M02 触达全 0 回基准；M08 平台承担不误扣商家；M13 C₀=0 限制可见；M14 非法候选阻断
- [ ] 4.6 拆解与 ΔΠ 对平（引擎不变量测试）

### Blocked by
None - can start immediately

**Stories**: 5(基准设置), 25, 26

---

## S2 候选比较、约束过滤与四类结论 + 盈亏平衡：compare()

### What to build
候选生成（P40/P50/P60/P70/P75 加权分位数锚定 + F/T 档位 + 人工增补 + 无券候选，合并去重，超历史范围标 extrapolated）+ 约束过滤（预算对 B_m、ΔΠ 底线/受控亏损、转化/GMV 目标、单均贡献底线、净增量 ROI B_m=0→不适用、合法性阻断，被过滤者留原因不消失）+ 四类结论判定 + 邻近方案展示 + 三种业务模式（毛利/转化/均衡帕累托+Score）+ 盈亏平衡（ΔC⁺_BE/C_BE/ΔC_BE、可触达上限检查、预算重算、π̄_new≤0 提示）。

### Acceptance criteria
- [ ] 预算 10,000 元示例：满159减10 被过滤（附原因）、满159减5 可行——通过测试
- [ ] M09 加购毛利下调贡献不反向提高；M10 无自然命中仍算加购；M11 全零行为回基准；M12 ROI 不适用；M18 超预算标不可行不截断成本；M19 全不可行时返回无可行券且展示无券
- [ ] 四类结论与邻近方案在 ComparisonResult 结构中可见

### Blocked by
S1

**Stories**: 6, 7, 10, 11, 16, 18, 19

---

## S3 敏感性与压力情景：stress_test()

### What to build
stress_test(spec, variants)：单因素变化 + 命名联合情景（保守/基准/积极）；输出各情景 ΔΠ、预算是否超限、排序是否变化、所选方案是否仍可行、主要敏感参数；变化范围由用户指定（无内置 ±20%）。变体格式与黄金压力表对应（k、q_cap、d、m_addon、r、ρ 六类参数）。

### Acceptance criteria
- [ ] 黄金压力表 6 值（低响应/高响应/低凑单高流失 × 两券方案）复现，容差 ±1 分
- [ ] 排序变化与最敏感参数正确输出（用压力表构造排序反转场景断言）
- [ ] 情景变体不修改原 spec（不可变输入）

### Blocked by
S2

**Stories**: 17

---

## S4 数据导入与质量检查：手工分桶/CSV/XLSX → DataSnapshot

### What to build
DataSnapshot 构建：手工分桶（JSON/表格）、CSV、标准 XLSX（openpyxl，分桶与订单明细两种模板，模板生成到 templates/）；字段映射与口径确认（观察单位/窗口/金额口径）；质量检查按提案 3.5 清单输出 error/warning（空值、重复订单、A≤0、非法概率、权重不守恒、货币单位、成本重复扣减、退款未说明、窗口不一致、券后金额误用提示）；明细聚合为 Aᵢwᵢ；缺 N 降级为每观察单位结果。

### Acceptance criteria
- [ ] M15 门槛穿过粗桶：对该候选输出 warning + limitations 标注，不伪造精确命中率
- [ ] M16 已含履约的贡献率又填履约费被拦截提示
- [ ] 模板生成 → 填数 → 导入 → 快照权重守恒往返成功；CSV 与 XLSX 双格式
- [ ] 缺 N 场景：结果仅每单位口径并明示限制

### Blocked by
S1

**Stories**: 1, 2, 3, 4

---

## S5 存储快照、运行封存与三格式导出

### What to build
coupon_data/ 目录（profiles 参数档案带版本与来源类型 / scenarios / runs / reviews / decisions）；运行封存（输入快照+完整配置+参数档案版本+ENGINE_VERSION+候选集+时间+结果+校验，run_id=时间戳+内容摘要，改输入新运行不覆盖）；导出到 output/coupon/：Markdown 决策摘要（8.3 决策卡模板）、CSV（候选表+分支账本，金额分列）、JSON（完整运行记录）；同输入重跑逐位一致。

### Acceptance criteria
- [ ] M17 同一损失只计一次（退货调整账本断言）；M20 同输入同版本重跑结果确定一致、导出与结果数值一致
- [ ] 导出 CSV 可再解析、JSON 可重放（重载运行记录得到相同 metrics）
- [ ] Markdown 决策摘要含场景版本/引擎版本/运行 ID/证据状态/回本条件/最敏感假设

### Blocked by
S1, S2, S3, S4

**Stories**: 21, 22, 25

---

## S6 CLI 入口与合成演示场景

### What to build
`python -m coupon_tool`：demo（内置第七节合成场景端到端：校验→比较→敏感性→封存运行→导出三格式，evidence_status=synthetic_assumptions 全程标注）、console（从 coupon_data/ 加载指定场景测算导出）、serve（占位转 S7）。不改动 main.py 与 target_forecast。

### Acceptance criteria
- [ ] 一条命令 demo 产出全部导出文件且关键数值与黄金表一致
- [ ] console 对保存场景完成测算并封存新运行
- [ ] 全程离线、无新增第三方依赖（openpyxl 已有）

### Blocked by
S5

**Stories**: 12, 25, 26

---

## S7 本地工作台 UI（单页四页签 + JSON API）

### What to build
server.py（stdlib http.server，端口 8310 可改）+ JSON API（state/validate/import/compare/stress/runs/export/decision）+ 无框架静态前端四页签：数据与基准（导入/映射/口径确认/问题清单）、场景与参数（候选集/预算/行为参数+来源标签）、比较与决策（候选表固定列 8.2/贡献拆解/盈亏平衡/敏感性切换/邻近方案与过滤原因/决策卡填写与保存）、历史与复盘（运行列表与详情壳）。视觉遵循 ~/.zcode/design/DESIGN.md（Xanthil 暖灰青基线）。"先设置参数再给出结果"。

### Acceptance criteria
- [ ] API 冒烟测试（仿 test_server.py）：加载演示场景→compare→stress→保存决策→导出，全链 200 且数值与库接口一致
- [ ] 候选结果表含 8.2 全部固定列；被过滤候选可见且附原因；参数来源标签全程可见
- [ ] 不出现未设置关键参数即出结果的路径

### Blocked by
S6

**Stories**: 3, 4, 6-11, 13-20（界面侧）, 27

---

## S8 复盘闭环与参数版本

### What to build
create_review(run_id, actuals, notes)：actuals 导入（JSON/CSV：orders/gmv_pre/gmv_paid/商家券补/核销数/窗口）→ 预测 vs 实际对比 → 偏差七类记录（流量/基准转化/客单结构/触达核销/加购流失/成本结算/未识别剩余）→ 口径核查提示；参数新版本创建（人工确认、旧版本不可变）；历史页签复盘区与参数版本变化视图。

### Acceptance criteria
- [ ] 13.2 产品验收路径完整闭合：导入实绩→复盘记录→参数新版本，原运行与旧参数版本不被覆盖
- [ ] 门禁 D：预测/实际差异可记录，参数更新有人工确认字段，描述性结果与因果结论在界面分开表述
- [ ] 复盘记录进入运行历史可追溯

### Blocked by
S7

**Stories**: 23, 24
