#!/usr/bin/env python3
"""Nested grouped-CV trial of smooth temperature/composition WSGG weights.

The offline model uses shared ordered kappa values and softmax weights whose
logits are quadratic in temperature and linear in CO2/H2O mole fractions.
Slope coefficients receive ridge regularization. No runtime coefficients are
changed by this experiment.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
from pathlib import Path

import numpy as np
from scipy.optimize import least_squares

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.hitemp_calibration.fit_wsgg_narrowband import (  # noqa: E402
    calibration_domain,
    condition_key,
    fit_model,
    load_observations,
    predict_tau,
    require_within_calibration_domain,
)

N_GASES = 4
N_SPLITS_OUTER = 4
N_SPLITS_INNER = 3
REGULARIZATION_GRID = (0.01, 0.1, 1.0)
FEATURE_NAMES = ("temperature_linear", "temperature_quadratic", "x_co2", "x_h2o")


def _folds(rows, count: int, seed: str):
    groups = sorted({condition_key(row) for row in rows})
    if count < 2 or count > len(groups):
        raise ValueError("fold count must be between 2 and the number of condition groups")
    ranked = sorted(groups, key=lambda key: hashlib.sha256(
        (seed + "\0" + json.dumps(key, separators=(",", ":"))).encode("utf-8")
    ).hexdigest())
    group_fold = {key: index % count for index, key in enumerate(ranked)}
    return [
        ([row for row in rows if group_fold[condition_key(row)] != fold],
         [row for row in rows if group_fold[condition_key(row)] == fold])
        for fold in range(count)
    ]


def _feature_transform(rows):
    raw = np.asarray([
        [row["temperature_K"], row["x_co2"], row["x_h2o"]] for row in rows
    ], dtype=float)
    mean = raw.mean(axis=0)
    scale = raw.std(axis=0)
    scale[scale == 0] = 1.0
    normalized = (raw - mean) / scale
    quadratic = normalized[:, 0] ** 2
    quadratic_mean = float(quadratic.mean())
    quadratic_scale = float(quadratic.std()) or 1.0
    return {
        "mean": mean,
        "scale": scale,
        "quadratic_mean": quadratic_mean,
        "quadratic_scale": quadratic_scale,
    }


def _features(rows, transform):
    raw = np.asarray([
        [row["temperature_K"], row["x_co2"], row["x_h2o"]] for row in rows
    ], dtype=float)
    normalized = (raw - transform["mean"]) / transform["scale"]
    quadratic = (normalized[:, 0] ** 2 - transform["quadratic_mean"]) / transform["quadratic_scale"]
    return np.column_stack((normalized[:, 0], quadratic, normalized[:, 1], normalized[:, 2]))


def _decode(params, features):
    from scripts.hitemp_calibration.fit_wsgg_narrowband import _softmax, decode_parameters

    # Three free gas logits, each with an intercept and four smooth features;
    # the fourth gas logit is fixed at zero to remove the additive ambiguity.
    coefficient_count = (len(FEATURE_NAMES) + 1) * (N_GASES - 1)
    coefficients = params[:coefficient_count].reshape(N_GASES - 1, len(FEATURE_NAMES) + 1)
    logits = np.column_stack((np.ones(len(features)), features)) @ coefficients.T
    weights = np.apply_along_axis(_softmax, 1, np.column_stack((logits, np.zeros(len(features)))))
    _, kappas = decode_parameters(
        np.r_[np.zeros(N_GASES - 1), params[coefficient_count:]], N_GASES, 0.0, 1000.0,
    )
    return weights, kappas


def _predict(rows, weights, kappas, domain):
    require_within_calibration_domain(rows, domain)
    u_bounds = domain["optical_path_atm_m"]
    u = np.asarray([row["pressure_atm"] * row["path_m"] for row in rows], dtype=float)
    return predict_tau(u, weights, kappas, u_domain=(u_bounds["min"], u_bounds["max"]))


def _summarize(rows, predicted):
    target = np.asarray([row["tau_reference"] for row in rows], dtype=float)
    errors = predicted - target
    absolute = np.abs(errors)
    relative = absolute / np.maximum(np.abs(target), 1e-8) * 100.0
    return {
        "sample_count": len(rows),
        "condition_group_count": len({condition_key(row) for row in rows}),
        "rmse_tau": float(np.sqrt(np.mean(errors ** 2))),
        "mae_tau": float(np.mean(absolute)),
        "max_absolute_error_tau": float(np.max(absolute)),
        "absolute_error_p95_tau": float(np.percentile(absolute, 95)),
        "mape_percent": float(np.mean(relative)),
    }


def _fit_smooth(train, regularization, max_nfev=10000):
    transform = _feature_transform(train)
    x = _features(train, transform)
    u = np.asarray([row["pressure_atm"] * row["path_m"] for row in train], dtype=float)
    target = np.asarray([row["tau_reference"] for row in train], dtype=float)
    # Stable neutral starting point; avoids an extra global optimization for
    # every inner-fold/regularization candidate.
    coefficients = np.zeros((N_GASES - 1, len(FEATURE_NAMES) + 1), dtype=float)
    initial_kappas = np.geomspace(0.01, 10.0, N_GASES)
    gaps = np.diff(np.r_[0.0, initial_kappas, 1000.0])
    gap_logits = np.log(gaps[:-1] / gaps[-1])
    initial = np.r_[coefficients.ravel(), gap_logits]
    coefficient_count = coefficients.size
    def residual(params):
        weights, kappas = _decode(params, x)
        prediction = np.sum(weights * np.exp(-u[:, None] * kappas[None, :]), axis=1)
        # Ridge acts only on temperature/composition slopes; intercepts retain
        # the global simplex initialization and are not pulled toward zero.
        slopes = params[:coefficient_count].reshape(N_GASES - 1, -1)[:, 1:].ravel()
        return np.r_[prediction - target, math.sqrt(regularization) * slopes]

    result = least_squares(
        residual, initial, method="trf", max_nfev=max_nfev,
        ftol=1e-10, xtol=1e-10, gtol=1e-10,
    )
    if not result.success:
        raise RuntimeError(f"smooth composition fit failed: {result.message}")
    weights, kappas = _decode(result.x, x)
    if (np.any(weights < 0) or not np.allclose(weights.sum(axis=1), 1.0, atol=1e-12)
            or np.any(kappas < 0) or np.any(np.diff(kappas) < 0)
            or np.any(kappas > 1000.0)):
        raise AssertionError("smooth model violated WSGG physical parameter constraints")
    return result, transform, weights, kappas


def _evaluate_alpha(train, validation, regularization, max_nfev=10000):
    domain = calibration_domain(train)
    result, transform, _, kappas = _fit_smooth(train, regularization, max_nfev)
    prediction = _predict(validation, *_decode(result.x, _features(validation, transform)), domain)
    return prediction


def _cross_validate(rows, seed):
    outer_folds = _folds(rows, N_SPLITS_OUTER, seed + "-outer")
    row_positions = {id(row): index for index, row in enumerate(rows)}
    fold_reports = []
    nested_selected_predictions = np.empty(len(rows), dtype=float)
    baseline_predictions = np.empty(len(rows), dtype=float)
    selected_alphas = []

    for outer_index, (outer_train, outer_validation) in enumerate(outer_folds):
        alpha_inner_scores = {}
        inner_count = min(N_SPLITS_INNER, len({condition_key(row) for row in outer_train}))
        for alpha in REGULARIZATION_GRID:
            sq_error = 0.0
            sample_count = 0
            for inner_train, inner_validation in _folds(
                outer_train, inner_count, f"{seed}-outer-{outer_index}-inner",
            ):
                pred = _evaluate_alpha(inner_train, inner_validation, alpha)
                target = np.asarray([r["tau_reference"] for r in inner_validation])
                sq_error += float(np.dot(pred - target, pred - target))
                sample_count += len(inner_validation)
            alpha_inner_scores[alpha] = math.sqrt(sq_error / sample_count)

        selected_alpha = min(alpha_inner_scores, key=alpha_inner_scores.get)
        selected_alphas.append(selected_alpha)
        domain = calibration_domain(outer_train)
        result, transform, _, kappas = _fit_smooth(outer_train, selected_alpha)
        selected_pred = _predict(
            outer_validation,
            *_decode(result.x, _features(outer_validation, transform)),
            domain,
        )
        global_weights, global_kappas, _ = fit_model(outer_train, N_GASES, 0.0, 1000.0, 10000)
        baseline_pred = _predict(outer_validation, global_weights, global_kappas, domain)

        for row, pred in zip(outer_validation, selected_pred):
            nested_selected_predictions[row_positions[id(row)]] = pred
        for row, pred in zip(outer_validation, baseline_pred):
            baseline_predictions[row_positions[id(row)]] = pred
        fold_reports.append({
            "fold": outer_index,
            "train_group_count": len({condition_key(r) for r in outer_train}),
            "validation_group_count": len({condition_key(r) for r in outer_validation}),
            "selected_regularization": selected_alpha,
            "inner_cv_rmse_by_regularization": {
                str(alpha): score for alpha, score in alpha_inner_scores.items()
            },
            "validation_rmse_tau": _summarize(outer_validation, selected_pred)["rmse_tau"],
        })

    return {
        "baseline_predictions": baseline_predictions,
        "nested_predictions": nested_selected_predictions,
        "folds": fold_reports,
        "selected_regularization_by_outer_fold": selected_alphas,
    }


def evaluate(input_csv: Path, output_json: Path, seed="p3b-smooth-composition-v1"):
    rows = load_observations(input_csv)
    cv = _cross_validate(rows, seed)
    baseline = _summarize(rows, cv["baseline_predictions"])
    smooth = _summarize(rows, cv["nested_predictions"])

    by_temperature = {}
    for label, predicate in (("T_le_1200K", lambda r: r["temperature_K"] <= 1200),
                             ("T_gt_1200K", lambda r: r["temperature_K"] > 1200)):
        indices = [i for i, row in enumerate(rows) if predicate(row)]
        subset = [rows[i] for i in indices]
        by_temperature[label] = {
            "global": _summarize(subset, cv["baseline_predictions"][indices]),
            "smooth_composition": _summarize(subset, cv["nested_predictions"][indices]),
        }

    by_composition = {}
    compositions = sorted({(row["x_co2"], row["x_h2o"]) for row in rows})
    for x_co2, x_h2o in compositions:
        indices = [
            i for i, row in enumerate(rows)
            if row["x_co2"] == x_co2 and row["x_h2o"] == x_h2o
        ]
        subset = [rows[i] for i in indices]
        by_composition[f"CO2={x_co2:g};H2O={x_h2o:g}"] = {
            "condition_group_count": len({condition_key(row) for row in subset}),
            "global": _summarize(subset, cv["baseline_predictions"][indices]),
            "smooth_composition": _summarize(subset, cv["nested_predictions"][indices]),
        }

    # Refit on all rows using the median inner-selected regularization for a
    # descriptive final coefficient table; CV scores above remain out-of-fold.
    final_alpha = float(np.median(cv["selected_regularization_by_outer_fold"]))
    final_result, final_transform, _, final_kappas = _fit_smooth(rows, final_alpha)
    reference_rows = [
        {"temperature_K": temperature, "x_co2": x_co2, "x_h2o": x_h2o}
        for temperature in sorted({row["temperature_K"] for row in rows})
        for x_co2, x_h2o in sorted({(row["x_co2"], row["x_h2o"]) for row in rows})
    ]
    final_weights, _ = _decode(final_result.x, _features(reference_rows, final_transform))
    final_coeff = final_result.x[:(N_GASES - 1) * (len(FEATURE_NAMES) + 1)].reshape(
        N_GASES - 1, len(FEATURE_NAMES) + 1,
    )

    report = {
        "status": "offline_experiment_only_requires_independent_validation",
        "method": "softmax WSGG weights with degree-2 temperature and linear CO2/H2O mole-fraction logits; shared ordered kappas; ridge penalty on non-intercept coefficients",
        "input": str(input_csv),
        "input_sha256": hashlib.sha256(input_csv.read_bytes()).hexdigest(),
        "condition_group_count": len({condition_key(row) for row in rows}),
        "cross_validation": {
            "outer_folds": N_SPLITS_OUTER,
            "inner_folds": N_SPLITS_INNER,
            "grouping": "complete (temperature_K, pressure_atm, x_co2, x_h2o) groups; all path rows stay in one fold",
            "seed": seed,
            "regularization_grid": list(REGULARIZATION_GRID),
            "selected_regularization_by_outer_fold": cv["selected_regularization_by_outer_fold"],
            "folds": cv["folds"],
        },
        "out_of_fold_metrics": {
            "global_shared_weights": baseline,
            "smooth_temperature_composition_weights": smooth,
            "by_temperature": by_temperature,
            "by_composition": by_composition,
        },
        "final_refit_descriptive_parameters": {
            "regularization": final_alpha,
            "feature_names": list(FEATURE_NAMES),
            "feature_transform": {
                "mean_temperature_K_x_co2_x_h2o": final_transform["mean"].tolist(),
                "scale_temperature_K_x_co2_x_h2o": final_transform["scale"].tolist(),
                "temperature_quadratic_mean": final_transform["quadratic_mean"],
                "temperature_quadratic_scale": final_transform["quadratic_scale"],
            },
            "free_logit_coefficients_intercept_then_features": final_coeff.tolist(),
            "weights_by_reference_temperature_and_composition": [
                {
                    "temperature_K": row["temperature_K"],
                    "x_co2": row["x_co2"],
                    "x_h2o": row["x_h2o"],
                    "weights": weight.tolist(),
                }
                for row, weight in zip(reference_rows, final_weights)
            ],
            "shared_kappa_atm_inv_m_inv": final_kappas.tolist(),
            "weights_nonnegative_and_sum_to_one": bool(
                np.all(final_weights >= 0)
                and np.allclose(final_weights.sum(axis=1), 1.0, atol=1e-12)
            ),
            "kappas_nonnegative_ordered_and_bounded_0_1000": bool(
                np.all(final_kappas >= 0)
                and np.all(np.diff(final_kappas) >= 0)
                and np.all(final_kappas <= 1000)
            ),
        },
        "production_solver_changed": False,
        "leckner_fast_path_changed": False,
        "provisional_status_removed": False,
        "limitations": [
            "The data contain only six temperatures and three compositions; a quadratic temperature surface and linear composition terms are exploratory.",
            "Nested grouped CV estimates interpolation among represented axis ranges; it does not validate extrapolation or unseen joint-space regions.",
            "Weights may absorb temperature/composition-dependent spectral physics while kappas are shared; coefficient interpretability is not established.",
            "The reference inherits incompleteness and pseudo-Voigt line-shape uncertainty; independent spectral validation is still required.",
            "This prototype is offline only and makes no production or Leckner changes.",
        ],
    }
    output_json.parent.mkdir(parents=True, exist_ok=True)
    output_json.write_text(json.dumps(report, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-csv", type=Path, default=Path("data/hitemp_narrowband_tau_reference.csv"))
    parser.add_argument("--output", type=Path, default=Path("reports/hitemp_wsgg_smooth_composition_cv.json"))
    args = parser.parse_args()
    report = evaluate(args.input_csv, args.output)
    print(json.dumps({
        "global_oof": report["out_of_fold_metrics"]["global_shared_weights"],
        "smooth_composition_oof": report["out_of_fold_metrics"]["smooth_temperature_composition_weights"],
        "by_temperature": report["out_of_fold_metrics"]["by_temperature"],
        "selected_regularization_by_fold": report["cross_validation"]["selected_regularization_by_outer_fold"],
        "output": str(args.output),
    }, indent=2))


if __name__ == "__main__":
    main()
