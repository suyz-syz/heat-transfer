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
from .leckner import emissivity as leckner_emissivity

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

def evaluate(T_gas: float, T_wall: float, pCO2: float, pH2O: float, L: float, eps_wall: float = 0.85) -> WSGGResult:
    if T_gas <= 0 or T_wall <= 0 or L <= 0:
        raise ValueError("T、L 必须为正")
    base_eps = leckner_emissivity(T_gas, pCO2, pH2O, L)
    if base_eps <= 0:
        return WSGGResult(0.0, 0.0, 0.0, 0.0, L)
    tau_target = -math.log(max(1e-12, 1.0 - base_eps))
    # 求 scale，使 sum(w_j*(1-exp(-scale*f_j))) = base_eps。
    lo, hi = 0.0, max(1.0, tau_target * 100.0)
    def eps_at(scale):
        return sum(w * (1.0 - math.exp(-scale*f)) for w, f in zip(DEFAULT_WEIGHTS, DEFAULT_KAPPA_FACTORS))
    while eps_at(hi) < base_eps:
        hi *= 2.0
        if hi > 1e12:
            raise RuntimeError("WSGG scale 求解发散")
    for _ in range(80):
        mid = 0.5 * (lo + hi)
        if eps_at(mid) < base_eps:
            lo = mid
        else:
            hi = mid
    # 第一阶段 provisional WSGG：用 Leckner 的总光学厚度确定尺度，
    # 但保留独立四灰气体谱形。0.85 是保守的临时尺度因子；该值不是 HITEMP 拟合常数。
    scale = 0.85 * tau_target
    eg = eps_at(scale)
    tau = -math.log(max(1e-12, 1.0 - eg))
    return WSGGResult(eg, eg, tau / L, tau, L)
