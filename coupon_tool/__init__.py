# -*- coding: utf-8 -*-
"""优惠券测算工具（P0）：本地、确定性、可解释的满减券情景测算与比较。

公共库接口（提案 §10.2 的 P0 子集）：
    load_spec / validate_spec / simulate
（compare / stress_test / create_review 随后续切片加入）
"""
from .spec import ENGINE_VERSION, SpecError, ScenarioSpec, load_spec, validate_spec
from .engine import SimulationResult, simulate
from .compare import ComparisonResult, compare, generate_candidates
from .stress import SensitivityResult, stress_test, single_factor_variants
from .review import create_review, DEVIATION_CATEGORIES
from .synthetic import build_synthetic_spec, synthetic_spec_dict

__all__ = [
    "ENGINE_VERSION", "SpecError", "ScenarioSpec", "load_spec", "validate_spec",
    "SimulationResult", "simulate", "ComparisonResult", "compare", "generate_candidates",
    "SensitivityResult", "stress_test", "single_factor_variants",
    "create_review", "DEVIATION_CATEGORIES",
    "build_synthetic_spec",
    "synthetic_spec_dict",
]
