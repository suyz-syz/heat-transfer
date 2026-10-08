# -*- coding: utf-8 -*-
"""对流换热统一接口；第一阶段保留现有关联式行为。"""
from __future__ import annotations
import math
from .properties import get_gas_properties

def gnielinski_h(v: float, D: float, L: float, T_f: float, P_pa: float, gas=None) -> float:
    if min(v, D, L, T_f, P_pa) <= 0:
        raise ValueError("速度、尺度、温度和压力必须为正")
    props = get_gas_properties(T_f, P_pa, gas)
    Re = v * D / (props.mu / props.rho)
    Pr = props.Pr
    if Re >= 10000.0:
        f = (0.79 * math.log(Re) - 1.64) ** -2
        Nu_fd = (f/8.0) * (Re-1000.0) * Pr / (1.0 + 12.7*math.sqrt(f/8.0)*(Pr**(2.0/3.0)-1.0))
    elif Re <= 2300.0:
        Nu_fd = 3.66
    else:
        f = (0.79 * math.log(Re) - 1.64) ** -2
        Nu_t = (f/8.0) * (Re-1000.0) * Pr / (1.0 + 12.7*math.sqrt(f/8.0)*(Pr**(2.0/3.0)-1.0))
        x = (Re-2300.0)/(10000.0-2300.0)
        Nu_fd = 3.66 + x*(Nu_t-3.66)
    return Nu_fd * (1.0 + (D/L)**(2.0/3.0)) * props.k / D

def get_h_conv(*, v: float, D: float, L: float, T_f: float, P_pa: float, gas=None) -> float:
    return gnielinski_h(v, D, L, T_f, P_pa, gas)
