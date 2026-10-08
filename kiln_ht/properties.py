# -*- coding: utf-8 -*-
"""窑炉烟气物性统一入口。"""
from .gas import GasMixture, DEFAULT_GAS
from .models.properties.nasa import GasProperties, mixture_properties

def get_gas_properties(T: float, P: float, gas: GasMixture | None = None) -> GasProperties:
    """返回混合烟气 rho/cp/mu/k/Pr；P 单位 Pa，T 单位 K。"""
    return mixture_properties(T, P, gas or DEFAULT_GAS)
