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
