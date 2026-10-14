#!/usr/bin/env python3
"""Offline LBL grid-convergence matrix for the 2000-2400 cm-1 trial band.

This evaluates only the narrow band with the committed HITEMP/TIPS inputs. The
spectral line model remains the existing pseudo-Voigt approximation. No result
from this script is a full-spectrum or production-solver validation.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.hitemp_calibration.hitemp_wsgg_calibration import (  # noqa: E402
    C2_CM_K,
    C_LIGHT,
    H_PLANCK,
    K_B,
    band_emissivity,
    lbl_spectrum,
    load_inputs,
)

BAND_CM_INV = (2000.0, 2400.0)
GAS_TEMPERATURES_K = (600.0, 1000.0, 1200.0, 1600.0, 2000.0, 2400.0)
PRESSURE_CASES_ATM = (0.3, 1.0, 3.0)
CO2_FRACTIONS = (0.0, 0.04, 0.12, 0.20)
H2O_FRACTIONS = (0.0, 0.02, 0.08, 0.15)
PATH_LENGTHS_M = tuple(float(v) for v in np.geomspace(0.05, 5.0, 7))
GRID_STEPS_CM_INV = (0.01, 0.005)
DEFAULT_THRESHOLDS = {
    "alpha_integral_relative": 0.005,
    "transmittance_max_absolute": 0.002,
    "band_emissivity_max_absolute": 0.0005,
    "black_wall_flux_max_relative": 0.005,
}


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def composition_matrix() -> list[tuple[float, float]]:
    """Independent CO2/H2O mole-fraction axes, including pure-species edges."""
    return [
        (co2, h2o)
        for co2 in CO2_FRACTIONS
        for h2o in H2O_FRACTIONS
        if co2 + h2o > 0.0 and co2 + h2o < 1.0
    ]


def matched_wall_temperatures(gas_temperature_K: float) -> tuple[float, ...]:
    """Three bounded gas/wall temperature ratios for the flux-proxy comparison."""
    return tuple(sorted({max(300.0, round(gas_temperature_K * ratio, 6))
                         for ratio in (0.50, 0.75, 0.90)}))


def _align_fine_to_coarse(coarse_wn, fine_wn, fine_values):
    coarse_step = float(coarse_wn[1] - coarse_wn[0])
    fine_step = float(fine_wn[1] - fine_wn[0])
    factor = coarse_step / fine_step
    rounded = int(round(factor))
    if rounded < 2 or not math.isclose(factor, rounded, rel_tol=0.0, abs_tol=1e-9):
        raise ValueError("grid steps must be aligned integer refinements")
    aligned = fine_values[::rounded]
    if aligned.size != coarse_wn.size or not np.allclose(
        fine_wn[::rounded], coarse_wn, rtol=0.0, atol=1e-9
    ):
        raise ValueError("coarse and fine grids do not share aligned band endpoints")
    return aligned


def _planck_exitance_per_cm(wn_cm_inv, temperature_K):
    """Blackbody spectral exitance per cm^-1; used only for a convergence proxy."""
    wn_m_inv = 100.0 * np.asarray(wn_cm_inv, dtype=float)
    z = H_PLANCK * C_LIGHT * wn_m_inv / (K_B * temperature_K)
    return (
        2.0 * math.pi * H_PLANCK * C_LIGHT**2 * wn_m_inv**3
        / np.expm1(z) * 100.0
    )


def black_wall_band_flux_proxy(wn, alpha_m_inv, gas_temperature_K, wall_temperature_K, path_m):
    """Band-limited black-wall exchange proxy using LBL absorptance.

    q = integral[(1-exp(-alpha L)) * (E_b(Tg)-E_b(Tw)) d(wn)].
    This metric compares numerical grids only; it is not a kiln boundary model.
    """
    absorptance = -np.expm1(-np.asarray(alpha_m_inv, dtype=float) * path_m)
    spectral_difference = (
        _planck_exitance_per_cm(wn, gas_temperature_K)
        - _planck_exitance_per_cm(wn, wall_temperature_K)
    )
    return float(np.trapezoid(absorptance * spectral_difference, wn))


def compare_grids(coarse, fine, temperature_K, wall_temperatures_K, path_lengths_m):
    wn_c, alpha_c = coarse
    wn_f, alpha_f = fine
    alpha_f_at_c = _align_fine_to_coarse(wn_c, wn_f, alpha_f)

    alpha_denominator = max(float(np.trapezoid(np.abs(alpha_f_at_c), wn_c)), 1e-30)
    alpha_l1_relative = float(
        np.trapezoid(np.abs(alpha_c - alpha_f_at_c), wn_c) / alpha_denominator
    )
    alpha_max_abs = float(np.max(np.abs(alpha_c - alpha_f_at_c)))

    tau_errors = []
    emissivity_errors = []
    emissivity_relative_errors = []
    flux_relative_errors = []
    for path_m in path_lengths_m:
        tau_c = np.exp(-alpha_c * path_m)
        tau_f = np.exp(-alpha_f_at_c * path_m)
        tau_errors.append(np.abs(tau_c - tau_f))

        eps_c = band_emissivity(wn_c, alpha_c, temperature_K, path_m)
        eps_f = band_emissivity(wn_f, alpha_f, temperature_K, path_m)
        emissivity_errors.append(abs(eps_c - eps_f))
        emissivity_relative_errors.append(abs(eps_c - eps_f) / max(abs(eps_f), 1e-12))

        for wall_temperature_K in wall_temperatures_K:
            flux_c = black_wall_band_flux_proxy(
                wn_c, alpha_c, temperature_K, wall_temperature_K, path_m
            )
            flux_f = black_wall_band_flux_proxy(
                wn_f, alpha_f, temperature_K, wall_temperature_K, path_m
            )
            flux_relative_errors.append(
                abs(flux_c - flux_f) / max(abs(flux_f), 1.0)
            )

    return {
        "alpha_integral_relative": alpha_l1_relative,
        "alpha_max_absolute_m_inv": alpha_max_abs,
        "transmittance_max_absolute": float(max(float(np.max(e)) for e in tau_errors)),
        "transmittance_mean_absolute": float(
            np.mean([float(np.mean(e)) for e in tau_errors])
        ),
        "band_emissivity_max_absolute": max(emissivity_errors),
        "band_emissivity_max_relative": max(emissivity_relative_errors, default=0.0),
        "black_wall_flux_max_relative": max(flux_relative_errors, default=0.0),
    }


def run_matrix(
    line_csv: Path,
    tips_csv: Path,
    *,
    coarse_step: float = GRID_STEPS_CM_INV[0],
    fine_step: float = GRID_STEPS_CM_INV[1],
    quick: bool = False,
) -> dict:
    if not (math.isfinite(coarse_step) and math.isfinite(fine_step)
            and coarse_step > fine_step > 0):
        raise ValueError("require finite grid steps with coarse_step > fine_step > 0")
    lines, tips_map = load_inputs(line_csv, tips_csv)
    temperatures = (600.0, 1200.0, 2400.0) if quick else GAS_TEMPERATURES_K
    pressures = (1.0,) if quick else PRESSURE_CASES_ATM
    compositions = ((0.12, 0.08), (0.20, 0.0), (0.0, 0.15)) if quick else composition_matrix()
    paths = PATH_LENGTHS_M[::3] if quick else PATH_LENGTHS_M
    cases = []
    for temperature in temperatures:
        wall_temperatures = matched_wall_temperatures(temperature)
        for pressure in pressures:
            for x_co2, x_h2o in compositions:
                coarse = lbl_spectrum(
                    lines, tips_map, temperature, pressure, x_co2, x_h2o,
                    step=coarse_step,
                )
                fine = lbl_spectrum(
                    lines, tips_map, temperature, pressure, x_co2, x_h2o,
                    step=fine_step,
                )
                metrics = compare_grids(
                    coarse, fine, temperature, wall_temperatures, paths
                )
                cases.append({
                    "gas_temperature_K": temperature,
                    "wall_temperatures_K": list(wall_temperatures),
                    "pressure_atm": pressure,
                    "partial_pressures_atm": {
                        "CO2": x_co2 * pressure, "H2O": x_h2o * pressure,
                    },
                    "mole_fractions": {"CO2": x_co2, "H2O": x_h2o},
                    "path_lengths_m": list(paths),
                    "metrics": metrics,
                    "passed": (
                        metrics["alpha_integral_relative"] <= DEFAULT_THRESHOLDS["alpha_integral_relative"]
                        and metrics["transmittance_max_absolute"] <= DEFAULT_THRESHOLDS["transmittance_max_absolute"]
                        and metrics["band_emissivity_max_absolute"] <= DEFAULT_THRESHOLDS["band_emissivity_max_absolute"]
                        and metrics["black_wall_flux_max_relative"] <= DEFAULT_THRESHOLDS["black_wall_flux_max_relative"]
                    ),
                })

    metric_names = tuple(DEFAULT_THRESHOLDS)
    maxima = {
        name: max(case["metrics"][name] for case in cases)
        for name in metric_names
    }
    all_passed = all(case["passed"] for case in cases)
    return {
        "report_type": "offline HITEMP/TIPS narrow-band LBL grid-convergence assessment",
        "status": "pass" if all_passed else "review_required",
        "scope": {
            "band_cm-1": list(BAND_CM_INV),
            "line_center_filter_cm-1": [1975.0, 2425.0],
            "reference_model": "pseudo-Voigt LBL; not independently validated spectroscopy",
            "scope_warning": "Results apply only to this narrow band and committed sample, not total spectrum or industrial release.",
            "production_solver_changed": False,
            "provisional_label_changed": False,
        },
        "inputs": {
            "line_csv": str(line_csv),
            "line_csv_sha256": sha256_file(line_csv),
            "tips_csv": str(tips_csv),
            "tips_csv_sha256": sha256_file(tips_csv),
            "filtered_line_count": int(len(lines)),
            "observed_line_wavenumber_cm-1": [
                float(lines["nu"].min()), float(lines["nu"].max())
            ],
        },
        "grid_comparison": {
            "coarse_step_cm-1": coarse_step,
            "fine_step_cm-1": fine_step,
            "grid_points": {
                "coarse": int(round((BAND_CM_INV[1] - BAND_CM_INV[0]) / coarse_step)) + 1,
                "fine": int(round((BAND_CM_INV[1] - BAND_CM_INV[0]) / fine_step)) + 1,
            },
            "thresholds": DEFAULT_THRESHOLDS,
            "worst_case_metrics": maxima,
        },
        "matrix": {
            "gas_temperatures_K": list(temperatures),
            "wall_temperature_ratios": [0.50, 0.75, 0.90],
            "pressures_atm": list(pressures),
            "composition_count": len(compositions),
            "compositions_mole_fraction_CO2_H2O": [
                {"CO2": co2, "H2O": h2o} for co2, h2o in compositions
            ],
            "path_lengths_m": list(paths),
            "case_count": len(cases),
        },
        "cases": cases,
        "limitations": [
            "Grid convergence is numerical verification against the same pseudo-Voigt LBL formulation, not independent physical validation.",
            "The black-wall flux field is only a narrow-band comparison proxy.",
            "No conclusion is made about spectral ranges outside 2000-2400 cm-1.",
            "The WSGG model remains provisional and the production Leckner path is unchanged.",
        ],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--line-csv", type=Path, default=ROOT / "data/hitemp_co2_h2o_1000_4000_sample.csv")
    parser.add_argument("--tips-csv", type=Path, default=ROOT / "data/tips_partition_sums_296_2400.csv")
    parser.add_argument("--output", type=Path, default=ROOT / "reports/hitemp_grid_convergence.json")
    parser.add_argument("--coarse-step", type=float, default=GRID_STEPS_CM_INV[0])
    parser.add_argument("--fine-step", type=float, default=GRID_STEPS_CM_INV[1])
    parser.add_argument("--quick", action="store_true", help="small smoke matrix, not the full reference matrix")
    args = parser.parse_args()
    report = run_matrix(
        args.line_csv, args.tips_csv, coarse_step=args.coarse_step,
        fine_step=args.fine_step, quick=args.quick,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "status": report["status"],
        "case_count": report["matrix"]["case_count"],
        "grid_comparison": report["grid_comparison"],
        "output": str(args.output),
    }, indent=2))
    if report["status"] != "pass":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
