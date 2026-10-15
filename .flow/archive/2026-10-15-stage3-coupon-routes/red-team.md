# Red-Team: 阶段3——coupon_tool server 路由表化

> **降级模式声明**：子代理因配额限制（403，5 小时窗口，两次尝试均失败）不可用，按 dev-flow 规定**内联执行**红队。对抗距离弱于 fresh-context 模式，DONE 摘要将披露；下述行号证据均出自对 `coupon_tool/server.py`（重构后 HEAD 版本）与测试文件的逐行实读。

**verdict 先行：GO（有条件）**。方向正确——重复骨架（3×load_spec+422、3×缺参 422、8 分支 if/elif）真实存在且可机械表化，爆炸半径被 test_coupon_server + characterization 部分钉住。但发现**一处按"handler 签名统一 (app, r, body)"字面实施必然引入行为变化的陷阱**（统一预读 body），**一套按路由不均质的异常/锁语义**（表化时最容易静默抹平的东西），以及**一组现有测试的真实盲区**（其中 /api/import 整条路由零覆盖）。无 kill 准则已触发。

## Top Kill-Assumptions（按 影响 × 可能性 × 测试成本 排序）

**1. "handler 签名统一为 (app, r, body)"——统一预读 body 会改 /api/demo 的可观察行为**
- **Claim:**（提案开放问题 2 的诱惑解）POST 统一签名带 body，暗示 dispatch 层统一 `r.read_body()`。
- **Fails if:** 按字面实施。`/api/demo`（server.py:138-144）**从不读 body**——今天向它 POST 一个畸形 JSON body 会得到 200（demo 正常返回）；统一预读后 `JSONDecodeError⊂ValueError` 落进外层 except（server.py:245-246）→ **422 "请求不合法"**。行为漂移且无测试会抓住（test_coupon_server 只 POST `{}`）。
- **Kill criterion:** 实施中 dispatch 层出现统一 `read_body()` 即停止；body 必须由各 handler 自读。
- **Cheapest test:** 动工前补一条 characterization：POST /api/demo 带 `data=b"not-json"` → 现状 200。

**2. 异常语义按路由不均质——外层双 except 的包裹范围与内层短路交织，是表化最易抹平的隐性契约**
- **Claim:**（提案未提）`load_spec_or_422` 提取一次即可覆盖三处重复。
- **Fails if:** 提取时丢失两个不对称：(a) compare/stress/run 的内层 SpecError catch 回 **422 + "场景不合法：{exc}" 前缀 + return True 短路**（server.py:171-175 等），而**外层** except SpecError 回 **422 + str(exc) 无前缀**（server.py:243-244）——同一 SpecError 从 load_spec 抛 vs 从 compare()/stress_test() 引擎深处抛，**错误文案不同**；统一成一个 helper 后若引擎路径的 SpecError 也带上"场景不合法"前缀，文案漂移。(b) `/api/review` 有自己的内层 catch `(ValueError, FileNotFoundError, SpecError)`（server.py:227-229），FileNotFoundError 在其余路由**不被外层捕获**（会炸穿 handler 无响应），在 review 却回 422——表化若把 FileNotFoundError 统一加进外层，等于给所有路由新增异常吞噬。
- **Kill criterion:** 重构后任一路由的 422 错误文案与现状不同，或原本炸穿连接的异常（如 export 路径的 PermissionError、review 之外的 FileNotFoundError）被新表化层吞成 422——停止。
- **Cheapest test:** characterization 四条：① compare 传不合法场景 → 422 带"场景不合法"前缀；② review 传不存在 run_id → 422 str(exc)（FileNotFoundError 路径）；③ POST /api/runs（不存在的 POST 路由）→ 404；④ GET /api/export/{id}/bogus_kind → 404。

