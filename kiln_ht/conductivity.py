# -*- coding: utf-8 -*-
"""Temperature-dependent thermal conductivity models; SI conductivity units.

Polynomial compatibility mode uses degrees Celsius by default, matching legacy k_coef.
Tabulated mode uses absolute temperature in kelvin and piecewise-linear interpolation;
extrapolation is rejected rather than silently guessed.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Iterable, Sequence, Tuple


@dataclass(frozen=True)
class ConductivityModel:
    mode: str = "constant"
    value: float = 1.0
    coefficients: Tuple[float, float, float] = (1.0, 0.0, 0.0)
    temperature_unit: str = "degC"
    points: Tuple[Tuple[float, float], ...] = ()

    @classmethod
    def constant(cls, value: float) -> "ConductivityModel":
        return cls(mode="constant", value=float(value))

    @classmethod
    def polynomial(cls, coefficients: Sequence[float], temperature_unit: str = "degC") -> "ConductivityModel":
        if len(coefficients) != 3:
            raise ValueError("多项式必须包含 c0、c1、c2 三个系数")
        if temperature_unit not in ("degC", "K"):
            raise ValueError("temperature_unit 必须是 degC 或 K")
        return cls(mode="polynomial", coefficients=tuple(float(x) for x in coefficients),
                   temperature_unit=temperature_unit)

    @classmethod
    def table(cls, points: Iterable[Sequence[float]]) -> "ConductivityModel":
        normalized = tuple((float(p[0]), float(p[1])) for p in points)
        if len(normalized) < 2:
            raise ValueError("多点插值表至少需要两个点")
        if any(not math.isfinite(t) or not math.isfinite(k) for t, k in normalized):
            raise ValueError("插值表必须全部为有限数值")
        if any(normalized[i][0] >= normalized[i+1][0] for i in range(len(normalized)-1)):
            raise ValueError("插值表温度必须严格递增且不能重复")
        if any(k <= 0 for _, k in normalized):
            raise ValueError("插值表导热系数必须全部为正")
        return cls(mode="table", points=normalized)

    def conductivity(self, temperature_k: float) -> float:
        t_k = float(temperature_k)
        if not math.isfinite(t_k) or t_k <= 0:
            raise ValueError("温度必须是正的有限 K 值")
        if self.mode == "constant":
            result = self.value
        elif self.mode == "polynomial":
            t = t_k - 273.15 if self.temperature_unit == "degC" else t_k
            c0, c1, c2 = self.coefficients
            result = c0 + c1*t + c2*t*t
        elif self.mode == "table":
            if t_k < self.points[0][0] or t_k > self.points[-1][0]:
                raise ValueError(f"温度 {t_k:g} K 超出插值表范围 {self.points[0][0]:g}–{self.points[-1][0]:g} K；不允许静默外推")
            for (t0, k0), (t1, k1) in zip(self.points, self.points[1:]):
                if t_k <= t1:
                    f = (t_k-t0)/(t1-t0)
                    result = k0 + f*(k1-k0)
                    break
            else:
                result = self.points[-1][1]
        else:
            raise ValueError(f"不支持的导热系数模式: {self.mode}")
        if not math.isfinite(result) or result <= 0:
            raise ValueError(f"导热系数在 {t_k:g} K 下必须为正有限值")
        return result

    def integral_k(self, t0_k: float, t1_k: float) -> float:
        """Return integral of lambda(T) dT between Kelvin bounds (W/m)."""
        if t0_k == t1_k:
            return 0.0
        sign = 1.0
        if t1_k < t0_k:
            t0_k, t1_k, sign = t1_k, t0_k, -1.0
        if self.mode == "constant":
            self.conductivity(t0_k)
            self.conductivity(t1_k)
            return sign * self.value * (t1_k - t0_k)
        if self.mode == "polynomial":
            def primitive(tk):
                t = tk - 273.15 if self.temperature_unit == "degC" else tk
                a, b, c = self.coefficients
                return a*t + 0.5*b*t*t + (c/3.0)*t*t*t
            self.conductivity(t0_k)
            self.conductivity(t1_k)
            return sign * (primitive(t1_k) - primitive(t0_k))
        if self.mode == "table":
            if t0_k < self.points[0][0] or t1_k > self.points[-1][0]:
                raise ValueError("温度超出导热系数插值表范围；不允许静默外推")
            cursor = t0_k
            total = 0.0
            for (ta, ka), (tb, kb) in zip(self.points, self.points[1:]):
                lo, hi = max(cursor, ta), min(t1_k, tb)
                if hi <= lo:
                    continue
                def kval(t):
                    return ka + (kb-ka)*(t-ta)/(tb-ta)
                total += 0.5*(kval(lo)+kval(hi))*(hi-lo)
                cursor = hi
                if cursor >= t1_k:
                    break
            return sign * total
        raise ValueError(f"不支持的导热系数模式: {self.mode}")

    def mean_k(self, t0_k: float, t1_k: float) -> float:
        if t0_k == t1_k:
            return self.conductivity(t0_k)
        value = self.integral_k(t0_k, t1_k) / (t1_k - t0_k)
        if not math.isfinite(value) or value <= 0:
            raise ValueError("区间平均导热系数必须为正有限值")
        return value

    def as_dict(self) -> dict:
        if self.mode == "constant":
            return {"mode": "constant", "value": self.value}
        if self.mode == "polynomial":
            return {"mode": "polynomial", "temperature_unit": self.temperature_unit,
                    "coefficients": list(self.coefficients)}
        return {"mode": "table", "points": [list(p) for p in self.points]}
