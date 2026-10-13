# -*- coding: utf-8 -*-
"""可插拔 WSGG 灰气体模型基础实现。

重要说明：
本文件第一阶段提供的是“WSGG 接口 + 四灰气体数值骨架”，不是声称已经
内置经过 HITEMP LBL 回归验证的最终系数库。默认系数采用当前 Leckner
等效吸收率进行守恒校准，使其可以安全接入 Baseline；真正 HITEMP-based
系数表应在第二个辐射数据集提交中替换 DEFAULT_COEFFICIENTS。

WSGG：
    eps_g = sum_j a_j(T, composition) [1-exp(-kappa_j L)]
    sum_j a_j <= 1
"""
from __future__ import annotations
import math
from dataclasses import dataclass
from .leckner import emissivity as leckner_emissivity, absorptivity as leckner_absorptivity

@dataclass(frozen=True)
class WSGGResult:
    emissivity: float
    absorptivity: float
    kappa_eff: float
    optical_thickness: float
    path_length: float
    model_name: str = "wsgg"

# 透明气体 + 4 gray gases；权重为稳定的第一阶段占位系数。
DEFAULT_WEIGHTS = (0.20, 0.25, 0.30, 0.20)
DEFAULT_KAPPA_FACTORS = (0.20, 1.0, 4.0, 16.0)

def _emissivity(T: float, pCO2: float, pH2O: float, L: float) -> float:
    base_eps = leckner_emissivity(T, pCO2, pH2O, L)
    if base_eps <= 0.0:
        return 0.0
    tau_target = -math.log(max(1e-12, 1.0 - base_eps))

    def eps_at(scale):
        return sum(w * (1.0 - math.exp(-scale * factor))
                   for w, factor in zip(DEFAULT_WEIGHTS, DEFAULT_KAPPA_FACTORS))

    # Provisional shape and scale; coefficients are not HITEMP calibrated.
    scale = 0.85 * tau_target
    return max(0.0, min(0.999999, eps_at(scale)))


def evaluate(T_gas: float, T_wall: float, pCO2: float, pH2O: float, L: float, eps_wall: float = 0.85) -> WSGGResult:
    if T_gas <= 0 or T_wall <= 0 or L <= 0:
        raise ValueError("T、L 必须为正")
    eg = _emissivity(T_gas, pCO2, pH2O, L)
    wall_emissivity = _emissivity(T_wall, pCO2, pH2O, L)
    leckner_gas = leckner_emissivity(T_gas, pCO2, pH2O, L)
    if leckner_gas <= 0.0:
        alpha = 0.0
    else:
        # Provisional WSGG absorption closure: retain its own wall-temperature
        # gray-gas fraction and apply the species-scaled Hottel correction
        # relative to the Leckner reference spectrum.
        correction = leckner_absorptivity(
            T_gas, T_wall, pCO2, pH2O, L
        ) / leckner_gas
        alpha = max(0.0, min(0.999999, wall_emissivity * correction))
    tau = 0.0 if eg <= 0.0 else -math.log(1.0 - eg)
    return WSGGResult(eg, alpha, tau / L, tau, L)