**3. 锁粒度按路由不均质——"统一提取"是提案自己列的诱惑选项，恰是行为变化**
- **Claim:**（提案开放问题 3）"保持每路由现状（最保守）还是统一提取"。
- **Fails if:** 统一提取。现状粒度：demo 只锁 save_spec（141）；run 锁整个封存+导出（199-209）；export **完全不锁**（113-124 直接读文件）；scenario/{id} 只锁 load（93-94）；state 锁 payload 组装（82-90）。统一锁范围=竞态窗口变化（run 的原子性语义被破坏）或死锁风险（嵌套获取）。
- **Kill criterion:** 任一路由的 `with app.lock` 覆盖的语句集合与现状不同——停止。锁块留在各 handler 内原样搬移。
- **Cheapest test:** 代码审查级（diff 中锁块与业务语句的相对位置逐条对齐）；run 路由的原子性有 test_run_records_decision_and_exports 间接钉住。

**4. GET 正则路由与精确路由的匹配顺序、export kind 白名单——表化不能丢失 404 语义**
- **Claim:**（提案开放问题 1）正则路由是否值得表化。
- **Fails if:** 表丢失顺序语义。现状 elif 链顺序即语义：`/api/state`、`/api/review/list`、`/api/runs`、`/api/templates` 为精确匹配；`/api/scenario/([^/]+)`、`/api/run/([^/]+)`、`/api/export/([^/]+)/(markdown|csv_candidates|csv_ledger|json)` 为顺序正则。关键案例：GET `/api/scenario/save` 命中 scenario 正则 → load_spec("save") → 404 {"error": ...}（**有响应体的 404**），而非 make_dispatch_handler 的 404 {"error": "not found"}——两种 404 体不同。export 的 kind 交替组：非法 kind 不匹配任何表项 → False → 404 "not found"（现状相同，server.py:113 只列 4 种 kind）。
- **Kill criterion:** 重构后 GET /api/scenario/save 的响应体从 store 错误信息变为 "not found"（或反之）——停止。
- **Cheapest test:** characterization：GET /api/scenario/nonexistent → 404 且 error 含 SpecError/找不到文案；GET /api/export/x/bogus → 404 "not found"。

**5. 现有测试的真实盲区——"test_coupon_server.py 全覆盖"不成立**
- **Claim:** 提案称"现有 test_coupon_server.py 全覆盖"。
- **Fails if:** 以此为验证依据。实查 8 个测试：**/api/import（分桶+订单两种模式）整条路由零覆盖**；/api/decision 直接 POST（缺 run_id 422 与 happy path）零覆盖；/api/review/list 零覆盖；/api/scenario/{id} 的 404 分支零覆盖；demo 畸形 body 200 怪癖零覆盖（发现 1）；export 非法 kind 零覆盖。test_coupon_ingest.py 覆盖 import 函数本身但不经 HTTP 层。
- **Kill criterion:** 动工前未补齐上述 characterization 即开始改 route_* —— 判验证条款不合格。
- **Cheapest test:** 在 tests/test_coupon_server.py 或 characterization 文件补 ~6 条（每条 <10 行），先对现状跑绿。

## What's Well-Reasoned

- 重复骨架认定属实：3×`load_spec`+SpecError 422（169-175/178-184/192-198）、3×缺参 422（review 215-217、decision 234-236、stress 186-188）、8 分支 if/elif + 10 分支 GET 链，全部实读确认。
- route_get（21/56）同样处理合理：GET 侧重复少（无 load_spec 骨架），收益主要来自分支拆函数，但正则路由需保留顺序匹配表（发现 4）。
- 纯机械重构定位正确：plugin.py 的 handle_get/handle_post 闭包只依赖 route_get/route_post 签名（(app, h, path)），表化不动签名则壳零影响。
- 约束沿用正确：无框架、不动引擎、行为零漂移。

## Verdict

**GO**，以三个开工前条件：

1. **补盲区 characterization 先行**（发现 5 的 6 条 + 发现 1 的 demo 畸形 body 200 + 发现 4 的两种 404 体），先对现状跑绿。
2. **实施纪律写死**：dispatch 层不预读 body；锁块随 handler 原样搬移；外层双 except 的包裹范围保持罩住整个 POST 分发（或逐路由等价包裹），内层短路/前缀/FileNotFoundError 特例逐条保留。
3. **正则 GET 路由用有序匹配表**（精确表 + 顺序正则表两段），不用单一 dict。
