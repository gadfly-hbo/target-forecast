"""统一字段定义：两种输入模式最终都汇到 UNIFIED_COLUMNS 这张月度指标表。"""

import pandas as pd

# ---------- 模式A：通用订单明细表 ----------
# 各平台后台导出后做一次字段映射落到这里；一行 = 一个订单行（订单号可重复，跨商品行）
DETAIL_REQUIRED = ["日期", "订单号", "用户ID", "商品ID", "实付金额"]
DETAIL_OPTIONAL = ["品类", "件数", "原价金额", "平台"]

# ---------- 模式B：聚合指标表（一行 = 一个平台一个月） ----------
AGG_REQUIRED = ["月份", "新客数", "新客客单", "老客数", "老客复购频次", "老客客单"]
AGG_OPTIONAL = ["UV", "新客订单数", "转化率", "GMV"]  # GMV/转化率仅作一致性校验

# ---------- 统一月度指标层 ----------
# uv 仅模式B（或另附流量数据）才有；模式A下为 NaN，场视角自动降级为校验缺席。
UNIFIED_COLUMNS = [
    "platform", "month",      # month: 'YYYY-MM'
    "gmv", "orders", "units", "buyers", "uv",
    "new_customers", "new_gmv", "new_orders",
    "old_customers", "old_gmv", "old_orders",
]

SCENARIOS = ["保守", "基准", "挑战"]


def empty_unified(platform: str) -> pd.DataFrame:
    return pd.DataFrame({c: [] for c in UNIFIED_COLUMNS}).assign(platform=platform)
