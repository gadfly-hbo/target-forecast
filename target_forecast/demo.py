"""演示数据生成器：3个平台的通用订单明细（模式A）+ 1个私域聚合指标（模式B）。

- 明细含 6 个月「预热期」（2024-04 起，不落盘），使新老客滚动口径在正式数据起点处已稳定
- 正式历史期：2024-10 ~ 2026-09，共 24 个月；季节性含 618 / 双11 大促
- SKU 热度按 Zipf 分布生成，天然形成爆款帕累托结构
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

CATEGORIES = ["上衣", "裤装", "连衣裙", "外套", "鞋靴", "配饰"]
CAT_W = [0.28, 0.20, 0.18, 0.15, 0.11, 0.08]
SEASON = {1: 0.72, 2: 0.62, 3: 0.95, 4: 0.80, 5: 0.85, 6: 1.35,
          7: 0.90, 8: 0.90, 9: 1.00, 10: 1.05, 11: 1.80, 12: 1.15}

DETAIL_PLATFORMS = {
    "天猫": dict(base_orders=620, trend=1.005, new_rate=0.28, price_mu=5.3),
    "抖音": dict(base_orders=420, trend=1.014, new_rate=0.48, price_mu=5.1),
    "京东": dict(base_orders=290, trend=1.002, new_rate=0.24, price_mu=5.2),
}
SAVE_SINCE = "2024-10"


def _month_range(start: str, end: str):
    return pd.period_range(start, end, freq="M")


def _gen_skus(rng, n=100, extra_new=12):
    """n 个基础款（数据起点即在售）+ extra_new 个中途上架的新品（2026-06/07 上架）。

    新品热度取基础款第 5~30 名的量级，使其上架后有机会直接冲进爆款区。
    """
    total = n + extra_new
    cat = rng.choice(CATEGORIES, size=total, p=CAT_W)
    price = np.round(np.exp(rng.normal(5.2, 0.45, total)) / 5) * 5 - 0.1  # …4.9 结尾
    pop = 1.0 / np.arange(1, n + 1) ** 1.05
    w = list(pop / pop.sum())
    new_w = [pop[r - 1] / pop.sum() for r in rng.integers(5, 31, extra_new)]
    since = [pd.Period("2024-04")] * n + [pd.Period("2026-06" if i % 2 else "2026-07")
                                          for i in range(extra_new)]
    return pd.DataFrame({"商品ID": [f"S{i:03d}" for i in range(1, total + 1)],
                         "品类": cat, "price": price,
                         "w": w + list(new_w), "since": since})


def gen_detail(root: Path) -> None:
    out_dir = root / "data" / "orders"
    out_dir.mkdir(parents=True, exist_ok=True)
    months = _month_range("2024-04", "2026-09")

    for platform, cfg in DETAIL_PLATFORMS.items():
        rng = np.random.default_rng(abs(hash(platform)) % 2**31)
        skus = _gen_skus(rng)
        pool, last_seen, uid = [], {}, 0
        rows = []
        for i, m in enumerate(months):
            n_orders = int(cfg["base_orders"] * cfg["trend"] ** i
                           * SEASON[m.month] * rng.uniform(0.93, 1.07))
            new_n = int(rng.binomial(n_orders, cfg["new_rate"]))
            users = []
            for _ in range(new_n):
                uid += 1
                users.append(f"U{uid:06d}")
            while len(users) < n_orders:
                users.append(rng.choice(pool) if pool else None)
            for j, u in enumerate(users):  # 预热期首月老客池为空，溢出名额转新客
                if u is None:
                    uid += 1
                    users[j] = f"U{uid:06d}"
            for j, u in enumerate(users):
                day = int(rng.integers(0, m.days_in_month))
                ts = m.to_timestamp() + pd.Timedelta(days=day)
                promo = 0.85 if m.month == 11 else (0.9 if m.month == 6 else 1.0)
                n_lines = rng.choice([1, 2, 3], p=[0.55, 0.30, 0.15])
                avail = skus[skus["since"] <= m].reset_index(drop=True)
                pw = avail["w"].values / avail["w"].values.sum()
                picks = rng.choice(len(avail), size=n_lines, replace=False, p=pw)
                for k in picks:
                    qty = int(rng.choice([1, 2], p=[0.8, 0.2]))
                    p0 = avail["price"].iloc[k]
                    paid = round(p0 * qty * promo * rng.uniform(0.96, 1.0), 2)
                    rows.append({
                        "日期": ts, "订单号": f"O{i:03d}{j:05d}", "用户ID": u,
                        "商品ID": avail["商品ID"].iloc[k], "品类": avail["品类"].iloc[k],
                        "件数": qty, "实付金额": paid, "原价金额": round(p0 * qty, 2),
                    })
                last_seen[u] = ts
            # 更新老客池：保留近 400 天内有购买的用户
            cutoff = m.to_timestamp() + pd.Timedelta(days=m.days_in_month) - pd.Timedelta(days=400)
            pool = sorted(u for u, t in last_seen.items() if t >= cutoff)
        df = pd.DataFrame(rows)
        df = df[df["日期"].dt.strftime("%Y-%m") >= SAVE_SINCE].reset_index(drop=True)
        path = out_dir / f"{platform}.xlsx"
        with pd.ExcelWriter(path, engine="openpyxl") as xw:
            df.to_excel(xw, sheet_name="通用订单明细", index=False)
        print(f"  演示明细 [{platform}] {len(df):,} 行 × {df['日期'].min():%Y-%m}~{df['日期'].max():%Y-%m} → {path.name}")


def gen_agg(root: Path) -> None:
    out_dir = root / "data" / "metrics"
    out_dir.mkdir(parents=True, exist_ok=True)
    rng = np.random.default_rng(7)
    rows = []
    for i, m in enumerate(_month_range(SAVE_SINCE, "2026-09")):
        season = 0.6 + SEASON[m.month] * 0.4  # 私域大促弹性弱于平台
        uv = 3200 * 1.008 ** i * season * rng.uniform(0.95, 1.05)
        new_c = uv * 0.055 * rng.uniform(0.9, 1.1)
        rows.append({
            "月份": str(m), "UV": round(uv),
            "新客数": round(new_c), "新客客单": round(155 * rng.uniform(0.95, 1.05), 1),
            "老客数": round(640 * 1.006 ** i * season * rng.uniform(0.95, 1.05)),
            "老客复购频次": round(1.35 * rng.uniform(0.96, 1.04), 2),
            "老客客单": round(175 * rng.uniform(0.96, 1.04), 1),
        })
    df = pd.DataFrame(rows)
    path = out_dir / "私域.xlsx"
    with pd.ExcelWriter(path, engine="openpyxl") as xw:
        df.to_excel(xw, sheet_name="聚合指标", index=False)
    print(f"  演示聚合 [私域] {len(df)} 行 → {path.name}")


def generate(root: Path) -> None:
    print("生成演示数据（data/orders/*.xlsx 模式A + data/metrics/*.xlsx 模式B）…")
    gen_detail(root)
    gen_agg(root)
