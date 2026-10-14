#!/usr/bin/env python3
"""Compare global and two-stratum temperature-weight WSGG fits offline.

The prototype shares ordered kappa values across temperature strata and gives
each stratum its own simplex weights. It is an evaluation artifact only; it
does not update production coefficients or the primary P3b fit.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

import numpy as np
from scipy.optimize import least_squares

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.hitemp_calibration.fit_wsgg_narrowband import (
    calibration_domain,
    condition_key,
    error_metrics,
    fit_model,
    load_observations,
    predict_tau,
    require_within_calibration_domain,
    split_groups,
)

N_GASES = 4
STRATA = (("T_le_1200K", lambda t: t <= 1200.0), ("T_gt_1200K", lambda t: t > 1200.0))


def _decode(params: np.ndarray, n_gases: int) -> tuple[dict[int, np.ndarray], np.ndarray]:
    from scripts.hitemp_calibration.fit_wsgg_narrowband import _softmax, decode_parameters

    weight_count = n_gases - 1
    weights = {}
    for index in range(len(STRATA)):
        logits = np.r_[params[index * weight_count:(index + 1) * weight_count], 0.0]
        weights[index] = _softmax(logits)
    # decode_parameters consumes weight logits before the kappa gap logits.
    zeros = np.zeros(weight_count)
    _, kappas = decode_parameters(
        np.r_[zeros, params[len(STRATA) * weight_count:]], n_gases, 0.0, 1000.0,
    )
    return weights, kappas


def _stratum_index(temperature: float) -> int:
    return 0 if temperature <= 1200.0 else 1


def _predict(rows, weights_by_stratum, kappas, domain):
    require_within_calibration_domain(rows, domain)
    u_domain = domain["optical_path_atm_m"]
    predicted = np.empty(len(rows), dtype=float)
    for index in range(len(STRATA)):
        positions = [i for i, row in enumerate(rows) if _stratum_index(row["temperature_K"]) == index]
        if positions:
            u = [rows[i]["pressure_atm"] * rows[i]["path_m"] for i in positions]
            predicted[positions] = predict_tau(
                u, weights_by_stratum[index], kappas,
                u_domain=(u_domain["min"], u_domain["max"]),
            )
    return predicted


def _metrics(rows, predicted):
    target = np.asarray([r["tau_reference"] for r in rows], dtype=float)
    error = predicted - target
    absolute = np.abs(error)
    relative = absolute / np.maximum(np.abs(target), 1e-8) * 100.0
    return {
        "sample_count": int(target.size),
        "condition_group_count": len({condition_key(r) for r in rows}),
        "rmse_tau": float(np.sqrt(np.mean(error ** 2))),
        "mae_tau": float(np.mean(absolute)),
        "max_absolute_error_tau": float(np.max(absolute)),
        "absolute_error_p95_tau": float(np.percentile(absolute, 95)),
        "mape_percent": float(np.mean(relative)),
    }


def evaluate(input_csv: Path, output_json: Path, *, seed="p3b-v1", holdout_fraction=0.2):
    rows = load_observations(input_csv)
    train, holdout, train_keys, holdout_keys = split_groups(rows, holdout_fraction, seed)
    domain = calibration_domain(train)

    global_weights, global_kappas, optimizer = fit_model(
        train, N_GASES, 0.0, 1000.0, 10000,
    )
    baseline_train = error_metrics(train, global_weights, global_kappas, domain)
    baseline_holdout = error_metrics(holdout, global_weights, global_kappas, domain)

    if any(not any(_stratum_index(r["temperature_K"]) == i for r in train)
           for i in range(len(STRATA))):
        raise ValueError("every temperature stratum must have training observations")
    weight_count = N_GASES - 1
    weight_logits = np.tile(np.log(global_weights[:-1] / global_weights[-1]), len(STRATA))
    gaps = np.diff(np.r_[0.0, global_kappas, 1000.0])
    gap_logits = np.log(gaps[:-1] / gaps[-1])
    initial = np.r_[weight_logits, gap_logits]
    target = np.asarray([r["tau_reference"] for r in train])

    def residual(params):
        weights, kappas = _decode(params, N_GASES)
        return _predict(train, weights, kappas, domain) - target

    result = least_squares(
        residual, initial, method="trf", max_nfev=10000,
        ftol=1e-11, xtol=1e-11, gtol=1e-11,
    )
    if not result.success:
        raise RuntimeError(f"stratified fit failed: {result.message}")
    weights, kappas = _decode(result.x, N_GASES)
    strat_train_pred = _predict(train, weights, kappas, domain)
    strat_holdout_pred = _predict(holdout, weights, kappas, domain)
    global_holdout_pred = _predict(
        holdout, {0: global_weights, 1: global_weights}, global_kappas, domain,
    )

    holdout_by_temperature = {}
    for name, predicate in STRATA:
        subset = [r for r in holdout if predicate(r["temperature_K"])]
        subset_pred = _predict(subset, weights, kappas, domain)
        holdout_by_temperature[name] = {
            "global": error_metrics(subset, global_weights, global_kappas, domain),
            "stratified": _metrics(subset, subset_pred),
        }

    by_condition = {}
    for key in sorted({condition_key(row) for row in holdout}):
        indices = [i for i, row in enumerate(holdout) if condition_key(row) == key]
        condition = dict(zip(
            ("temperature_K", "pressure_atm", "x_co2", "x_h2o"), key,
        ))
        by_condition[json.dumps(condition, sort_keys=True)] = {
            "condition": condition,
            "global": _metrics([holdout[i] for i in indices], global_holdout_pred[indices]),
            "stratified": _metrics([holdout[i] for i in indices], strat_holdout_pred[indices]),
        }

    path_error_traces = []
    for key in sorted({condition_key(row) for row in holdout if row["temperature_K"] in (600.0, 2400.0)}):
        indices = sorted(
            (i for i, row in enumerate(holdout) if condition_key(row) == key),
            key=lambda i: holdout[i]["path_m"],
        )
        trace = []
        for i in indices:
            row = holdout[i]
            u = row["pressure_atm"] * row["path_m"]
            trace.append({
                "path_m": row["path_m"],
                "optical_path_atm_m": u,
                "tau_reference": row["tau_reference"],
                "global_tau": float(global_holdout_pred[i]),
                "global_error_tau": float(global_holdout_pred[i] - row["tau_reference"]),
                "stratified_tau": float(strat_holdout_pred[i]),
                "stratified_error_tau": float(strat_holdout_pred[i] - row["tau_reference"]),
            })
        path_error_traces.append({
            "condition": dict(zip(
                ("temperature_K", "pressure_atm", "x_co2", "x_h2o"), key,
            )),
            "paths": trace,
        })

    report = {
        "status": "offline_experiment_only_requires_independent_validation",
        "method": "two temperature strata (T <= 1200 K and T > 1200 K), separate simplex weights, shared ordered kappas",
        "production_solver_changed": False,
        "leckner_fast_path_changed": False,
        "provisional_status_removed": False,
        "input": str(input_csv),
        "input_sha256": __import__("hashlib").sha256(input_csv.read_bytes()).hexdigest(),
        "split_seed": seed,
        "train_condition_group_count": len(train_keys),
        "holdout_condition_group_count": len(holdout_keys),
        "calibration_domain_from_training": domain,
        "global_optimizer": optimizer,
        "global": {"training": baseline_train, "holdout": baseline_holdout},
        "temperature_stratified": {
            "optimizer_success": bool(result.success),
            "function_evaluations": int(result.nfev),
            "training": _metrics(train, strat_train_pred),
            "holdout": _metrics(holdout, strat_holdout_pred),
            "weights_by_stratum": {STRATA[i][0]: values.tolist() for i, values in weights.items()},
            "shared_kappa_atm_inv_m_inv": kappas.tolist(),
            "holdout_by_temperature": holdout_by_temperature,
            "holdout_by_condition": list(by_condition.values()),
            "holdout_path_error_traces_600K_2400K": path_error_traces,
        },
        "limitations": [
            "The fixed 1200 K split is exploratory and was selected for this grid; verify it on independent conditions.",
            "Composition and pressure effects remain unparameterized; weights may absorb correlated effects.",
            "The reference uses an incomplete line sample and pseudo-Voigt LBL; no independent spectroscopy validation is included.",
            "No production solver, Leckner fast path, or provisional status is changed.",
        ],
    }
    output_json.parent.mkdir(parents=True, exist_ok=True)
    output_json.write_text(json.dumps(report, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-csv", type=Path, default=Path("data/hitemp_narrowband_tau_reference.csv"))
    parser.add_argument("--output", type=Path, default=Path("reports/hitemp_wsgg_temperature_stratified_experiment.json"))
    args = parser.parse_args()
    report = evaluate(args.input_csv, args.output)
    print(json.dumps({
        "global_holdout": report["global"]["holdout"],
        "temperature_stratified_holdout": report["temperature_stratified"]["holdout"],
        "holdout_by_temperature": report["temperature_stratified"]["holdout_by_temperature"],
        "output": str(args.output),
    }, indent=2))


if __name__ == "__main__":
    main()
