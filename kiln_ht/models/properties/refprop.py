# -*- coding: utf-8 -*-
"""REFPROP 扩展接口占位。

运行核心不依赖 REFPROP。未来接入时实现：
    evaluate(T, P, GasMixture) -> GasProperties
并保持与 properties.get_gas_properties() 相同的返回结构。
"""
class RefpropUnavailableError(RuntimeError):
    pass

def evaluate(*args, **kwargs):
    raise RefpropUnavailableError("REFPROP provider 尚未启用；第一阶段默认使用 NASA + 工程输运相关式")
