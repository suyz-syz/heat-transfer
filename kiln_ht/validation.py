# -*- coding: utf-8 -*-
"""Baseline/新物理模型的可重复 Benchmark 接口。"""
from __future__ import annotations
from dataclasses import dataclass, asdict
from typing import List, Dict, Any
from .radiation import get_gas_radiation
from .gas import GasMixture, DEFAULT_GAS

@dataclass(frozen=True)
class RadiationBenchmarkCase:
    name: str
    T_gas: float
    T_wall: float
    P_bar: float
    pCO2_y: float
    pH2O_y: float
    beam_m: float

@dataclass(frozen=True)
class RadiationBenchmarkResult:
    case: str
    q_rad_leckner: float
    q_rad_wsgg: float
    delta_q_percent: float
    eps_leckner: float
    eps_wsgg: float

def default_benchmark_cases() -> List[RadiationBenchmarkCase]:
    return [
        RadiationBenchmarkCase("low", 800.0, 500.0, 1.01325, 0.18, 0.10, 3.8),
        RadiationBenchmarkCase("mid", 1200.0, 750.0, 1.01325, 0.18, 0.10, 3.8),
        RadiationBenchmarkCase("kiln", 1523.15, 900.0, 1.01325, 0.20, 0.08, 3.8),
        RadiationBenchmarkCase("high", 1800.0, 1100.0, 1.01325, 0.16, 0.12, 3.8),
    ]

def run_radiation_benchmark(cases=None) -> List[RadiationBenchmarkResult]:
    out = []
    for c in cases or default_benchmark_cases():
        P = c.P_bar * 1.0e5
        r0 = get_gas_radiation(c.T_gas, c.T_wall, c.pCO2_y*P, c.pH2O_y*P, c.beam_m, model="leckner")
        r1 = get_gas_radiation(c.T_gas, c.T_wall, c.pCO2_y*P, c.pH2O_y*P, c.beam_m, model="wsgg")
        dq = 100.0 * (r1.q_rad-r0.q_rad) / max(abs(r0.q_rad), 1e-30)
        out.append(RadiationBenchmarkResult(c.name, r0.q_rad, r1.q_rad, dq, r0.emissivity, r1.emissivity))
    return out

def benchmark_table(cases=None) -> List[Dict[str, Any]]:
    return [asdict(x) for x in run_radiation_benchmark(cases)]

from .calc import KilnParams, Layer, solve_wall

@dataclass(frozen=True)
class WallBenchmarkResult:
    case: str
    Q_air_leckner: float
    Tw_air_leckner: float
    Q_mix_wsgg: float
    Tw_mix_wsgg: float
    delta_Q_percent: float
    delta_Tw_K: float

def run_wall_benchmark(cases=None) -> List[WallBenchmarkResult]:
    layers = [Layer("fiber", 0.150, k=0.10), Layer("brick", 0.100, k=0.30),
              Layer("shell", 0.012, k=45.0)]
    out = []
    for c in cases or default_benchmark_cases():
        old = KilnParams(T_gas=c.T_gas, P_total=c.P_bar, CO2=c.pCO2_y, H2O=c.pH2O_y,
                         N2=1.0-c.pCO2_y-c.pH2O_y, O2=0.0,
                         radiation_model="leckner", property_model="air")
        new = KilnParams(T_gas=c.T_gas, P_total=c.P_bar, CO2=c.pCO2_y, H2O=c.pH2O_y,
                         N2=max(0.0, 1.0-c.pCO2_y-c.pH2O_y-0.03), O2=0.03,
                         radiation_model="wsgg", property_model="mixture")
        a = solve_wall(layers, old)
        b = solve_wall(layers, new)
        out.append(WallBenchmarkResult(c.name, a.Qprime, a.T_w1, b.Qprime, b.T_w1,
                    100.0*(b.Qprime-a.Qprime)/max(abs(a.Qprime),1e-30), b.T_w1-a.T_w1))
    return out


@dataclass(frozen=True)
class LBLWSGGMapPoint:
    temperature_K: float
    pressure_atm: float
    path_length_m: float
    emissivity_lbl: float
    emissivity_wsgg: float
    q_rad_lbl_W_m2: float
    q_rad_wsgg_W_m2: float
    relative_q_error_percent: float


def run_lbl_wsgg_error_map(
    lines, wavenumbers, path_lengths_m, temperatures_K, pressure_atm,
    mole_fractions, wall_temperature_K, weights, kappa,
) -> List[LBLWSGGMapPoint]:
    """Compare supplied HITEMP/LBL line data against a fitted WSGG parameter set.

    weights/kappa must have been fitted for the relevant gas-state slice. This
    routine deliberately does not label synthetic or uncalibrated coefficients as
    HITEMP validated. Gas is treated as a uniform, isothermal, non-scattering slab.
    """
    from .models.radiation.hitemp_lbl import absorption_spectrum, gas_emissivity_from_spectrum
    from .models.radiation.wsgg_fit import wsgg_emissivity
    from .radiation import SIGMA_SB

    if wall_temperature_K <= 0:
        raise ValueError("wall_temperature_K must be positive")
    out = []
    for temperature in temperatures_K:
        if temperature <= 0:
            raise ValueError("temperatures_K must be positive")
        for length in path_lengths_m:
            alpha = absorption_spectrum(
                lines, wavenumbers, temperature, pressure_atm, mole_fractions, length
            )
            eps_lbl = gas_emissivity_from_spectrum(alpha, wavenumbers, temperature, length)
            eps_wsgg = wsgg_emissivity(weights, kappa, length)
            blackbody_delta = SIGMA_SB * (temperature**4 - wall_temperature_K**4)
            q_lbl = eps_lbl * blackbody_delta
            q_wsgg = eps_wsgg * blackbody_delta
            rel = 100.0 * (q_wsgg-q_lbl) / max(abs(q_lbl), 1e-30)
            out.append(LBLWSGGMapPoint(
                temperature, pressure_atm, length, eps_lbl, eps_wsgg,
                q_lbl, q_wsgg, rel
            ))
    return out
