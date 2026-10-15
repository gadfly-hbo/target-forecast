# 交接卡：OverflowError 空洞修复（完成于 2026-10-15）

## 已完成

- 提交 `451a288`（main → origin/main）：三层修复（`_int_cents` float 上限 / `_validate_candidate` t-f 上限 / load_spec+route_post 元组加 OverflowError）+ stress docstring + 8 函数 9 用例矩阵
- 四条原 RemoteDisconnected 路径与红队新发现的 10+ 字段路径全部变为明确 422/不可行行；独立 REVIEW 复验零断连
- 门禁零回退：指纹 19/19、NaN 422、errors 顺序钉死；全量 231 passed；ENGINE_VERSION 未动

## 响应形状（记录在案的三分）

- 篮子 int-cents（amount/topup）→ 422"场景不合法"（load_spec 层）
- 候选 t/f → 200 + coupon_legality 不可行行（compare per-candidate catch；stress 侧静默丢弃该行——stress.py docstring 已注）
- 比率字段（load_spec 内强转）→ 422"场景不合法"；兜底路径（q_table.q/new_basket.weight/import 行）→ 422"请求不合法：int too large..."（英文内部文案，PRD K2 接受）

## 残余（记录不做）

- 桶界 10³⁰⁹~1.8e310 区间：limitation 文案出现超长数字（不崩溃，红队 K4 实测）；≥1.8e310 由兜底 422
- 已落盘含巨大值的 scenarios/*.json 在 CLI 下仍 traceback（兜底只在 HTTP 侧；极窄残余）
- N1：界检查双处重复（PRD 认可的双层设计）
