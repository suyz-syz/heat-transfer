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
    *, partition_sums=None, wall_emissivity=1.0,
) -> List[LBLWSGGMapPoint]:
    """Compare supplied HITEMP/LBL line data against a fitted WSGG parameter set.

    weights/kappa must have been fitted for the relevant gas-state slice. This
    routine deliberately does not label synthetic or uncalibrated coefficients as
    HITEMP validated. Gas is treated as a uniform, isothermal, non-scattering slab.
    """
    from .models.radiation.hitemp_lbl import (
        absorption_spectrum, gas_emissivity_from_spectrum, spectral_net_radiative_flux,
    )
    from .models.radiation.wsgg_fit import wsgg_emissivity
    from .radiation import SIGMA

    if wall_temperature_K <= 0:
        raise ValueError("wall_temperature_K must be positive")
    out = []
    for temperature in temperatures_K:
        if temperature <= 0:
            raise ValueError("temperatures_K must be positive")
        for length in path_lengths_m:
            alpha = absorption_spectrum(
                lines, wavenumbers, temperature, pressure_atm, mole_fractions, length,
                partition_sums=partition_sums,
            )
            eps_lbl = gas_emissivity_from_spectrum(alpha, wavenumbers, temperature, length)
            eps_wsgg = wsgg_emissivity(weights, kappa, length)
            q_lbl = spectral_net_radiative_flux(
                alpha, wavenumbers, temperature, wall_temperature_K, length,
                wall_emissivity=wall_emissivity,
            )
            eps_exchange = (
                eps_wsgg * wall_emissivity
                / (eps_wsgg + wall_emissivity - eps_wsgg * wall_emissivity)
                if eps_wsgg + wall_emissivity - eps_wsgg * wall_emissivity > 0 else 0.0
            )
            q_wsgg = eps_exchange * SIGMA * (temperature**4 - wall_temperature_K**4)
            rel = 100.0 * (q_wsgg-q_lbl) / max(abs(q_lbl), 1e-30)
            out.append(LBLWSGGMapPoint(
                temperature, pressure_atm, length, eps_lbl, eps_wsgg,
                q_lbl, q_wsgg, rel
            ))
    return out



@dataclass(frozen=True)
class LBLWSGGConditionResult:
    temperature_K: float
    pressure_atm: float
    pCO2_atm: float
    pH2O_atm: float
    training_rmse_emissivity: float
    holdout_mean_abs_q_error_percent: float
    holdout_max_abs_q_error_percent: float
    holdout_max_abs_q_error_W_m2: float
    weights: tuple[float, ...]
    kappa_m_inv: tuple[float, ...]
    holdout_points: int


def run_lbl_wsgg_calibration_sweep(
    lines, wavenumbers, path_lengths_m, temperatures_K, pressures_atm,
    co2_mole_fractions, h2o_mole_fractions, wall_temperature_K,
    *, n_gases=4, partition_sums=None, wall_emissivity=1.0,
    kappa_min=1e-4, kappa_max=1e3, grid_size=180, iterations=5000,
) -> list[LBLWSGGConditionResult]:
    """Calibrate and hold out WSGG fits over T/P/CO2/H2O composition combinations.

    For each thermodynamic state, fit on alternating path-length samples and
    score only the held-out samples. Coefficients are state-specific and are NOT
    a single deployable WSGG correlation; a separate regression/model-selection
    step is required before production use. A broad, converged spectral grid and
    real, sourced line and partition-sum data are required for scientific claims.
    """
    from .models.radiation.hitemp_lbl import absorption_spectrum, spectral_net_radiative_flux
    from .models.radiation.wsgg_fit import fit_wsgg, wsgg_emissivity
    from .radiation import SIGMA

    if len(path_lengths_m) < max(2 * (n_gases + 1), 6):
        raise ValueError("need at least 2*(n_gases+1) path lengths for train/holdout split")
    if not 0 < wall_emissivity <= 1 or wall_temperature_K <= 0:
        raise ValueError("invalid wall emissivity or temperature")
    train_idx = [i for i in range(len(path_lengths_m)) if i % 2 == 0]
    test_idx = [i for i in range(len(path_lengths_m)) if i % 2 == 1]
    if len(train_idx) < n_gases + 1 or not test_idx:
        raise ValueError("insufficient training/holdout path lengths")

    out = []
    for temperature in temperatures_K:
        for pressure in pressures_atm:
            for xco2 in co2_mole_fractions:
                for xh2o in h2o_mole_fractions:
                    if temperature <= 0 or pressure <= 0 or xco2 < 0 or xh2o < 0 or xco2 + xh2o > 1:
                        raise ValueError("invalid T/P or mole fractions")
                    composition = {"CO2": xco2, "H2O": xh2o}
                    eps_lbls = []
                    q_lbls = []
                    for length in path_lengths_m:
                        alpha = absorption_spectrum(
                            lines, wavenumbers, temperature, pressure, composition, length,
                            partition_sums=partition_sums,
                        )
                        eps = gas_emissivity_from_spectrum(alpha, wavenumbers, temperature, length)
                        eps_lbls.append(eps)
                        q_lbls.append(spectral_net_radiative_flux(
                            alpha, wavenumbers, temperature, wall_temperature_K, length,
                            wall_emissivity=wall_emissivity,
                        ))
                    fit = fit_wsgg(
                        [path_lengths_m[i] for i in train_idx],
                        [eps_lbls[i] for i in train_idx],
                        n_gases=n_gases, kappa_min=kappa_min, kappa_max=kappa_max,
                        grid_size=grid_size, iterations=iterations,
                    )
                    abs_pct, abs_wm2 = [], []
                    for i in test_idx:
                        eps_fit = wsgg_emissivity(fit.weights, fit.kappa, path_lengths_m[i])
                        denom = eps_fit + wall_emissivity - eps_fit * wall_emissivity
                        eps_exchange = eps_fit * wall_emissivity / denom if denom > 0 else 0.0
                        q_fit = eps_exchange * SIGMA * (
                            temperature**4 - wall_temperature_K**4
                        )
                        abs_pct.append(100.0 * abs(q_fit - q_lbls[i]) / max(abs(q_lbls[i]), 1e-12))
                        abs_wm2.append(abs(q_fit - q_lbls[i]))
                    out.append(LBLWSGGConditionResult(
                        temperature, pressure, xco2*pressure, xh2o*pressure,
                        fit.rmse,
                        sum(abs_pct)/len(abs_pct), max(abs_pct), max(abs_wm2),
                        fit.weights, fit.kappa, len(test_idx),
                    ))
    return out
