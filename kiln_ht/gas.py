# -*- coding: utf-8 -*-
"""窑内烟气组分与混合气体基础数据链。

单位约定：
- 摩尔分数 y_i：1
- 质量分数 w_i：1
- 压力 P：Pa
- 温度 T：K
- 摩尔质量 M：kg/mol
- 混合气体常数 R_mix：J/(kg·K)

物理关系：
    p_i = y_i P
    M_mix = sum(y_i M_i)
    R_mix = R_u / M_mix
    rho = P / (R_mix T)

本模块只负责“组成/分压/平均分子量”，不负责 cp、mu、k。
"""
from __future__ import annotations
from dataclasses import dataclass
from typing import Dict, Mapping
import math

R_UNIVERSAL = 8.31446261815324  # J/(mol K)

SPECIES_MOLAR_MASS = {
    "CO2": 44.0095e-3,
    "H2O": 18.01528e-3,
    "N2": 28.0134e-3,
    "O2": 31.9988e-3,
}


@dataclass(frozen=True)
class GasMixture:
    """CO2/H2O/N2/O2 理想气体混合物。

    输入可采用摩尔分数或质量分数；内部统一保存摩尔分数。
    """
    CO2: float
    H2O: float
    N2: float
    O2: float

    def __post_init__(self) -> None:
        ys = [self.CO2, self.H2O, self.N2, self.O2]
        if any((not isinstance(v, (int, float)) or not math.isfinite(v) or v < 0.0) for v in ys):
            raise ValueError("气体组分分数必须为有限非负数")
        total = sum(ys)
        if not total > 0.0:
            raise ValueError("气体组分总和必须大于 0")
        if abs(total - 1.0) > 1.0e-8:
            raise ValueError(f"摩尔分数总和必须为 1，当前为 {total:.12g}")

    @classmethod
    def from_mole_fractions(cls, values: Mapping[str, float], normalize: bool = False) -> "GasMixture":
        v = {s: float(values.get(s, 0.0)) for s in SPECIES_MOLAR_MASS}
        total = sum(v.values())
        if normalize:
            if total <= 0.0:
                raise ValueError("组分总和必须大于 0")
            v = {s: x / total for s, x in v.items()}
        return cls(**v)

    @classmethod
    def from_mass_fractions(cls, values: Mapping[str, float], normalize: bool = False) -> "GasMixture":
        ws = {s: float(values.get(s, 0.0)) for s in SPECIES_MOLAR_MASS}
        if any(x < 0.0 for x in ws.values()):
            raise ValueError("质量分数不能为负")
        total = sum(ws.values())
        if normalize:
            if total <= 0.0:
                raise ValueError("质量分数总和必须大于 0")
            ws = {s: x / total for s, x in ws.items()}
            total = 1.0
        if abs(total - 1.0) > 1.0e-8:
            raise ValueError(f"质量分数总和必须为 1，当前为 {total:.12g}")
        denom = sum(ws[s] / SPECIES_MOLAR_MASS[s] for s in ws)
        ys = {s: (ws[s] / SPECIES_MOLAR_MASS[s]) / denom for s in ws}
        return cls(**ys)

    def as_dict(self) -> Dict[str, float]:
        return {"CO2": self.CO2, "H2O": self.H2O, "N2": self.N2, "O2": self.O2}

    def molecular_weight(self) -> float:
        return sum(self.as_dict()[s] * SPECIES_MOLAR_MASS[s] for s in SPECIES_MOLAR_MASS)

    def gas_constant(self) -> float:
        return R_UNIVERSAL / self.molecular_weight()

    def partial_pressures(self, P_pa: float) -> Dict[str, float]:
        if P_pa <= 0.0:
            raise ValueError("绝对压力必须为正")
        return {s: y * P_pa for s, y in self.as_dict().items()}

    def density(self, T_k: float, P_pa: float) -> float:
        if T_k <= 0.0 or P_pa <= 0.0:
            raise ValueError("温度和压力必须为正")
        return P_pa / (self.gas_constant() * T_k)


def gas_fractions_for_mode(co2: float, h2o: float, mode: str = "combustion") -> Dict[str, float]:
    """Return normalized kiln gas mole fractions for the selected operating mode.

    Combustion mode treats CO2/H2O as the user inputs and distributes the
    remaining fraction using the legacy N2:O2 ratio (0.69:0.03). Hot-air mode
    uses dry air and ignores CO2/H2O inputs.
    """
    mode = str(mode).lower()
    if mode == "hot_air":
        return {"CO2": 0.0, "H2O": 0.0, "N2": 0.79, "O2": 0.21}
    if mode != "combustion":
        raise ValueError("气相模式必须为 combustion 或 hot_air")

    co2, h2o = float(co2), float(h2o)
    if (
        not math.isfinite(co2) or not math.isfinite(h2o)
        or co2 < 0.0 or h2o < 0.0
        or co2 >= 1.0 or h2o >= 1.0
    ):
        raise ValueError("CO2/H2O 摩尔分数必须是 [0, 1) 内的有限值")
    remaining = 1.0 - co2 - h2o
    if remaining < -1.0e-12:
        raise ValueError("CO2 与 H2O 摩尔分数之和不能超过 1")
    remaining = max(0.0, remaining)
    residual_total = 0.69 + 0.03
    return {
        "CO2": co2,
        "H2O": h2o,
        "N2": remaining * 0.69 / residual_total,
        "O2": remaining * 0.03 / residual_total,
    }


DEFAULT_GAS = GasMixture(CO2=0.20, H2O=0.08, N2=0.69, O2=0.03)
