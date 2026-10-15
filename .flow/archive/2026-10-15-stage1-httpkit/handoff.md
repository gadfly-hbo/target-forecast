# 交接卡：阶段1 httpkit 收敛（完成于 2026-10-15）

## 已完成

- 提交 `5ed0651`（main → origin/main）：`tools_common/httpkit.py` 单一事实源；coupon/roi/forecast 三工具 server 全量切换；壳仅替换响应调用点
- 验证：`.venv/bin/python -m pytest -q` → 180 passed；`main.py demo` 与 `python -m workbench serve` 真端口冒烟通过
- 行为变化以 deliberate-change 清单（6 条，见 .flow/prd.md 与提交信息）为准

## 开放依赖 / 下一批前置

- 重构方案剩余阶段（原方案，未动工）：
  - 阶段2：P0 target_forecast pipeline 收敛（`main.py` 与 `target_forecast/server.py` 的汇总/scan/load_cfg 双份）
  - 阶段3：P1 coupon server 路由表化（route_post 圈复杂度 29/认知 105）
  - 阶段4：P2 coupon engine.simulate 拆分（33/54；只搬移不改算术）
  - 阶段5：P2 其余（spec._check_behavior、exports.export_markdown、assistant service._execute）+ P3 测试 helper 去重
- REVIEW 遗留（non-blocking，见 .flow/review-findings.md）：
  - S3：补 deliberate-change #5 的负向测试（构造 NaN 引擎输出 → coupon /api/compare 回 422）
  - S2：`Responder.read_body` strict 行为已接受（与 coupon/roi 原版一致），如未来出现带长度空体客户端再加 `or b"{}"` 兜底

## 已知半死代码

- `roi_tool/server.py serve()` 无 CLI 调用方（已在 docstring 标注"半保留"）；删除与否留给 roi 独立入口需求出现时决定

## 过程备注

- GRILL Q7 原定一 PR 六提交，实际单次提交（中间绿态无法诚实重建，已在 review-findings.md 记录偏差）
- 上一轮 flow（assistant P3）产物在 `.flow/archive/2026-09-27-assistant-p3/`
