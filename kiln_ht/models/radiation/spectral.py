# -*- coding: utf-8 -*-
"""光谱吸收系数接口，为后续 HITEMP/LBL 模型预留。"""
from __future__ import annotations
from typing import Protocol

class SpectralAbsorptionModel(Protocol):
    def absorption_coefficient(self, wavelength_m: float, T: float, pCO2: float, pH2O: float) -> float:
        """返回谱吸收系数 k_lambda，单位 1/m。"""
        ...
