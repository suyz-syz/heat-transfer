#!/usr/bin/env python3
"""Fit WSGG to Marzouk (2025) public EM2C-SNB emissivity tables.

This is a literature-reference benchmark, NOT a HITEMP-LBL run. Input files are
the .dat files from https://data.mendeley.com/datasets/x5wjzk6sjs/1
(DOI: 10.17632/x5wjzk6sjs.1; CC BY 4.0). The published dataset uses the EM2C
statistical narrow-band (SNB) model at total pressure 1 atm; its independent
axis is pressure-pathlength in atm*m, not total pressure.

Outputs include shared-kappa WSGG fits for N=3,4,5, polynomial coefficients for
the temperature-dependent weights, and held-out path-length emissivity errors.
If --wall-temperature-k is supplied, a deliberately simplified black-wall
flux-proxy error is also reported: delta_q = delta_epsilon * sigma *
abs(Tgas**4 - Twall**4). It is NOT a general non-gray wall heat-flux solution.
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import statistics
from pathlib import Path

SIGMA = 5.670374419e-8
TEMPERATURE_MIN = 300.0
TEMPERATURE_MAX = 2900.0


def parse_emissivity_table(path: Path) -> dict:
    """Parse a published EM2C-SNB .dat table into temperature/pathlength slices."""
    rows = []
    with path.open(encoding="utf-8-sig", errors="strict") as stream:
        for line_no, line in enumerate(stream, 1):
            fields = line.replace(",", " ").split()
            if len(fields) < 3:
                continue
            # The source file contains descriptive metadata before its numeric
            # table. Only physical records have T on the published 300..2900 K grid.
            for start in range(len(fields) - 2):
                try:
                    pl, temp, eps = map(float, fields[start:start + 3])
                except ValueError:
                    continue
                if (pl > 0 and TEMPERATURE_MIN <= temp <= TEMPERATURE_MAX
                        and abs((temp - TEMPERATURE_MIN) / 25.0 -
                                round((temp - TEMPERATURE_MIN) / 25.0)) < 1e-8
                        and 0.0 <= eps <= 1.0):
                    rows.append((pl, temp, eps, line_no))
                    break
    if not rows:
        raise ValueError(f"no valid emissivity records found in {path}")
    by_temp: dict[float, dict[float, float]] = {}
    for pl, temp, eps, _ in rows:
        if pl in by_temp.setdefault(temp, {}):
            raise ValueError(f"duplicate (T, PL) record in {path}: T={temp}, PL={pl}")
        by_temp[temp][pl] = eps
    temperatures = sorted(by_temp)
    common_pl = sorted(set.intersection(*(set(by_temp[t]) for t in temperatures)))
    if len(temperatures) < 5 or len(common_pl) < 8:
        raise ValueError(
            f"insufficient grid in {path}: {len(temperatures)} temperatures, "
            f"{len(common_pl)} common pressure-pathlength values"
        )
    # Ignore partial/non-common path-length columns rather than silently mixing grids.
    return {
        "source_file": path.name,
        "temperature_K": temperatures,
        "pressure_pathlength_atm_m": common_pl,
        "emissivity": {
            str(t): [by_temp[t][pl] for pl in common_pl] for t in temperatures
        },
    }


def fit_nonnegative_weights(basis: list[list[float]], targets: list[float],
                            iterations: int = 4000) -> list[float]:
    n = len(basis[0])
    weights = [1.0 / n] * n
    for _ in range(iterations):
        change = 0.0
        for j in range(n):
            numerator = denominator = 0.0
            for row, target in zip(basis, targets):
                residual = target - sum(weights[k] * row[k] for k in range(n) if k != j)
                numerator += row[j] * residual
                denominator += row[j] * row[j]
            value = max(0.0, numerator / denominator) if denominator else 0.0
            change = max(change, abs(value - weights[j]))
            weights[j] = value
        total = sum(weights)
        if total > 1.0:
            weights = [v / total for v in weights]
        if change < 1e-11:
            break
    return weights


def basis_for(path_lengths: list[float], kappas: list[float]) -> list[list[float]]:
    return [[-math.expm1(-k * pl) for k in kappas] for pl in path_lengths]


def choose_shared_kappas(data: dict, n_gases: int, train_indices: list[int],
                         grid_size: int = 140) -> list[float]:
    pl = data["pressure_pathlength_atm_m"]
    log_min, log_max = math.log(1e-4), math.log(1e3)
    candidates = [math.exp(log_min + i * (log_max - log_min) / (grid_size - 1))
                  for i in range(grid_size)]
    selected: list[float] = []
    all_targets = {
        t: [data["emissivity"][str(t)][i] for i in train_indices]
        for t in data["temperature_K"]
    }
    train_pl = [pl[i] for i in train_indices]
    for _ in range(n_gases):
        best_k, best_sse = None, math.inf
        for candidate in candidates:
            if any(abs(math.log(candidate / old)) < 1e-9 for old in selected):
                continue
            trial = sorted((*selected, candidate))
            basis = basis_for(train_pl, trial)
            sse = 0.0
            for t, targets in all_targets.items():
                weights = fit_nonnegative_weights(basis, targets, iterations=120)
                sse += sum((sum(w * b for w, b in zip(weights, row)) - y) ** 2
                           for row, y in zip(basis, targets))
            if sse < best_sse:
                best_k, best_sse = candidate, sse
        if best_k is None:
            raise RuntimeError("could not select a distinct shared kappa")
        selected.append(best_k)
    return sorted(selected)


def solve_linear(matrix: list[list[float]], rhs: list[float]) -> list[float]:
    a = [row[:] + [value] for row, value in zip(matrix, rhs)]
    n = len(rhs)
    for col in range(n):
        pivot = max(range(col, n), key=lambda r: abs(a[r][col]))
        if abs(a[pivot][col]) < 1e-14:
            raise ValueError("singular polynomial fit")
        a[col], a[pivot] = a[pivot], a[col]
        scale = a[col][col]
        a[col] = [v / scale for v in a[col]]
        for row in range(n):
            if row == col:
                continue
            factor = a[row][col]
            a[row] = [v - factor * p for v, p in zip(a[row], a[col])]
    return [a[i][-1] for i in range(n)]


def polynomial_fit(x: list[float], y: list[float], degree: int = 4) -> list[float]:
    degree = min(degree, len(x) - 1)
    powers = [[v ** k for k in range(2 * degree + 1)] for v in x]
    matrix = [[sum(p[k + j] for p in powers) for j in range(degree + 1)]
              for k in range(degree + 1)]
    rhs = [sum((v ** k) * yy for v, yy in zip(x, y)) for k in range(degree + 1)]
    return solve_linear(matrix, rhs)


def polyval(coefficients: list[float], x: float) -> float:
    result = 0.0
    for coefficient in reversed(coefficients):
        result = result * x + coefficient
    return result


def run_fit(data: dict, n_gases: int, wall_temperature_k: float | None) -> dict:
    pl = data["pressure_pathlength_atm_m"]
    temperatures = data["temperature_K"]
    train_indices = [i for i in range(len(pl)) if i % 2 == 0]
    test_indices = [i for i in range(len(pl)) if i % 2 == 1]
    kappas = choose_shared_kappas(data, n_gases, train_indices)
    train_pl = [pl[i] for i in train_indices]
    test_pl = [pl[i] for i in test_indices]
    train_basis = basis_for(train_pl, kappas)
    test_basis = basis_for(test_pl, kappas)

    weights_by_temp = {}
    test_records = []
    for temp in temperatures:
        targets = data["emissivity"][str(temp)]
        weights = fit_nonnegative_weights(train_basis, [targets[i] for i in train_indices])
        weights_by_temp[temp] = weights
        for i, row in zip(test_indices, test_basis):
            predicted = sum(w * b for w, b in zip(weights, row))
            actual = targets[i]
            relative = abs(predicted - actual) / abs(actual) if abs(actual) > 1e-8 else None
            q_error = None
            if wall_temperature_k is not None:
                q_error = abs(predicted - actual) * SIGMA * abs(
                    temp**4 - wall_temperature_k**4
                )
            test_records.append({
                "temperature_K": temp,
                "pressure_pathlength_atm_m": pl[i],
                "actual_emissivity": actual,
                "predicted_emissivity": predicted,
                "abs_emissivity_error": abs(predicted - actual),
                "relative_emissivity_error": relative,
                "black_wall_flux_proxy_abs_error_W_m2": q_error,
            })

    # Regress per-state weights as quartic polynomials in T/1000.
    x = [temp / 1000.0 for temp in temperatures]
    poly = [polynomial_fit(x, [weights_by_temp[t][j] for t in temperatures], 4)
            for j in range(n_gases)]
    poly_records = []
    for temp in temperatures:
        pred_weights = [max(0.0, polyval(poly[j], temp / 1000.0))
                        for j in range(n_gases)]
        total = sum(pred_weights)
        if total > 1.0:
            pred_weights = [w / total for w in pred_weights]
        for i in test_indices:
            actual = data["emissivity"][str(temp)][i]
            predicted = sum(w * b for w, b in zip(pred_weights, test_basis[test_indices.index(i)]))
            relative = abs(predicted - actual) / abs(actual) if abs(actual) > 1e-8 else None
            q_error = None
            if wall_temperature_k is not None:
                q_error = abs(predicted - actual) * SIGMA * abs(
                    temp**4 - wall_temperature_k**4
                )
            poly_records.append({
                "temperature_K": temp, "pressure_pathlength_atm_m": pl[i],
                "actual_emissivity": actual, "predicted_emissivity": predicted,
                "abs_emissivity_error": abs(predicted - actual),
                "relative_emissivity_error": relative,
                "black_wall_flux_proxy_abs_error_W_m2": q_error,
            })

    def metrics(records: list[dict]) -> dict:
        valid_rel = [r["relative_emissivity_error"] for r in records
                     if r["relative_emissivity_error"] is not None]
        flux = [r["black_wall_flux_proxy_abs_error_W_m2"] for r in records
                if r["black_wall_flux_proxy_abs_error_W_m2"] is not None]
        return {
            "heldout_points": len(records),
            "emissivity_MAPE_percent": 100.0 * statistics.mean(valid_rel) if valid_rel else None,
            "max_abs_emissivity_error": max(r["abs_emissivity_error"] for r in records),
            "max_black_wall_flux_proxy_error_W_m2": max(flux) if flux else None,
            "worst_emissivity_case": max(records, key=lambda r: r["abs_emissivity_error"]),
        }

    return {
        "n_gases": n_gases,
        "shared_kappa_per_atm_m_inverse": kappas,
        "weight_polynomial_basis": "a_j(T) = sum(c[j,k] * (T/1000 K)^k), k=0..4",
        "weight_polynomial_coefficients_low_to_high": poly,
        "state_specific_weight_holdout_metrics": metrics(test_records),
        "temperature_polynomial_weight_holdout_metrics": metrics(poly_records),
        "limitations": [
            "Ground truth is published EM2C-SNB total emissivity, not raw HITEMP LBL.",
            "Total pressure is fixed at 1 atm in the source dataset; PL is pressure times path length.",
            "Heat-flux value is only an equivalent black-wall gray flux proxy if wall temperature is supplied.",
            "The polynomial weights are clipped/renormalized at evaluation; inspect polynomial behavior before deployment.",
        ],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", action="append", required=True, type=Path,
                        help="one or more published R=..._totalEmissivities_90x105.dat files")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--wall-temperature-k", type=float, default=None,
                        help="optional wall temperature for a clearly labelled gray flux proxy")
    args = parser.parse_args()
    if args.wall_temperature_k is not None and (
        not math.isfinite(args.wall_temperature_k) or args.wall_temperature_k < 0
    ):
        parser.error("--wall-temperature-k must be finite and nonnegative")
    report = {
        "benchmark": "Marzouk 2025 public EM2C-SNB emissivity dataset",
        "doi": "10.17632/x5wjzk6sjs.1",
        "source_url": "https://data.mendeley.com/datasets/x5wjzk6sjs/1",
        "method": "hold out alternate pressure-pathlength samples; shared kappa across temperatures per composition",
        "wall_temperature_k": args.wall_temperature_k,
        "datasets": [],
    }
    for path in args.input:
        data = parse_emissivity_table(path)
        report["datasets"].append({
            "source_file": path.name,
            "temperature_range_K": [min(data["temperature_K"]), max(data["temperature_K"])],
            "pressure_pathlength_range_atm_m": [
                min(data["pressure_pathlength_atm_m"]), max(data["pressure_pathlength_atm_m"])
            ],
            "results": [run_fit(data, n, args.wall_temperature_k) for n in (3, 4, 5)],
        })
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(f"Wrote literature benchmark report: {args.output}")


if __name__ == "__main__":
    main()
