# 提案（讨论稿）：OverflowError 空洞修复

> 来源：阶段5 红队新发现的范围外既有行为问题（`.flow/archive/2026-10-15-stage5-final/handoff.md` 遗留清单），用户指令开专项 flow 修复。

## 一句话目标

coupon 工具链对"整数分金额超出 float 可表示范围"（>|1.8e308|，如 10³⁰⁹）的输入返回明确的 422/候选不可行，而非未捕获 OverflowError 导致连接重置无响应。

## 复现证据（2026-10-15 本机实证，四条路径全部 RemoteDisconnected）

对 `POST /api/compare` 注入 `10**309`：

| 输入路径 | 崩溃点 | 现状结果 |
|---|---|---|
| 候选 `threshold_cents` | engine `_basket_branches` `float(t)`（engine.py:148） | 连接重置 |
| 篮子 `amount_cents` | engine `_baseline_basket_rows` `float(bk.amount_cents)`（engine.py:99） | 连接重置 |
| 篮子 `topup_amount_cents` | 同 threshold 路径（engine.py:148） | 连接重置 |
| `new_basket[].amount_cents` | simulate 新增成交块 `float(amt_j)` | 连接重置 |

根因：`route_post` 外层捕获元组是 `(SpecError, ValueError, KeyError, TypeError)`，**OverflowError ⊄ ValueError**（它是 ArithmeticError），全部炸穿 handler。

## 修复方案（草案，红队待攻击）

1. **根因层——输入校验**：
   - `spec.py _int_cents`（篮子金额/加购金额的统一 choke point，Basket.__post_init__ 调用）加 float 范围上限：`abs(v) > sys.float_info.max` → SpecError("…超出可计算范围")→ load_spec 阶段 422"场景不合法"（带前缀路径）
   - `engine.py _validate_candidate` 对 t/f 加同一上限 → SpecError → 经 compare 的 per-candidate catch 变 200 + coupon_legality 不可行行（与 F≥T 的既有语义一致）
2. **兜底层——server**：`route_post` 外层捕获元组加 OverflowError → 422"请求不合法"（防御未来新的转换点）
3. new_basket 金额：behavior.new_basket 是原始 dict 不经 _int_cents——由兜底层覆盖（422）或 engine 抛 SpecError

## 硬约束（不可推翻）

1. **阶段5 已钉行为不回退**：`amount_cents=2×10³⁰⁶` 必须仍走"200 计算 → 序列化 NaN → 422 请求不合法"路径（test_compare_nan_output_rejected_as_422 钉住）——float 上限（1.8e308）天然容纳 2e306，不得引入更紧的业务上限改变该行为。
2. **指纹门禁 19/19 保持绿**（engine 改动仅新增对原崩溃输入的拒绝路径，battery 无此类输入）。
3. spec errors 顺序钉死测试、markdown 封存、其余 223 项全绿。
4. 不动引擎既有算术（新增校验分支除外）；无新依赖。

## 开放问题

- `_validate_candidate` 拒绝后经 compare 变"200+不可行行"是否为期望语义（vs 422）？与 F≥T 一致性论证。
- bucket_min/max_cents 不经 `_int_cents`（Basket.__post_init__ 只校验 amount/topup）——桶界 10³⁰⁹ 会经 `t / 100` f-string 除法溢出，是否纳入本批？
- 兜底层加 OverflowError 后，错误文案归"请求不合法"还是单独文案？
- CLI 路径（console 命令）溢出输入：SpecError 后 `sys.exit(2)` 带信息（现状已 catch SpecError）——确认无需额外处理。
