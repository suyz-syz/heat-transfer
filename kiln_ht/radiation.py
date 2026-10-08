# -*- coding: utf-8 -*-
"""烟气-壁面辐射统一接口。

灰气体模型：
    q'' = sigma (Tg^4-Tw^4) /
          (1/eps_g + 1/eps_w - 1)
    h_rad = q''/(Tg-Tw)

分压 pCO2/pH2O：Pa；光程 L：m；温度：K；热流：W/m²。
"""
from __future__ import annotations
import math
from dataclasses import dataclass
from .models.radiation.leckner import evaluate as leckner
from .models.radiation.wsgg import evaluate as wsgg

SIGMA = 5.670374419e-8

@dataclass(frozen=True)
class GasRadiationResult:
    emissivity: float
    absorptivity: float
    kappa_eff: float
    optical_thickness: float
    path_length: float
    q_rad: float
    h_rad: float
    model: str

def get_gas_radiation(T_gas: float, T_wall: float, pCO2: float, pH2O: float, L: float,
                      eps_wall: float = 0.85, model: str = "wsgg") -> GasRadiationResult:
    if T_gas <= 0 or T_wall <= 0 or L <= 0:
        raise ValueError("T_gas、T_wall、L 必须为正")
    if pCO2 < 0 or pH2O < 0:
        raise ValueError("CO2/H2O 分压不能为负")
    if not (0.0 < eps_wall <= 1.0):
        raise ValueError("eps_wall 必须在 (0,1] 内")
    fn = {"wsgg": wsgg, "leckner": leckner}.get(model.lower())
    if fn is None:
        raise ValueError("radiation model 必须为 'wsgg' 或 'leckner'")
    r = fn(T_gas, T_wall, pCO2, pH2O, L, eps_wall)
    denom = 1.0 / r.emissivity + 1.0 / eps_wall - 1.0 if r.emissivity > 0 else math.inf
    q = SIGMA * (T_gas**4 - T_wall**4) / denom if math.isfinite(denom) else 0.0
    h = q / (T_gas - T_wall) if abs(T_gas - T_wall) > 1e-12 else 4.0 * SIGMA * T_gas**3 / denom if math.isfinite(denom) else 0.0
    return GasRadiationResult(r.emissivity, r.absorptivity, r.kappa_eff, r.optical_thickness, L, q, h, model.lower())
