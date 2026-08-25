# -*- coding: utf-8 -*-
"""水泥窑窑衬多层圆筒壁一维稳态传热计算核心包（无 UI / 服务依赖，零第三方依赖）。"""

from .calc import (
    DEFAULT_P_TOTAL,
    GRAVITY,
    MAX_WALL_ITER,
    SIGMA,
    WALL_TOL,
    KilnParams,
    Layer,
    WallSolution,
    air_properties,
    compute_temperature_curve,
    gas_emissivity,
    inner_convection_h,
    inner_radiation_h,
    outer_forced_h,
    outer_natural_h,
    outer_radiation_h,
    solve_wall,
    validate_params,
)

__version__ = "1.0.0"
