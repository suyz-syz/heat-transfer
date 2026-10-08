# -*- coding: utf-8 -*-
"""NASA Glenn 七项多项式 + 工程输运性质模型。

NASA 多项式：
    cp/R = a1 + a2*T + a3*T^2 + a4*T^3 + a5*T^4

NASA Glenn 数据库给出热力学性质；本模块的 mu、k 采用独立的
Sutherland 型组分相关式，再通过 Wilke/Mason-Saxena 型规则混合。
这一区分很重要：NASA polynomial 本身不是输运性质数据库。

有效温区：默认 300~2000 K；NASA 数据本身可覆盖更宽范围，但本项目
第一阶段只对窑炉目标温区提供显式检查。
"""
from __future__ import annotations
import math
from dataclasses import dataclass
from typing import Dict, Tuple
from ...gas import GasMixture, SPECIES_MOLAR_MASS, R_UNIVERSAL

# NASA-7, low/high ranges. Values are standard NASA Glenn polynomial coefficients.
NASA7: Dict[str, Tuple[Tuple[float, ...], Tuple[float, ...]]] = {
    "CO2": (
        (2.35677352, 8.98459677e-3, -7.12356269e-6, 2.45919022e-9, -1.43699548e-13),
        (4.63659493, 2.74131985e-3, -9.95828516e-7, 1.60373011e-10, -9.16103468e-15),
    ),
    "H2O": (
        (4.19864056, -2.03643410e-3, 6.52040211e-6, -5.48797062e-9, 1.77197817e-12),
        (3.03399249, 2.17691804e-3, -1.64072518e-7, -9.70419870e-11, 1.68200992e-14),
    ),
    "N2": (
        (3.53100528, -1.23660987e-4, -5.02999433e-7, 2.43530612e-9, -1.40881235e-12),
        (2.95257626, 1.39690040e-3, -4.92631603e-7, 7.86010367e-11, -4.60755321e-15),
    ),
    "O2": (
        (3.78245636, -2.99673416e-3, 9.84730201e-6, -9.68129509e-9, 3.24372837e-12),
        (3.28253784, 1.48308754e-3, -7.57966669e-7, 2.09470555e-10, -2.16717794e-14),
    ),
}
MW = SPECIES_MOLAR_MASS

# Sutherland-like engineering transport constants: reference mu at T0, S.
MU_REF = {"CO2": (1.48e-5, 300.0, 240.0), "H2O": (1.00e-5, 300.0, 350.0),
          "N2": (1.663e-5, 300.0, 111.0), "O2": (1.919e-5, 300.0, 127.0)}
K_REF = {"CO2": (0.0168, 300.0, 240.0), "H2O": (0.0181, 300.0, 350.0),
         "N2": (0.0259, 300.0, 111.0), "O2": (0.0263, 300.0, 127.0)}

@dataclass(frozen=True)
class SpeciesProperties:
    cp: float       # J/(kg K)
    mu: float       # Pa s
    k: float        # W/(m K)
    M: float        # kg/mol

@dataclass(frozen=True)
class GasProperties:
    T: float
    P: float
    rho: float
    cp: float
    mu: float
    k: float
    Pr: float
    M: float
    R: float

def _cp_molar(species: str, T: float) -> float:
    if T <= 0.0 or not math.isfinite(T):
        raise ValueError("T 必须为有限正温度")
    low, high = NASA7[species]
    a = low if T <= 1000.0 else high
    cp_r = a[0] + a[1]*T + a[2]*T**2 + a[3]*T**3 + a[4]*T**4
    return cp_r * R_UNIVERSAL

def _sutherland(T: float, params: Tuple[float, float, float]) -> float:
    mu0, T0, S = params
    return mu0 * (T / T0) ** 1.5 * (T0 + S) / (T + S)

def species_properties(species: str, T: float) -> SpeciesProperties:
    if species not in NASA7:
        raise KeyError(species)
    cp = _cp_molar(species, T) / MW[species]
    mu = _sutherland(T, MU_REF[species])
    k = _sutherland(T, K_REF[species])
    return SpeciesProperties(cp=cp, mu=mu, k=k, M=MW[species])

def _wilke_phi(mu_i: float, mu_j: float, M_i: float, M_j: float) -> float:
    return ((1.0 + math.sqrt(mu_i / mu_j) * (M_j / M_i) ** 0.25) ** 2
            / math.sqrt(8.0 * (1.0 + M_i / M_j)))

def _wilke(y: Dict[str, float], props: Dict[str, SpeciesProperties], attr: str) -> float:
    values = {s: getattr(props[s], attr) for s in y}
    total = 0.0
    for i, yi in y.items():
        denom = 0.0
        for j, yj in y.items():
            denom += yj * _wilke_phi(values[i], values[j], props[i].M, props[j].M)
        total += yi * values[i] / denom
    return total

def mixture_properties(T: float, P: float, gas: GasMixture) -> GasProperties:
    if not (300.0 <= T <= 2000.0):
        raise ValueError("第一阶段 NASA 物性模型要求 300 K <= T <= 2000 K")
    if P <= 0.0:
        raise ValueError("绝对压力必须为正")
    y = gas.as_dict()
    sp = {s: species_properties(s, T) for s in y}
    cp = sum(y[s] * sp[s].cp for s in y)
    mu = _wilke(y, sp, "mu")
    k = _wilke(y, sp, "k")
    M = gas.molecular_weight()
    R = gas.gas_constant()
    rho = P / (R * T)
    Pr = cp * mu / k
    return GasProperties(T=T, P=P, rho=rho, cp=cp, mu=mu, k=k, Pr=Pr, M=M, R=R)
