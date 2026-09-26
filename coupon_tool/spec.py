# -*- coding: utf-8 -*-
"""ScenarioSpec：优惠券测算的领域对象与校验（提案 §11 协议的 P0 落地）。

金额一律整数分（int），转"元"只发生在显示层；概率与比率为 float。
结构/类型错误（含非整数分）在 load_spec 即抛 SpecError；
语义错误（权重不守恒、非法概率等）默认抛出，strict=False 时留给 validate_spec 报告。
"""
from __future__ import annotations

from dataclasses import dataclass, field, asdict

ENGINE_VERSION = "0.1.0"


class SpecError(ValueError):
    """场景不合法或无法安全测算。"""


def _int_cents(value, name):
    if isinstance(value, bool) or not isinstance(value, int):
        raise SpecError(f"{name} 必须是整数分（int），得到 {value!r}")
    return value


def _prob(value, name, errors):
    if not (isinstance(value, (int, float)) and 0.0 <= value <= 1.0):
        errors.append(f"{name} 必须是 [0,1] 内的概率，得到 {value!r}")
    return value


@dataclass
class Basket:
    """基准成交篮子类型：券前金额、条件权重、可选覆盖毛利率。"""
    amount_cents: int
    weight: float
    margin_rate: float | None = None
    label: str = ""
    topup_amount_cents: int | None = None  # 显式加购后金额；缺省 = 门槛 T（恰好凑单简化）
    bucket_min_cents: int | None = None    # 粗桶区间（可选）：用于 M15 穿桶检查
    bucket_max_cents: int | None = None

    def __post_init__(self):
        self.amount_cents = _int_cents(self.amount_cents, "篮子金额")
        if self.topup_amount_cents is not None:
            self.topup_amount_cents = _int_cents(self.topup_amount_cents, "加购后金额")


@dataclass
class Baseline:
    visitors: int | None          # N；None = 缺 N 降级为每观察单位口径
    conversion_rate: float        # C₀（无本次券）
    baskets: list[Basket]
    data_snapshot_id: str | None = None


@dataclass
class CostProfile:
    margin_base_rate: float                # 原篮子商品毛利率
    margin_addon_rate: float | None        # 加购部分毛利率；None = 未显式设置（告警后按 base 计）
    merchant_share_rho: float = 1.0        # 商家承担比例 ρ
    fixed_fee_cents: float = 0.0           # V：每单固定可变费用
    fee_rate: float = 0.0                  # V：费率
    fee_basis: str = "customer_paid"       # customer_paid | pre_coupon（收费基数必须显式）
    return_adj_cents: float = 0.0          # H：每单退货等结算路径期望净减少额（情景估计）
    fixed_activity_cost_cents: float = 0.0  # K：相对无券方案的新增固定费用
    margin_includes_fulfillment: bool = False  # 毛利率已含履约成本时，不得再填履约费（M16）


@dataclass
class Behavior:
    reach_base: float | list = 1.0         # e：基准购买者有效触达（可逐篮子）
    reach_new: float = 1.0                 # e⁺：基准非购买者有效触达
    redeem_natural: float | list = 0.8     # r：自然达标核销率
    redeem_topup: float | list = 1.0       # r⁺：加购达标核销率
    churn: float | list = 0.0              # d：未加购达标者放弃原本购买概率
    q_mode: str = "curve"                  # curve | table | zero
    q_curve: dict = field(default_factory=lambda: {"q_cap": 0.8, "lam": 2.2, "d_ref": 0.1})
    q_table: list = field(default_factory=list)  # [{gap_max, ftr_max, q}] 首个匹配行生效
    conversion: dict = field(default_factory=lambda: {"mode": "relative", "k": 0.9, "s_max": 0.5})
    new_basket: list = field(default_factory=list)  # [{label,weight,amount_cents,margin_rate,redeem}]
    topup_amount_mode: str = "at_threshold"


@dataclass
class Constraints:
    merchant_coupon_budget_cents: float | None = None
    min_incremental_contribution_cents: float = 0.0
    allow_controlled_loss: bool = False
    max_loss_cents: float | None = None
    min_conversion_rate: float | None = None
    min_delta_c: float | None = None        # 净转化变化下限（百分点由显示层换算）
    min_gmv_pre_cents: float | None = None
    min_avg_contribution_cents: float | None = None
    max_ft_ratio: float | None = None       # F/T 折扣上限（业务规则，非套利证明）


@dataclass
class ScenarioSpec:
    schema_version: str
    scenario_id: str
    currency: str = "CNY"
    observation_unit: str = "unique_visitor_first_paid_order"
    window: dict = field(default_factory=dict)
    baseline: Baseline | None = None
    candidates: list = field(default_factory=list)
    cost: CostProfile | None = None
    behavior: Behavior | None = None
    constraints: Constraints = field(default_factory=Constraints)
    objective: str = "incremental_contribution"
    objective_params: dict = field(default_factory=dict)  # balanced: w_profit/w_conversion/profit_scale/conversion_scale
    evidence_status: str = "synthetic_assumptions"
    parameter_sources: dict = field(default_factory=dict)  # 参数名 -> {source_type, note}

    def to_dict(self) -> dict:
        d = asdict(self)
        return d


