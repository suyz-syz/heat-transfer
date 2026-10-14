#!/usr/bin/env python3
"""Fit a constrained narrow-band WSGG model to offline LBL transmittance data.

Input CSV columns:
    temperature_K, pressure_atm, x_co2, x_h2o, path_m, tau_reference

Each unique (temperature, pressure, composition) combination is an indivisible
case group. A deterministic hash split keeps all path lengths from a condition
in either training or holdout, never both. The resulting JSON is an offline
calibration artifact only; it does not update production solver coefficients.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
from pathlib import Path
from typing import Sequence

import numpy as np
from scipy.optimize import least_squares

BAND_CM_INV = (2000.0, 2400.0)
CONDITION_COLUMNS = (
    "temperature_K", "pressure_atm", "x_co2", "x_h2o",
)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_observations(path: Path) -> list[dict]:
    required = set(CONDITION_COLUMNS) | {"path_m", "tau_reference"}
    rows: list[dict] = []
    with path.open(newline="", encoding="utf-8-sig") as stream:
        reader = csv.DictReader(stream)
        missing = required - set(reader.fieldnames or ())
        if missing:
            raise ValueError(f"input CSV missing columns: {sorted(missing)}")
        for line_number, raw in enumerate(reader, start=2):
            try:
                row = {key: float(raw[key]) for key in required}
            except (TypeError, ValueError) as exc:
                raise ValueError(f"invalid numeric value on CSV line {line_number}") from exc
            if not all(math.isfinite(value) for value in row.values()):
                raise ValueError(f"non-finite value on CSV line {line_number}")
            if row["temperature_K"] <= 0 or row["pressure_atm"] <= 0 or row["path_m"] < 0:
                raise ValueError(f"invalid temperature, pressure, or path on line {line_number}")
            if not (0 <= row["x_co2"] < 1 and 0 <= row["x_h2o"] < 1
                    and row["x_co2"] + row["x_h2o"] < 1):
                raise ValueError(f"invalid gas mole fractions on line {line_number}")
            if not 0 <= row["tau_reference"] <= 1:
                raise ValueError(f"tau_reference must be in [0, 1] on line {line_number}")
            row["source_line"] = line_number
            rows.append(row)
    if not rows:
        raise ValueError("input CSV contains no observations")
    return rows


def condition_key(row: dict) -> tuple[float, ...]:
    """Full thermochemical condition; path length is a within-case sample axis."""
    return tuple(float(row[name]) for name in CONDITION_COLUMNS)


def split_groups(
    rows: Sequence[dict], holdout_fraction: float, seed: str,
) -> tuple[list[dict], list[dict], list[tuple[float, ...]], list[tuple[float, ...]]]:
    groups = sorted({condition_key(row) for row in rows})
    if len(groups) < 2:
        raise ValueError("at least two distinct full-condition groups are required for holdout")
    if not 0 < holdout_fraction < 1:
        raise ValueError("holdout_fraction must be strictly between zero and one")

    # Hash-ranked selection is deterministic, independent of CSV row order, and
    # moves the complete condition group (all its paths) as one unit.
    ranked = sorted(
        groups,
        key=lambda key: hashlib.sha256(
            (seed + "\0" + json.dumps(key, separators=(",", ":"))).encode("utf-8")
        ).hexdigest(),
    )
    holdout_count = min(len(groups) - 1, max(1, int(math.ceil(len(groups) * holdout_fraction))))
    holdout_keys = set(ranked[:holdout_count])
    train = [row for row in rows if condition_key(row) not in holdout_keys]
    holdout = [row for row in rows if condition_key(row) in holdout_keys]
    train_keys = [key for key in groups if key not in holdout_keys]
    held_keys = [key for key in groups if key in holdout_keys]
    return train, holdout, train_keys, held_keys


def _softmax(values: np.ndarray) -> np.ndarray:
    shifted = values - np.max(values)
    exp_values = np.exp(shifted)
    return exp_values / exp_values.sum()


def decode_parameters(params: np.ndarray, n_gases: int, kappa_min: float, kappa_max: float):
    """Map unconstrained parameters to simplex weights and ordered kappas.

    Kappa gaps are a softmax partition of [kappa_min, kappa_max]. Thus every
    kappa is nonnegative, ordered, and bounded without sorting or clipping.
    """
    weight_logits = np.r_[params[:n_gases - 1], 0.0]
    weights = _softmax(weight_logits)
    gap_logits = np.r_[params[n_gases - 1:], 0.0]
    gaps = _softmax(gap_logits)
    kappas = kappa_min + (kappa_max - kappa_min) * np.cumsum(gaps[:-1])
    return weights, kappas


def predict_tau(
    u: Sequence[float], weights: Sequence[float], kappas: Sequence[float],
    *, u_domain: tuple[float, float],
) -> np.ndarray:
    u_values = np.asarray(u, dtype=float)
    weight_values = np.asarray(weights, dtype=float)
    kappa_values = np.asarray(kappas, dtype=float)
    u_min, u_max = u_domain
    if (u_values.ndim != 1 or not np.all(np.isfinite(u_values))
            or np.any(u_values < 0)):
        raise ValueError("optical path u must contain finite nonnegative values")
    if (not math.isfinite(u_min) or not math.isfinite(u_max)
            or u_min < 0 or u_max < u_min):
        raise ValueError("calibrated optical-path domain must be finite and nonnegative")
    if np.any(u_values < u_min) or np.any(u_values > u_max):
        raise ValueError(
            f"optical path outside calibrated domain [{u_min}, {u_max}]; refusing extrapolation"
        )
    if (weight_values.ndim not in (1, 2) or kappa_values.ndim != 1
            or weight_values.shape[-1] == 0 or weight_values.shape[-1] != kappa_values.size
            or (weight_values.ndim == 2 and weight_values.shape[0] != u_values.size)
            or not np.all(np.isfinite(weight_values))
            or not np.all(np.isfinite(kappa_values))):
        raise ValueError("weights and kappas must be finite, nonempty arrays with matching gas dimensions")
    weight_sums = weight_values.sum(axis=-1)
    if (np.any(weight_values < 0) or not np.allclose(weight_sums, 1.0, atol=1e-12)
            or np.any(kappa_values < 0) or np.any(np.diff(kappa_values) < 0)):
        raise ValueError("WSGG parameters violate simplex or ordered nonnegative kappa constraints")
    terms = np.exp(-u_values[:, None] * kappa_values[None, :])
    predicted = (terms @ weight_values if weight_values.ndim == 1
                 else np.sum(terms * weight_values, axis=1))
    roundoff_tolerance = 32 * np.finfo(float).eps
    if (not np.all(np.isfinite(predicted))
            or np.any(predicted < -roundoff_tolerance)
            or np.any(predicted > 1 + roundoff_tolerance)):
        raise ArithmeticError("WSGG transmittance is outside physical bounds [0, 1]")
    # Only correct floating-point noise at the physical endpoints; material
    # violations above raise rather than being silently clipped.
    predicted = np.clip(predicted, 0.0, 1.0)
    predicted[u_values == 0] = 1.0
    return predicted


def _condition_u(row: dict) -> float:
    # kappa uses optical path in atm*m, matching reports/hitemp_wsgg_calibration.json.
    return float(row["pressure_atm"] * row["path_m"])


def calibration_domain(rows: Sequence[dict]) -> dict[str, dict[str, float]]:
    domain: dict[str, dict[str, float]] = {}
    for name in (*CONDITION_COLUMNS, "optical_path_atm_m"):
        values = [
            _condition_u(row) if name == "optical_path_atm_m" else float(row[name])
            for row in rows
        ]
        domain[name] = {"min": min(values), "max": max(values)}
    return domain


def require_within_calibration_domain(rows: Sequence[dict], domain: dict) -> None:
    for row in rows:
        values = {name: float(row[name]) for name in CONDITION_COLUMNS}
        values["optical_path_atm_m"] = _condition_u(row)
        for name, value in values.items():
            bounds = domain[name]
            if value < bounds["min"] or value > bounds["max"]:
                raise ValueError(
                    f"{name}={value} outside calibrated domain "
                    f"[{bounds['min']}, {bounds['max']}]; refusing extrapolation"
                )


def fit_model(
    rows: Sequence[dict], n_gases: int, kappa_min: float, kappa_max: float,
    max_nfev: int,
) -> tuple[np.ndarray, np.ndarray, dict]:
    if len(rows) < n_gases + 1:
        raise ValueError(f"training set needs at least n_gases+1={n_gases + 1} observations")
    u = np.asarray([_condition_u(row) for row in rows], dtype=float)
    u_domain = (float(np.min(u)), float(np.max(u)))
    target = np.asarray([row["tau_reference"] for row in rows], dtype=float)
    if np.unique(u).size < 2:
        raise ValueError("training set must contain at least two distinct pressure*path values")

    # Start from separated, physically useful kappa scales rather than an
    # evenly spaced partition of the full bound. With the default bounds this
    # initializes roughly at 0.01, 0.1, 1, and 10 atm^-1 m^-1.
    span = kappa_max - kappa_min
    first = max(kappa_min + span * 1e-8, min(0.01, kappa_max * 1e-4))
    last = min(kappa_max - span * 1e-8, max(first * 10.0, min(10.0, kappa_min + span * 0.1)))
    if n_gases == 1:
        initial_kappas = np.asarray([(first + last) * 0.5])
    else:
        initial_kappas = np.geomspace(first, last, n_gases)
    gaps = np.diff(np.r_[kappa_min, initial_kappas, kappa_max])
    initial = np.zeros((n_gases - 1) + n_gases, dtype=float)
    initial[n_gases - 1:] = np.log(gaps[:-1] / gaps[-1])

    def residual(params: np.ndarray) -> np.ndarray:
        weights, kappas = decode_parameters(params, n_gases, kappa_min, kappa_max)
        return predict_tau(u, weights, kappas, u_domain=u_domain) - target

    result = least_squares(
        residual, initial, method="trf", max_nfev=max_nfev,
        ftol=1e-11, xtol=1e-11, gtol=1e-11,
    )
    if not result.success and result.status <= 0:
        raise RuntimeError(f"constrained WSGG fit did not converge: {result.message}")
    weights, kappas = decode_parameters(result.x, n_gases, kappa_min, kappa_max)
    return weights, kappas, {
        "success": bool(result.success),
        "message": str(result.message),
        "function_evaluations": int(result.nfev),
        "training_rmse_tau": float(np.sqrt(np.mean(result.fun ** 2))),
        "training_sse_tau": float(np.dot(result.fun, result.fun)),
    }


def error_metrics(
    rows: Sequence[dict], weights: np.ndarray, kappas: np.ndarray,
    domain: dict[str, dict[str, float]],
) -> dict:
    require_within_calibration_domain(rows, domain)
    target = np.asarray([row["tau_reference"] for row in rows], dtype=float)
    u = np.asarray([_condition_u(row) for row in rows], dtype=float)
    u_bounds = domain["optical_path_atm_m"]
    predicted = predict_tau(
        u, weights, kappas, u_domain=(u_bounds["min"], u_bounds["max"]),
    )
    absolute = np.abs(predicted - target)
    relative_percent = absolute / np.maximum(np.abs(target), 1e-8) * 100.0
    return {
        "sample_count": int(target.size),
        "condition_group_count": len({condition_key(row) for row in rows}),
        "rmse_tau": float(np.sqrt(np.mean((predicted - target) ** 2))),
        "mae_tau": float(np.mean(absolute)),
        "max_absolute_error_tau": float(np.max(absolute)),
        "mape_percent": float(np.mean(relative_percent)),
        "relative_error_p95_percent": float(np.percentile(relative_percent, 95)),
        "absolute_error_p95_tau": float(np.percentile(absolute, 95)),
        "tau_reference_floor_for_relative_error": 1e-8,
    }


def condition_group_metrics(
    rows: Sequence[dict], weights: np.ndarray, kappas: np.ndarray,
    domain: dict[str, dict[str, float]],
) -> list[dict]:
    """Return holdout errors for each indivisible thermochemical condition."""
    grouped: dict[tuple[float, ...], list[dict]] = {}
    for row in rows:
        grouped.setdefault(condition_key(row), []).append(row)

    results = []
    for key, group_rows in sorted(grouped.items()):
        metrics = error_metrics(group_rows, weights, kappas, domain)
        results.append({
            "condition": dict(zip(CONDITION_COLUMNS, key)),
            **metrics,
        })
    # Put the conditions with the largest absolute error first for quick review.
    return sorted(
        results,
        key=lambda item: (item["max_absolute_error_tau"], item["rmse_tau"]),
        reverse=True,
    )


def run(
    input_csv: Path, output_json: Path, *, n_gases: int = 4,
    holdout_fraction: float = 0.2, seed: str = "p3b-v1",
    kappa_min: float = 0.0, kappa_max: float = 1000.0,
    max_nfev: int = 10000,
) -> dict:
    if n_gases < 1 or kappa_min < 0 or not kappa_max > kappa_min:
        raise ValueError("require n_gases >= 1 and 0 <= kappa_min < kappa_max")
    if not math.isfinite(kappa_min) or not math.isfinite(kappa_max):
        raise ValueError("kappa bounds must be finite")
    if max_nfev < 1:
        raise ValueError("max_nfev must be positive")

    rows = load_observations(input_csv)
    train, holdout, train_keys, holdout_keys = split_groups(rows, holdout_fraction, seed)
    weights, kappas, optimizer = fit_model(
        train, n_gases, kappa_min, kappa_max, max_nfev,
    )
    train_domain = calibration_domain(train)
    # Assertions make any future parameterization regression fail before reporting.
    if np.any(weights < 0) or not np.isclose(weights.sum(), 1.0, atol=1e-12):
        raise AssertionError("weight simplex constraint violated")
    if np.any(kappas < 0) or np.any(np.diff(kappas) < 0):
        raise AssertionError("nonnegative/order constraint violated")

    report = {
        "report_type": "P3b offline constrained WSGG narrow-band transmittance fit",
        "status": "provisional_offline_fit_requires_independent_physical_validation",
        "scope": {
            "band_cm-1": list(BAND_CM_INV),
            "target": "band-averaged transmittance",
            "model": "tau(u) = sum_i a_i * exp(-kappa_i * u)",
            "u_definition": "pressure_atm * path_m",
            "kappa_unit": "atm^-1 m^-1",
            "n_gray_gases": n_gases,
            "production_solver_changed": False,
            "leckner_fast_path_changed": False,
            "provisional_status_removed": False,
        },
        "inputs": {
            "path": str(input_csv),
            "sha256": sha256_file(input_csv),
            "row_count": len(rows),
            "condition_columns": list(CONDITION_COLUMNS),
            "split_seed": seed,
            "holdout_fraction": holdout_fraction,
            "split_method": "deterministic SHA-256 ranking of complete (T, p, x_CO2, x_H2O) groups",
            "train_condition_groups": [list(key) for key in train_keys],
            "holdout_condition_groups": [list(key) for key in holdout_keys],
            "train_group_count": len(train_keys),
            "holdout_group_count": len(holdout_keys),
            "calibration_domain_from_training": train_domain,
            "domain_policy": "Reject values outside componentwise training min/max for T, p, mole fractions, or pressure*path. This axis-aligned guard does not establish joint-space coverage.",
        },
        "constraints": {
            "weights_nonnegative": bool(np.all(weights >= 0)),
            "weights_sum": float(weights.sum()),
            "kappa_nonnegative": bool(np.all(kappas >= 0)),
            "kappa_sorted_non_decreasing": bool(np.all(np.diff(kappas) >= 0)),
            "kappa_bounds": [kappa_min, kappa_max],
            "parameterization": "softmax simplex weights and softmax-partitioned ordered kappa gaps",
        },
        "parameters": {
            "weights": [float(value) for value in weights],
            "kappa_atm_inv_m_inv": [float(value) for value in kappas],
        },
        "optimizer": optimizer,
        "metrics": {
            "training": error_metrics(train, weights, kappas, train_domain),
            "holdout": error_metrics(holdout, weights, kappas, train_domain),
            "holdout_by_condition": condition_group_metrics(
                holdout, weights, kappas, train_domain,
            ),
        },
        "limitations": [
            "This is a narrow-band offline fit and is not a total-spectrum radiation model.",
            "Holdout metrics are condition-grouped and must be reviewed before any engineering use.",
            "The reference data's spectral and line-shape uncertainty is inherited by this fit.",
            "No production solver, Leckner fast path, or provisional status is changed by this script.",
        ],
    }
    output_json.parent.mkdir(parents=True, exist_ok=True)
    output_json.write_text(json.dumps(report, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-csv", required=True, type=Path)
    parser.add_argument(
        "--output", type=Path,
        default=Path("reports/hitemp_wsgg_narrowband_fit.json"),
    )
    parser.add_argument("--n-gases", type=int, default=4)
    parser.add_argument("--holdout-fraction", type=float, default=0.2)
    parser.add_argument("--seed", default="p3b-v1")
    parser.add_argument("--kappa-min", type=float, default=0.0)
    parser.add_argument("--kappa-max", type=float, default=1000.0)
    parser.add_argument("--max-nfev", type=int, default=10000)
    args = parser.parse_args()
    report = run(
        args.input_csv, args.output, n_gases=args.n_gases,
        holdout_fraction=args.holdout_fraction, seed=args.seed,
        kappa_min=args.kappa_min, kappa_max=args.kappa_max,
        max_nfev=args.max_nfev,
    )
    print(json.dumps({
        "status": report["status"],
        "input_sha256": report["inputs"]["sha256"],
        "train": report["metrics"]["training"],
        "holdout": report["metrics"]["holdout"],
        "parameters": report["parameters"],
        "output": str(args.output),
    }, indent=2))


if __name__ == "__main__":
    main()
