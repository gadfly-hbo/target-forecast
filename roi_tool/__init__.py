# -*- coding: utf-8 -*-
"""投放 ROI 测算工具：测算引擎 + workbench 插件适配。"""
ENGINE_VERSION = "1.0"

from .demo import build_demo_plans, default_scenarios, demo_meta, evaluate_demo  # noqa: F401,E402
from .engine import PlanError, evaluate, validate_plan  # noqa: F401,E402