# ---------------- 载入与校验 ----------------

def _check_semantics(spec: ScenarioSpec) -> list[str]:
    errors: list[str] = []
    b = spec.baseline
    if b is None:
        return ["缺少 baseline"]
    wsum = sum(bk.weight for bk in b.baskets)
    if abs(wsum - 1.0) > 1e-9:
        errors.append(f"基准篮子权重合计必须为 1，实际 {wsum:.6f}")
    for i, bk in enumerate(b.baskets):
        if bk.weight < 0:
            errors.append(f"篮子[{i}]权重为负")
        if bk.amount_cents <= 0:
            errors.append(f"篮子[{i}]金额必须 > 0")
        if bk.margin_rate is not None and not 0.0 <= bk.margin_rate <= 1.0:
            errors.append(f"篮子[{i}]毛利率必须在 [0,1]")
    _prob(b.conversion_rate, "基准转化率 C₀", errors)
    if not (0.0 <= b.conversion_rate < 1.0):
        errors.append("C₀ 必须在 [0,1)（C₀=1 时无新增空间）")
    if b.visitors is not None and b.visitors <= 0:
        errors.append("N 必须为正整数（缺 N 请置 None 走每单位口径）")
    if not b.baskets:
        errors.append("基准篮子分布为空")
    return errors


def _check_cost(spec: ScenarioSpec) -> list[str]:
    errors: list[str] = []
    c = spec.cost
    if c is None:
        return ["缺少 cost"]
    if not 0.0 <= c.margin_base_rate <= 1.0:
        errors.append("原篮子毛利率必须在 [0,1]")
    if c.margin_addon_rate is not None and not 0.0 <= c.margin_addon_rate <= 1.0:
        errors.append("加购毛利率必须在 [0,1]")
    _prob(c.merchant_share_rho, "商家承担比例 ρ", errors)
    if c.fee_basis not in ("customer_paid", "pre_coupon"):
        errors.append(f"不支持的收费基数 {c.fee_basis!r}")
    if c.fixed_fee_cents < 0 or c.fee_rate < 0 or c.return_adj_cents < 0:
        errors.append("费用/退货调整为负")
    if c.margin_includes_fulfillment and (c.fixed_fee_cents > 0 or c.fee_rate > 0):
        errors.append("成本重复扣减：毛利率已包含履约成本，又填写了履约费（先明确口径再测算）")
    return errors


def _per_basket_ok(values, n) -> bool:
    if isinstance(values, list):
        return len(values) == n and all(isinstance(v, (int, float)) for v in values)
    return isinstance(values, (int, float))


def _check_behavior(spec: ScenarioSpec) -> list[str]:
    errors: list[str] = []
    h = spec.behavior
    if h is None:
        return ["缺少 behavior"]
    n = len(spec.baseline.baskets)
    for name in ("reach_base", "redeem_natural", "redeem_topup", "churn"):
        values = getattr(h, name)
        if not _per_basket_ok(values, n):
            errors.append(f"{name} 必须是标量或与篮子数等长的列表")
        else:
            vals = values if isinstance(values, list) else [values] * n
            for i, v in enumerate(vals):
                _prob(v, f"{name}[{i}]", errors)
    _prob(h.reach_new, "新增触达 e⁺", errors)
    if h.q_mode not in ("curve", "table", "zero"):
        errors.append(f"未知凑单模式 {h.q_mode!r}")
    if h.q_mode == "curve":
        qc = h.q_curve
        _prob(qc.get("q_cap", 0.8), "q_cap", errors)
        if qc.get("lam", 2.2) < 0:
            errors.append("λ 必须 ≥ 0")
        if qc.get("d_ref", 0.1) <= 0:
            errors.append("d_ref 必须 > 0")
    if h.q_mode == "table" and not h.q_table:
        errors.append("凑单参数表为空")
    conv = h.conversion
    if conv.get("mode") == "relative":
        if conv.get("k", 0.9) < 0:
            errors.append("k 必须 ≥ 0")
        if conv.get("s_max", 0.5) < 0:
            errors.append("s_max 必须 ≥ 0")
    elif conv.get("mode") == "absolute":
        dcp = conv.get("delta_c_plus")
        if not isinstance(dcp, (int, float)) or dcp < 0:
            errors.append("绝对 ΔC⁺ 必须为非负数")
    else:
        errors.append(f"未知转化响应模式 {conv.get('mode')!r}")
    wsum = sum(nb.get("weight", 0.0) for nb in h.new_basket)
    if h.new_basket and abs(wsum - 1.0) > 1e-9:
        errors.append(f"新增结果分布 vⱼ 权重合计必须为 1，实际 {wsum:.6f}")
    for j, nb in enumerate(h.new_basket):
        amt = nb.get("amount_cents", "at_threshold")
        if amt != "at_threshold" and (not isinstance(amt, int) or isinstance(amt, bool) or amt <= 0):
            errors.append(f"新增结果[{j}]金额必须是正整数分或 'at_threshold'")
        if nb.get("redeem") not in (0, 1):
            errors.append(f"新增结果[{j}]核销状态必须为 0/1")
    if not h.new_basket:
        errors.append("缺少新增结果分布 vⱼ")
    return errors


