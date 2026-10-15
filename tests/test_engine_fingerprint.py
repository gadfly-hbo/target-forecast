# -*- coding: utf-8 -*-
"""engine.simulate 逐位指纹门禁（阶段4，先例：test_httpkit_characterization）。

对 19 个 battery 用例序列化全量 SimulationResult（含 engine_version）取 sha256，
重构（simulate 拆五函数）前后必须逐 hash 相等——红队突变实验（MUT1/2/3）证明
现有 68 条 coupon 测试对"接线漂移"全部放行，本门禁是"只搬移不改算术"的唯一
可证伪验收。

hash 平台绑定说明：CPython + IEEE754 双精度下稳定；若在异机/异 Python 版本
失败，优先怀疑真实 FP 差异而非测试问题，可用 .flow/gen_fingerprint.py 的
配方重新封存（需在当次重构前对未重构代码生成）。

红队（fresh-context，2026-10-15）16 位历史值：12 个可复现用例已断言前缀一致
（golden 10 + no_n + c0_zero）；以下 7 个用例的红队 fixture 参数未留存，本机
重新封存为准，旧值仅作参考：absbig 34306f00cb131d2f / straddle_fees
100a9b19088c207a / mixed_topup_0 a9c0ad3fc12d310f / mixed_topup_4
bc0f9797f934faa3 / multinew b4b145c2e0badbc27 / qtable 06d4df090b846b6d /
combo dad16601057c4b99。
"""
import dataclasses
import hashlib
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from coupon_tool import load_spec, simulate  # noqa: E402
from coupon_tool.synthetic import synthetic_spec_dict  # noqa: E402

EXPECTED = {
    "golden_no_coupon": "16634525229d2f2e12df8b0156949d654b2a40946ece8fb9ee06812543563151",
    "golden_7900_500": "299c771b592a7f7d5deb6414a4e86dbd0ed55cd5909c9d6c96e8e849616e1af1",
    "golden_9900_1000": "77e4165f6c2998d0a4ad20689df397299debae3825b9992312231a9a1dd7b578",
    "golden_10900_500": "440df9f9dca3d6130ef8147aa019bdf225839569c167bc4ba4fd317a69b90e48",
    "golden_12900_500": "4859a42dcd4d4eddd25dd355cc66f880d74d078f56bd97a71d834196e3ffc743",
    "golden_13900_500": "5220de8e50cc855054c676c209d7dd64b80adac711d3c72e26fe3cc77b8106b7",
    "golden_13900_1000": "197dbc7f09ba58137c65a333cc0431d984333ca97b2d84fc1d8fc8d731c800e2",
    "golden_13900_2000": "151cc7fa2cc724fa2a053a06b2de43ee4c1bbacbf55356bb5d0b734758be6160",
    "golden_15900_500": "487b0502d959979c78077611156a1907885b0f7186bde2b361f444ce8e89c4b1",
    "golden_15900_1000": "450c92b8c786c3a26dbc09881ae03f47824bb30b23203e0d46212955ffa8650e",
    "no_n": "f9b06638d064eb8f6313d7ea402a9bb07f5d4b573bc7f1765326b19c395c78e5",
    "c0_zero": "32360df478aed4d21e71bd0025c3162841891d0fb7d45c48036f567ce39b96ac",
    "absbig": "0c9f5c64ed49ca1a7e902640de0dd2744159f04715ab442913110871b66081cd",
    "straddle_fees": "b95ad22722ff6240a1de1d540434abaf6c2ce2653888c7917472eec0bad34e82",
    "mixed_topup_0": "81f14a19596295c8f065cb05f3e4253af6563ef734abe43110ce8949cda1129c",
    "mixed_topup_4": "81f14a19596295c8f065cb05f3e4253af6563ef734abe43110ce8949cda1129c",
    "multinew": "da778ca6616a1dcab5d8ab3dcc2ece3abe4a42a202d1dfe24e0e16f4b6adb810",
    "qtable": "ecd9c12ed6c2d9c3d0ea2d11c65d5b7626a0f4fd855d5d8fc5dd7d8aaa1c11da",
    "combo": "7992c4aeb2b36e1e17eb18b892bc563c8a737198b5c4093ee87d6582a08c7b95",
}

