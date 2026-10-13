# -*- coding: utf-8 -*-
"""Leckner/Hottel 型 CO2-H2O 灰气体工程模型。

pCO2、pH2O 输入为 Pa；内部转换为 bar·m 的 pL。
该模型用于兼容旧 Baseline 与回归校核，不宣称为 HITEMP/LBL 高精度模型。
"""
from __future__ import annotations
import math
from dataclasses import dataclass

@dataclass(frozen=True)
class LecknerResult:
    emissivity: float
    absorptivity: float
    kappa_eff: float
    optical_thickness: float
    path_length: float
    model_name: str = "leckner"


def _components(T: float, pCO2: float, pH2O: float, L: float):
    """Return the Leckner CO2/H2O terms and spectral-overlap correction."""
    if T <= 0 or L <= 0 or pCO2 < 0 or pH2O < 0:
        raise ValueError("T、L 必须为正，分压不能为负")
    pLco2 = pCO2 / 1.0e5 * L
    pLh2o = pH2O / 1.0e5 * L
    if pLco2 + pLh2o <= 0:
        return 0.0, 0.0, 0.0
    Td = max(T, 500.0) / 1000.0
    ec = 0.2257 * Td**-1.5 * max(pLco2, 1e-12)**0.4 / (1 + 0.2757 * Td**-0.5 * max(pLco2, 1e-12)**0.5)
    eh = 0.569 * Td**-0.5 * max(pLh2o, 1e-12)**0.3 / (1 + 0.569 * Td**-0.5 * max(pLh2o, 1e-12)**0.5)
    de = 0.0089 * Td**-1.5 * (pLco2 + pLh2o)**0.5 / (1 + 0.0089 * Td**-1.5 * (pLco2 + pLh2o)**0.5)
    return ec, eh, de


def emissivity(T: float, pCO2: float, pH2O: float, L: float) -> float:
    ec, eh, de = _components(T, pCO2, pH2O, L)
    return max(0.0, min(0.999999, ec + eh - de))


def absorptivity(T_gas: float, T_wall: float, pCO2: float, pH2O: float, L: float) -> float:
    """Hottel-style wall-temperature absorptivity with species exponents.

    The CO2 and H2O bands are temperature-scaled independently (0.65 and
    0.45 respectively). Their overlap correction uses the geometric-mean
    exponent. Clipping preserves a physically admissible gray-gas fraction.
    """
    if T_gas <= 0 or T_wall <= 0:
        raise ValueError("T_gas、T_wall 必须为正")
    ec, eh, overlap = _components(T_wall, pCO2, pH2O, L)
    if ec == 0.0 and eh == 0.0:
        return 0.0
    ratio = T_gas / T_wall
    co2_abs = ec * ratio**0.65
    h2o_abs = eh * ratio**0.45
    overlap_abs = overlap * ratio**0.55
    return max(0.0, min(0.999999, co2_abs + h2o_abs - overlap_abs))
def evaluate(T_gas: float, T_wall: float, pCO2: float, pH2O: float, L: float, eps_wall: float = 0.85) -> LecknerResult:
    eg = emissivity(T_gas, pCO2, pH2O, L)
    alpha = absorptivity(T_gas, T_wall, pCO2, pH2O, L)
    tau = 0.0 if eg <= 0.0 else -math.log(1.0 - eg)
    kappa = tau / L
    return LecknerResult(eg, alpha, kappa, tau, L)
