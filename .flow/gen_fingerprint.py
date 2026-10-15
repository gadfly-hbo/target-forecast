# -*- coding: utf-8 -*-
"""阶段4 指纹生成器：对当前（未重构）engine 计算 19 用例 sha256，交叉核对红队可复现值。

用法：.venv/bin/python .flow/gen_fingerprint.py   （输出 EXPECTED dict 片段供测试内联）
"""
import dataclasses
import hashlib
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from coupon_tool import load_spec, simulate
from coupon_tool.synthetic import synthetic_spec_dict

RED_TEAM_16 = {
    "golden_no_coupon": "16634525229d2f2e", "golden_79_5": "299c771b592a7f7d",
    "golden_99_10": "77e4165f6c2998d0", "golden_109_5": "440df9f9dca3d613",
    "golden_129_5": "4859a42dcd4d4edd", "golden_139_5": "5220de8e50cc8550",
    "golden_139_10": "197dbc7f09ba5813", "golden_139_20": "151cc7fa2cc724fa",
    "golden_159_5": "487b0502d959979c", "golden_159_10": "450c92b8c786c3a2",
    "no_n": "f9b06638d064eb8f", "c0_zero": "32360df478aed4d2",
}


def _cand(t, f):
    return {"enabled": t is not None, "threshold_cents": t, "face_value_cents": f}


def battery():
    """返回 [(name, spec, candidate)]——GRILL Q2 定义基准。"""
    cases = []
    for t, f in [(None, 0), (7900, 500), (9900, 1000), (10900, 500), (12900, 500),
                 (13900, 500), (13900, 1000), (13900, 2000), (15900, 500), (15900, 1000)]:
        cases.append((f"golden_{t}_{f}" if t is not None else "golden_no_coupon",
                      load_spec(synthetic_spec_dict()), _cand(t, f)))

    d = synthetic_spec_dict(); d["baseline"]["visitors"] = None
    cases.append(("no_n", load_spec(d), _cand(15900, 500)))
    d = synthetic_spec_dict(); d["baseline"]["conversion_rate"] = 0.0
    cases.append(("c0_zero", load_spec(d), _cand(15900, 500)))
    d = synthetic_spec_dict(); d["behavior"]["conversion"] = {"mode": "absolute", "delta_c_plus": 0.95}
    cases.append(("absbig", load_spec(d), _cand(15900, 500)))
    d = synthetic_spec_dict()
    d["baseline"]["baskets"][2]["bucket_min_cents"], d["baseline"]["baskets"][2]["bucket_max_cents"] = 10000, 14000
    d["cost"].update(fixed_fee_cents=100, fee_rate=0.01, fixed_activity_cost_cents=50000)
    cases.append(("straddle_fees", load_spec(d), _cand(13900, 500)))
    d = synthetic_spec_dict()
    for i in range(1, 5):
        d["baseline"]["baskets"][i]["topup_amount_cents"] = 20000
    cases.append(("mixed_topup_0", load_spec(d), _cand(20000, 500)))
    d = synthetic_spec_dict()
    for i in range(0, 4):
        d["baseline"]["baskets"][i]["topup_amount_cents"] = 20000
    cases.append(("mixed_topup_4", load_spec(d), _cand(20000, 500)))
    d = synthetic_spec_dict()
    d["behavior"]["new_basket"] = [
        {"label": "新增1", "weight": 0.6, "amount_cents": 15900, "margin_rate": 0.30, "redeem": 1},
        {"label": "新增2", "weight": 0.4, "amount_cents": 8000, "margin_rate": 0.30, "redeem": 1},
    ]
    cases.append(("multinew", load_spec(d), _cand(15900, 500)))
    d = synthetic_spec_dict()
    d["behavior"]["q_mode"] = "table"
    d["behavior"]["q_table"] = [{"gap_max": 0.2, "q": 0.5}, {"ftr_max": 0.5, "q": 0.2}, {"q": 0.1}]
    cases.append(("qtable", load_spec(d), _cand(15900, 500)))
    d = synthetic_spec_dict()
    d["baseline"]["conversion_rate"] = 0.0
    d["baseline"]["baskets"][3]["bucket_min_cents"], d["baseline"]["baskets"][3]["bucket_max_cents"] = 13000, 15000
    cases.append(("combo", load_spec(d), _cand(13900, 500)))
    return cases


def digest(res) -> str:
    payload = json.dumps(dataclasses.asdict(res), sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


if __name__ == "__main__":
    out, failed = {}, []
    for name, spec, cand in battery():
        h = digest(simulate(spec, cand))
        out[name] = h
        if name in RED_TEAM_16 and not h.startswith(RED_TEAM_16[name]):
            failed.append((name, h[:16], RED_TEAM_16[name]))
    print("EXPECTED = {")
    for k, v in out.items():
        print(f'    "{k}": "{v}",')
    print("}")
    if failed:
        print("CROSS-CHECK FAILED:", failed)
        sys.exit(1)
    print("cross-check: 12/12 match red-team prefixes")
