# -*- coding: utf-8 -*-
"""烟气-壁面辐射统一接口。

灰气体模型（Hottel 近黑壁闭合）：
    q'' = sigma (Tg^4-Tw^4) /
          (1/eps_g + 1/eps_w - 1)
    h_rad = q''/(Tg-Tw)

吸收率采用壁温下的 Hottel 修正；eps_wall 限定为 > 0.7。
pCO2/pH2O：Pa；光程 L：m；温度：K；热流：W/m²。
"""
from __future__ import annotations
import math
from dataclasses import dataclass
from .models.radiation.leckner import evaluate as leckner
from .models.radiation.wsgg import evaluate as wsgg
from .models.radiation.hitemp_grid import evaluate as hitemp_grid

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
                      eps_wall: float = 0.85, model: str = "wsgg", *,
                      total_pressure_atm: float | None = None,
                      x_co2: float | None = None, x_h2o: float | None = None) -> GasRadiationResult:
    if T_gas <= 0 or T_wall <= 0 or L <= 0:
        raise ValueError("T_gas、T_wall、L 必须为正")
    if pCO2 < 0 or pH2O < 0:
        raise ValueError("CO2/H2O 分压不能为负")
    if not (0.7 < eps_wall <= 1.0):
        raise ValueError("Hottel 近黑壁公式要求 eps_wall > 0.7 且 <= 1")
    normalized_model = model.lower()
    fn = {"wsgg": wsgg, "leckner": leckner, "hitemp_grid": hitemp_grid}.get(normalized_model)
    if fn is None:
        raise ValueError("radiation model 必须为 'wsgg'、'leckner' 或 'hitemp_grid'")

    def evaluate_at_wall_temperature(wall_temperature: float):
        if normalized_model == "hitemp_grid":
            return fn(T_gas, wall_temperature, pCO2, pH2O, L, eps_wall,
                      total_pressure_atm=total_pressure_atm, x_co2=x_co2, x_h2o=x_h2o)
        return fn(T_gas, wall_temperature, pCO2, pH2O, L, eps_wall)

    r = evaluate_at_wall_temperature(T_wall)
    phi_wall = (1.0 + eps_wall) / 2.0
    q = phi_wall * SIGMA * (
        r.emissivity * T_gas**4 - r.absorptivity * T_wall**4
    )
    if abs(T_gas - T_wall) > 1e-12:
        h = q / (T_gas - T_wall)
    else:
        # Stable equal-temperature limit from d(alpha(Tw)*Tw^4)/dTw
        # at fixed gas state.
        step = max(1e-3, T_wall * 1e-5)
        t_lo = max(1e-9, T_wall - step)
        t_hi = T_wall + step
        alpha_lo = evaluate_at_wall_temperature(t_lo).absorptivity
        alpha_hi = evaluate_at_wall_temperature(t_hi).absorptivity
        absorbed_derivative = (
            alpha_hi * t_hi**4 - alpha_lo * t_lo**4
        ) / (t_hi - t_lo)
        h = phi_wall * SIGMA * max(0.0, absorbed_derivative)
    return GasRadiationResult(r.emissivity, r.absorptivity, r.kappa_eff, r.optical_thickness, L, q, h, model.lower())
