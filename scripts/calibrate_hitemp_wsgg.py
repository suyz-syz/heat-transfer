#!/usr/bin/env python3
"""Calibrate WSGG N=3,4,5 against imported HITEMP/TIPS LBL spectra.

This creates a source-tracked, band-limited report. It does not claim total-spectrum
or metrology-grade validation: the current LBL reference uses pseudo-Voigt profiles.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path

from kiln_ht.models.radiation.hitemp_lbl import (
    absorption_spectrum,
    gas_emissivity_from_spectrum,
    load_hitemp_csv,
)
from kiln_ht.models.radiation.wsgg_fit import fit_wsgg, wsgg_emissivity


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_tips(path: Path) -> dict[str, list[tuple[float, float]]]:
    import csv

    tables: dict[str, list[tuple[float, float]]] = {}
    with path.open(newline="", encoding="utf-8-sig") as stream:
        reader = csv.DictReader(stream)
        required = {"molecule", "isotope", "temperature_K", "Q"}
        if not required.issubset(reader.fieldnames or []):
            raise ValueError("TIPS CSV must contain molecule,isotope,temperature_K,Q")
        for row in reader:
            molecule = row["molecule"].strip().upper()
            isotope = row["isotope"].strip()
            key = f"{molecule}:{isotope}" if isotope else molecule
            temperature, q_value = float(row["temperature_K"]), float(row["Q"])
            if not (math.isfinite(temperature) and math.isfinite(q_value)
                    and temperature > 0 and q_value > 0):
                raise ValueError(f"invalid TIPS value for {key}")
            tables.setdefault(key, []).append((temperature, q_value))
    if not tables:
        raise ValueError("TIPS CSV contains no partition-sum data")
    return tables


def run_calibration(
    line_csv: Path,
    tips_csv: Path,
    output: Path,
    *,
    release: str,
    wn_min_cm: float = 2000.0,
    wn_max_cm: float = 2400.0,
    wn_step_cm: float = 0.5,
    temperatures_k: tuple[float, ...] = (800.0, 1200.0, 1600.0),
    pressure_atm: float = 1.0,
    co2_mole_fraction: float = 0.12,
    h2o_mole_fraction: float = 0.08,
    path_min_m: float = 0.05,
    path_max_m: float = 5.0,
    path_count: int = 20,
    fit_grid_size: int = 80,
    fit_iterations: int = 1000,
) -> dict:
    if not line_csv.is_file() or not tips_csv.is_file():
        raise FileNotFoundError("both normalized HITEMP line CSV and TIPS CSV must exist")
    if not release.strip():
        raise ValueError("release/version provenance is required")
    if not (math.isfinite(wn_min_cm) and math.isfinite(wn_max_cm)
            and math.isfinite(wn_step_cm) and wn_min_cm > 0
            and wn_max_cm > wn_min_cm and wn_step_cm > 0):
        raise ValueError("invalid wavenumber grid")
    if not (math.isfinite(pressure_atm) and pressure_atm > 0):
        raise ValueError("pressure_atm must be positive")
    if not (0 < co2_mole_fraction < 1 and 0 < h2o_mole_fraction < 1
            and co2_mole_fraction + h2o_mole_fraction < 1):
        raise ValueError("CO2/H2O fractions must be positive and sum to less than one")
    if path_count < 6 or path_min_m <= 0 or path_max_m <= path_min_m:
        raise ValueError("path_count must be >=6 and path bounds positive/increasing")
    if any(not math.isfinite(t) or t <= 0 for t in temperatures_k):
        raise ValueError("temperatures must be finite and positive")

    lines = load_hitemp_csv(line_csv)
    tips = load_tips(tips_csv)
    isotope_keys = {
        f"{line.molecule.upper()}:{line.isotope}" if line.isotope else line.molecule.upper()
        for line in lines if line.molecule.upper() in ("CO2", "H2O")
    }
    missing = sorted(key for key in isotope_keys if key not in tips)
    if missing:
        raise ValueError("missing TIPS partition sums for: " + ", ".join(missing))

    count = int(math.floor((wn_max_cm - wn_min_cm) / wn_step_cm + 1e-9)) + 1
    wavenumbers = [wn_min_cm + i * wn_step_cm for i in range(count)]
    path_lengths = [
        math.exp(math.log(path_min_m) + i * math.log(path_max_m / path_min_m) / (path_count - 1))
        for i in range(path_count)
    ]
    mole_fractions = {"CO2": co2_mole_fraction, "H2O": h2o_mole_fraction}
    results = []
    for temperature in temperatures_k:
        alpha = absorption_spectrum(
            lines, wavenumbers, temperature, pressure_atm, mole_fractions,
            path_lengths[-1], partition_sums=tips,
        )
        targets = [
            gas_emissivity_from_spectrum(alpha, wavenumbers, temperature, path)
            for path in path_lengths
        ]
        fits = {}
        for n_gases in (3, 4, 5):
            fitted = fit_wsgg(
                path_lengths, targets, n_gases=n_gases, grid_size=fit_grid_size,
                iterations=fit_iterations,
            )
            predictions = [
                wsgg_emissivity(fitted.weights, fitted.kappa, path)
                for path in path_lengths
            ]
            errors = [pred - target for pred, target in zip(predictions, targets)]
            fits[str(n_gases)] = {
                "weights": list(fitted.weights),
                "kappa_per_m": list(fitted.kappa),
                "fit_rmse_band_emissivity": fitted.rmse,
                "fit_max_abs_error_band_emissivity": fitted.max_abs_error,
                "sample_count": fitted.samples,
                "closure_sum_weights": sum(fitted.weights),
                "holdout": {
                    "performed": False,
                    "reason": "no independent holdout; metrics below are in-sample",
                    "in_sample_rmse": math.sqrt(sum(e * e for e in errors) / len(errors)),
                    "in_sample_max_abs_error": max(abs(e) for e in errors),
                },
            }
        results.append({
            "temperature_K": temperature,
            "pressure_atm": pressure_atm,
            "composition_mole_fraction": mole_fractions,
            "target_band_emissivity": targets,
            "fits_by_n_gray_gases": fits,
        })

    report = {
        "report_type": "HITEMP/TIPS-derived LBL band-emissivity WSGG calibration",
        "status": "source-derived calibration; requires independent validation before engineering release",
        "provenance": {
            "release": release,
            "line_csv": str(line_csv),
            "line_csv_sha256": sha256_file(line_csv),
            "tips_csv": str(tips_csv),
            "tips_csv_sha256": sha256_file(tips_csv),
            "line_count": len(lines),
            "tips_isotopologue_keys": sorted(tips),
        },
        "spectral_grid_cm-1": {
            "minimum": wn_min_cm,
            "maximum": wavenumbers[-1],
            "step": wn_step_cm,
            "point_count": len(wavenumbers),
        },
        "path_lengths_m": path_lengths,
        "temperature_cases_K": list(temperatures_k),
        "results": results,
        "limitations": [
            "Fits are for the stated spectral band only, not total-spectrum emissivity.",
            "The LBL engine currently uses a pseudo-Voigt profile, not a validated Hartmann-Tran profile.",
            "The fitted coefficients are condition-specific; this report does not regress a global T/composition/pressure correlation.",
            "Fit metrics are in-sample and are not independent experimental validation.",
            "Verify line-list edition, isotopologue completeness, pressure broadening and spectral-grid convergence before use.",
        ],
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--line-csv", required=True, type=Path,
                        help="normalized CSV generated by prepare_hitemp_benchmark.py")
    parser.add_argument("--tips-csv", required=True, type=Path,
                        help="TIPS partition sums CSV generated by prepare_hitemp_benchmark.py")
    parser.add_argument("--release", required=True, help="exact HITEMP/TIPS release provenance")
    parser.add_argument("--output", type=Path, default=Path("reports/hitemp_wsgg_calibration.json"))
    parser.add_argument("--wn-min", type=float, default=2000.0)
    parser.add_argument("--wn-max", type=float, default=2400.0)
    parser.add_argument("--wn-step", type=float, default=0.5)
    parser.add_argument("--temperatures", type=float, nargs="+", default=[800.0, 1200.0, 1600.0])
    parser.add_argument("--pressure-atm", type=float, default=1.0)
    parser.add_argument("--co2", type=float, default=0.12)
    parser.add_argument("--h2o", type=float, default=0.08)
    parser.add_argument("--path-min-m", type=float, default=0.05)
    parser.add_argument("--path-max-m", type=float, default=5.0)
    parser.add_argument("--path-count", type=int, default=20)
    parser.add_argument("--fit-grid-size", type=int, default=80)
    parser.add_argument("--fit-iterations", type=int, default=1000)
    args = parser.parse_args()
    report = run_calibration(
        args.line_csv, args.tips_csv, args.output, release=args.release,
        wn_min_cm=args.wn_min, wn_max_cm=args.wn_max, wn_step_cm=args.wn_step,
        temperatures_k=tuple(args.temperatures), pressure_atm=args.pressure_atm,
        co2_mole_fraction=args.co2, h2o_mole_fraction=args.h2o,
        path_min_m=args.path_min_m, path_max_m=args.path_max_m,
        path_count=args.path_count, fit_grid_size=args.fit_grid_size,
        fit_iterations=args.fit_iterations,
    )
    print(f"Wrote HITEMP/TIPS WSGG calibration: {args.output}")
    print(f"Transitions: {report['provenance']['line_count']}; temperatures: {len(report['results'])}")


if __name__ == "__main__":
    main()