def validate_spec(spec: ScenarioSpec) -> dict:
    """返回 {errors, warnings}；errors 非空时不得测算。"""
    errors = _check_semantics(spec) + _check_cost(spec) + _check_behavior(spec)
    if spec.constraints.allow_controlled_loss and spec.constraints.max_loss_cents is None:
        errors.append("受控亏损必须显式设置最大损失额度（max_loss_cents），不得静默退化为底线 0")
    warnings: list[str] = []
    if spec.cost is not None and spec.cost.margin_addon_rate is None:
        warnings.append("加购毛利率未显式设置，按原篮子毛利率计算（提案要求显式确认）")
    if spec.baseline is not None and spec.baseline.visitors is None:
        warnings.append("缺 N：结果为每观察单位口径，不输出活动总量")
    return {"errors": errors, "warnings": warnings}


def load_spec(data: dict, strict: bool = True) -> ScenarioSpec:
    """从 JSON dict 构建 ScenarioSpec。结构错误总是抛出；语义错误在 strict 时抛出。"""
    try:
        base = data.get("baseline", {})
        baskets = [Basket(**bk) for bk in base.get("baskets", [])]
        baseline = Baseline(
            visitors=base.get("visitors"),
            conversion_rate=float(base.get("conversion_rate", 0.0)),
            baskets=baskets,
            data_snapshot_id=base.get("data_snapshot_id"),
        )
        cost_data = dict(data.get("cost", {}))
        cost = CostProfile(margin_base_rate=float(cost_data.pop("margin_base_rate", 0.0)),
                           margin_addon_rate=(float(cost_data["margin_addon_rate"])
                                              if cost_data.get("margin_addon_rate") is not None else None),
                           merchant_share_rho=float(cost_data.get("merchant_share_rho", 1.0)),
                           fixed_fee_cents=float(cost_data.get("fixed_fee_cents", 0.0)),
                           fee_rate=float(cost_data.get("fee_rate", 0.0)),
                           fee_basis=cost_data.get("fee_basis", "customer_paid"),
                           return_adj_cents=float(cost_data.get("return_adj_cents", 0.0)),
                           fixed_activity_cost_cents=float(cost_data.get("fixed_activity_cost_cents", 0.0)),
                           margin_includes_fulfillment=bool(cost_data.get("margin_includes_fulfillment", False)))
        h = dict(data.get("behavior", {}))
        behavior = Behavior(
            reach_base=h.get("reach_base", 1.0),
            reach_new=float(h.get("reach_new", 1.0)),
            redeem_natural=h.get("redeem_natural", 0.8),
            redeem_topup=h.get("redeem_topup", 1.0),
            churn=h.get("churn", 0.0),
            q_mode=h.get("q_mode", "curve"),
            q_curve=dict(h.get("q_curve", {})) or {"q_cap": 0.8, "lam": 2.2, "d_ref": 0.1},
            q_table=list(h.get("q_table", [])),
            conversion=dict(h.get("conversion", {})) or {"mode": "relative", "k": 0.9, "s_max": 0.5},
            new_basket=list(h.get("new_basket", [])),
            topup_amount_mode=h.get("topup_amount_mode", "at_threshold"),
        )
        cons = dict(data.get("constraints", {}))
        constraints = Constraints(
            merchant_coupon_budget_cents=cons.get("merchant_coupon_budget_cents"),
            min_incremental_contribution_cents=float(cons.get("min_incremental_contribution_cents", 0.0)),
            allow_controlled_loss=bool(cons.get("allow_controlled_loss", False)),
            max_loss_cents=cons.get("max_loss_cents"),
            min_conversion_rate=cons.get("min_conversion_rate"),
            min_delta_c=cons.get("min_delta_c"),
            min_gmv_pre_cents=cons.get("min_gmv_pre_cents"),
            min_avg_contribution_cents=cons.get("min_avg_contribution_cents"),
            max_ft_ratio=cons.get("max_ft_ratio"),
        )
        spec = ScenarioSpec(
            schema_version=str(data.get("schema_version", "2.0")),
            scenario_id=str(data.get("scenario_id", "unnamed")),
            currency=data.get("currency", "CNY"),
            observation_unit=data.get("observation_unit", "unique_visitor_first_paid_order"),
            window=dict(data.get("window", {})),
            baseline=baseline,
            candidates=list(data.get("candidates", [])),
            cost=cost,
            behavior=behavior,
            constraints=constraints,
            objective=data.get("objective", "incremental_contribution"),
            objective_params=dict(data.get("objective_params", {})),
            evidence_status=data.get("evidence_status", "synthetic_assumptions"),
            parameter_sources=dict(data.get("parameter_sources", {})),
        )
    except SpecError:
        raise
    except (TypeError, KeyError, ValueError) as exc:
        raise SpecError(f"场景结构不合法：{exc}") from exc

    if strict:
        result = validate_spec(spec)
        if result["errors"]:
            raise SpecError("；".join(result["errors"]))
    return spec