RED_TEAM_16 = {  # 可复现用例的红队 16 位前缀（交叉核对）
    "golden_no_coupon": "16634525229d2f2e", "golden_7900_500": "299c771b592a7f7d",
    "golden_9900_1000": "77e4165f6c2998d0", "golden_10900_500": "440df9f9dca3d613",
    "golden_12900_500": "4859a42dcd4d4edd", "golden_13900_500": "5220de8e50cc8550",
    "golden_13900_1000": "197dbc7f09ba5813", "golden_13900_2000": "151cc7fa2cc724fa",
    "golden_15900_500": "487b0502d959979c", "golden_15900_1000": "450c92b8c786c3a2",
    "no_n": "f9b06638d064eb8f", "c0_zero": "32360df478aed4d2",
}

# 每个变体用例的目标断言（构造健全性：防退化 battery 静默封存）
SANITY = {
    "absbig": lambda res: any("超出可触达非购买者上限" in lim for lim in res.limitations),
    "straddle_fees": lambda res: any("穿过粗桶" in lim for lim in res.limitations),
    "mixed_topup_0": lambda res: any("恰好凑到门槛" in lim for lim in res.limitations),
    "mixed_topup_4": lambda res: any("恰好凑到门槛" in lim for lim in res.limitations),
    "multinew": lambda res: res.metrics["new_orders"] > 0,
    "qtable": lambda res: res.metrics["topup_redemptions"] > 0,
    "combo": lambda res: (any("穿过粗桶" in lim for lim in res.limitations)
                          and any("C₀=0" in lim for lim in res.limitations)),
}


def _cand(t, f):
    return {"enabled": t is not None, "threshold_cents": t, "face_value_cents": f}


def _case(name):
    d = synthetic_spec_dict()
    if name.startswith("golden_"):
        if name == "golden_no_coupon":
            t, f = None, 0
        else:
            t_s, f_s = name.replace("golden_", "").split("_")
            t, f = int(t_s), int(f_s)
        return load_spec(d), _cand(t, f)
    if name == "no_n":
        d["baseline"]["visitors"] = None
        return load_spec(d), _cand(15900, 500)
    if name == "c0_zero":
        d["baseline"]["conversion_rate"] = 0.0
        return load_spec(d), _cand(15900, 500)
    if name == "absbig":
        d["behavior"]["conversion"] = {"mode": "absolute", "delta_c_plus": 0.95}
        return load_spec(d), _cand(15900, 500)
    if name == "straddle_fees":
        d["baseline"]["baskets"][2]["bucket_min_cents"] = 10000
        d["baseline"]["baskets"][2]["bucket_max_cents"] = 14000
        d["cost"].update(fixed_fee_cents=100, fee_rate=0.01, fixed_activity_cost_cents=50000)
        return load_spec(d), _cand(13900, 500)
    if name in ("mixed_topup_0", "mixed_topup_4"):
        explicit = range(1, 5) if name == "mixed_topup_0" else range(0, 4)
        for i in explicit:
            d["baseline"]["baskets"][i]["topup_amount_cents"] = 20000
        return load_spec(d), _cand(20000, 500)
    if name == "multinew":
        d["behavior"]["new_basket"] = [
            {"label": "新增1", "weight": 0.6, "amount_cents": 15900, "margin_rate": 0.30, "redeem": 1},
            {"label": "新增2", "weight": 0.4, "amount_cents": 8000, "margin_rate": 0.30, "redeem": 1},
        ]
        return load_spec(d), _cand(15900, 500)
    if name == "qtable":
        d["behavior"]["q_mode"] = "table"
        d["behavior"]["q_table"] = [{"gap_max": 0.2, "q": 0.5}, {"ftr_max": 0.5, "q": 0.2}, {"q": 0.1}]
        return load_spec(d), _cand(15900, 500)
    if name == "combo":
        d["baseline"]["conversion_rate"] = 0.0
        d["baseline"]["baskets"][3]["bucket_min_cents"] = 13000
        d["baseline"]["baskets"][3]["bucket_max_cents"] = 15000
        return load_spec(d), _cand(13900, 500)
    raise ValueError(name)


@pytest.mark.parametrize("name", list(EXPECTED))
def test_simulate_fingerprint(name):
    spec, cand = _case(name)
    res = simulate(spec, cand)
    if name in SANITY:
        assert SANITY[name](res), f"{name} 的目标分支未被触发（battery 退化）"
    payload = json.dumps(dataclasses.asdict(res), sort_keys=True, ensure_ascii=False)
    digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()
    assert digest == EXPECTED[name], f"{name} 数值漂移（非纯搬移）"
    if name in RED_TEAM_16:
        assert digest.startswith(RED_TEAM_16[name])  # 红队基线交叉核对
