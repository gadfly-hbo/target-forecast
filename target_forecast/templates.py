"""输入模板生成：templates/ 下两种填数模板（含示例行与填数说明）。"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

DETAIL_COLS = ["日期", "订单号", "用户ID", "商品ID", "品类", "件数", "实付金额", "原价金额"]
DETAIL_NOTES = [
    "【通用订单明细表 · 模式A】一行 = 一个订单行；同一订单号买多件商品可跨多行。",
    "必填：日期、订单号、用户ID、商品ID、实付金额；选填：品类（缺省记「未分类」）、件数（缺省1）、原价金额。",
    "实付金额 = 支付口径净额（已扣退款）；各平台后台导出后把字段名映射成表头即可，平台名写在文件名上（如 天猫.xlsx）。",
    "放到 data/orders/ 目录下，每个平台一个文件。",
    "注意：订单明细不含UV/转化率，本模式下主测算口径为「人」视角；需要场视角请改用聚合模板。",
    "日期支持 Excel 日期或 2026/9/1 等写法；用户ID/订单号/商品ID 请按文本处理，避免科学计数法。",
]
DETAIL_EXAMPLE = pd.DataFrame([
    {"日期": pd.Timestamp("2026-09-01"), "订单号": "O10001", "用户ID": "U000123", "商品ID": "S001",
     "品类": "上衣", "件数": 1, "实付金额": 199.0, "原价金额": 249.0},
    {"日期": pd.Timestamp("2026-09-01"), "订单号": "O10001", "用户ID": "U000123", "商品ID": "S018",
     "品类": "配饰", "件数": 2, "实付金额": 118.0, "原价金额": 139.0},
    {"日期": pd.Timestamp("2026-09-02"), "订单号": "O10002", "用户ID": "U000124", "商品ID": "S007",
     "品类": "连衣裙", "件数": 1, "实付金额": 329.0, "原价金额": 399.0},
])

AGG_COLS = ["月份", "UV", "新客数", "新客客单", "老客数", "老客复购频次", "老客客单"]
AGG_NOTES = [
    "【聚合指标表 · 模式B】一行 = 一个平台一个月。",
    "必填：月份、新客数、新客客单、老客数、老客复购频次、老客客单；选填：UV、新客订单数、转化率、GMV（后两者仅作一致性校验）。",
    "GMV由公式派生：新客数×新客客单 + 老客数×复购频次×老客客单；填了UV则启用场视角（UV×转化×客单）作为主口径。",
    "老客复购频次 = 该月老客订单数 ÷ 老客人数；月份写 YYYY-MM（如 2026-09）。",
    "放到 data/metrics/ 目录下，每个平台一个文件。",
]
AGG_EXAMPLE = pd.DataFrame([
    {"月份": "2026-07", "UV": 3120, "新客数": 168, "新客客单": 152.5, "老客数": 655,
     "老客复购频次": 1.31, "老客客单": 176.2},
    {"月份": "2026-08", "UV": 3244, "新客数": 175, "新客客单": 158.9, "老客数": 668,
     "老客复购频次": 1.33, "老客客单": 174.8},
])


def build(root: Path) -> None:
    out = root / "templates"
    out.mkdir(parents=True, exist_ok=True)
    with pd.ExcelWriter(out / "订单明细模板.xlsx", engine="openpyxl") as xw:
        pd.DataFrame({"填数说明": DETAIL_NOTES}).to_excel(xw, sheet_name="填数说明", index=False)
        DETAIL_EXAMPLE.to_excel(xw, sheet_name="通用订单明细", index=False)
    with pd.ExcelWriter(out / "聚合指标模板.xlsx", engine="openpyxl") as xw:
        pd.DataFrame({"填数说明": AGG_NOTES}).to_excel(xw, sheet_name="填数说明", index=False)
        AGG_EXAMPLE.to_excel(xw, sheet_name="聚合指标", index=False)
    print(f"输入模板已生成 → {out}/")
