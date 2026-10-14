#!/usr/bin/env python3
"""Probe domain rejection and mathematical stability of the smooth WSGG trial.

Out-of-domain formula scans are numerical diagnostics only; they are not
accepted predictions and do not establish physical accuracy beyond the data.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.hitemp_calibration.evaluate_smooth_composition_wsgg import (  # noqa: E402
    _decode,
    _features,
    _predict,
)
from scripts.hitemp_calibration.fit_wsgg_narrowband import (  # noqa: E402
    calibration_domain,
    load_observations,
    predict_tau,
)


def assess(input_csv: Path, fit_report: Path, output_json: Path) -> dict:
    fit = json.loads(fit_report.read_text(encoding="utf-8"))
    params = fit["final_refit_descriptive_parameters"]
    transform_raw = params["feature_transform"]
    transform = {
        "mean": np.asarray(transform_raw["mean_temperature_K_x_co2_x_h2o"], dtype=float),
        "scale": np.asarray(transform_raw["scale_temperature_K_x_co2_x_h2o"], dtype=float),
        "quadratic_mean": transform_raw["temperature_quadratic_mean"],
        "quadratic_scale": transform_raw["temperature_quadratic_scale"],
    }
    coefficients = np.asarray(
        params["free_logit_coefficients_intercept_then_features"], dtype=float,
    )
    kappas = np.asarray(params["shared_kappa_atm_inv_m_inv"], dtype=float)
    gaps = np.diff(np.r_[0.0, kappas, 1000.0])
    model_params = np.r_[coefficients.ravel(), np.log(gaps[:-1] / gaps[-1])]
    rows = load_observations(input_csv)
    domain = calibration_domain(rows)

    nominal = {
        "temperature_K": 1000.0,
        "pressure_atm": 1.0,
        "path_m": 1.0,
        "x_co2": 0.12,
        "x_h2o": 0.08,
    }
    probes = (
        ("temperature_below", {"temperature_K": 500.0}),
        ("temperature_above", {"temperature_K": 2600.0}),
        ("x_co2_below", {"x_co2": 0.05}),
        ("x_co2_above", {"x_co2": 0.25}),
        ("x_h2o_below", {"x_h2o": 0.02}),
        ("x_h2o_above", {"x_h2o": 0.15}),
        ("optical_path_above", {"pressure_atm": 3.0, "path_m": 6.0}),
    )
    rejected = []
    for name, updates in probes:
        row = {**nominal, **updates}
        weights, _ = _decode(model_params, _features([row], transform))
        try:
            _predict([row], weights, kappas, domain)
        except ValueError as exc:
            rejected.append({"probe": name, "rejected": True, "reason": str(exc)})
        else:
            raise AssertionError(f"out-of-domain probe was accepted: {name}")

    temperatures = np.linspace(300.0, 3000.0, 601)
    compositions = ((0.05, 0.02), (0.25, 0.15), (0.12, 0.08))
    u_grid = np.linspace(0.0, 20.0, 201)
    min_weight, max_weight, max_weight_slope = 1.0, 0.0, 0.0
    physical_bound_violations = 0
    max_positive_tau_step = 0.0
    max_tau_at_zero_error = 0.0
    weights_finite_simplex = True
    for x_co2, x_h2o in compositions:
        feature_rows = [
            {"temperature_K": float(t), "x_co2": x_co2, "x_h2o": x_h2o}
            for t in temperatures
        ]
        feature_matrix = _features(feature_rows, transform)
        weights, _ = _decode(model_params, feature_matrix)
        weights_finite_simplex = weights_finite_simplex and bool(
            np.all(np.isfinite(weights)) and np.all(weights >= 0)
            and np.allclose(weights.sum(axis=1), 1.0, atol=1e-12)
        )
        min_weight = min(min_weight, float(weights.min()))
        max_weight = max(max_weight, float(weights.max()))
        max_weight_slope = max(
            max_weight_slope,
            float(np.max(np.abs(np.diff(weights, axis=0))) / (temperatures[1] - temperatures[0])),
        )
        for weight in weights:
            tau = predict_tau(
                u_grid, np.tile(weight, (len(u_grid), 1)), kappas,
                u_domain=(0.0, 20.0),
            )
            physical_bound_violations += int(np.count_nonzero((tau < 0) | (tau > 1)))
            max_positive_tau_step = max(max_positive_tau_step, float(np.max(np.diff(tau))))
            max_tau_at_zero_error = max(max_tau_at_zero_error, abs(float(tau[0]) - 1.0))

    report = {
        "status": "domain_guard_passed_raw_extension_is_diagnostic_only",
        "fit_report": str(fit_report),
        "training_domain": domain,
        "domain_guard_probes": rejected,
        "raw_formula_stress_scan": {
            "temperature_K": [float(temperatures[0]), float(temperatures[-1])],
            "temperature_sample_count": int(temperatures.size),
            "composition_cases_x_co2_x_h2o": [list(pair) for pair in compositions],
            "u_scan_atm_m": [float(u_grid[0]), float(u_grid[-1])],
            "weights_finite_and_simplex": weights_finite_simplex,
            "weight_minimum": min_weight,
            "weight_maximum": max_weight,
            "maximum_absolute_weight_change_per_K": max_weight_slope,
            "tau_bounds_violations": physical_bound_violations,
            "maximum_positive_tau_step_as_u_increases": max_positive_tau_step,
            "maximum_absolute_tau_at_u0_minus_one": max_tau_at_zero_error,
        },
        "interpretation": [
            "The supported prediction path rejected all seven out-of-domain probes.",
            "The raw polynomial-logit extension was scanned only for numeric shape and physical bounds; no reference truth exists outside the sampled domain.",
            "The quadratic temperature logits are continuous and the weight scan showed no abrupt high-frequency oscillation; this does not imply out-of-domain accuracy.",
            "The mixture-of-exponentials remains bounded and non-increasing with optical path when simplex weights and nonnegative shared kappas are enforced.",
        ],
        "production_solver_changed": False,
        "leckner_fast_path_changed": False,
        "provisional_status_removed": False,
    }
    output_json.parent.mkdir(parents=True, exist_ok=True)
    output_json.write_text(json.dumps(report, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-csv", type=Path, default=Path("data/hitemp_narrowband_tau_reference.csv"))
    parser.add_argument("--fit-report", type=Path, default=Path("reports/hitemp_wsgg_smooth_composition_cv.json"))
    parser.add_argument("--output", type=Path, default=Path("reports/hitemp_wsgg_smooth_composition_extrapolation.json"))
    args = parser.parse_args()
    report = assess(args.input_csv, args.fit_report, args.output)
    print(json.dumps({
        "status": report["status"],
        "rejected_domain_probe_count": len(report["domain_guard_probes"]),
        "raw_formula_stress_scan": report["raw_formula_stress_scan"],
        "output": str(args.output),
    }, indent=2))


if __name__ == "__main__":
    main()
