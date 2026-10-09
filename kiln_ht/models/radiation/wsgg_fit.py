"""Fit a WSGG approximation to LBL emissivity tables without external dependencies.

The fitter uses nonnegative coordinate descent for weights and greedy log-grid
search for absorption coefficients. It is a calibration utility, not a source of
coefficients by itself: input targets must come from a documented LBL/HITEMP run.
"""
from __future__ import annotations
from dataclasses import dataclass
import math
from typing import Sequence


@dataclass(frozen=True)
class WSGGFit:
    weights: tuple[float, ...]
    kappa: tuple[float, ...]
    rmse: float
    max_abs_error: float
    samples: int


def wsgg_emissivity(weights: Sequence[float], kappa: Sequence[float], path_length_m: float) -> float:
    if len(weights) != len(kappa) or not weights:
        raise ValueError("weights and kappa must have the same nonzero length")
    if path_length_m < 0 or any(not math.isfinite(x) for x in (*weights, *kappa)):
        raise ValueError("non-finite coefficients or negative path length")
    if any(w < 0 for w in weights) or any(k < 0 for k in kappa):
        raise ValueError("WSGG weights and absorption coefficients must be nonnegative")
    return sum(w * (-math.expm1(-k*path_length_m)) for w, k in zip(weights, kappa))


def fit_wsgg(
    path_lengths_m: Sequence[float], target_emissivities: Sequence[float],
    n_gases: int = 4, *, kappa_min: float = 1e-4, kappa_max: float = 1e3,
    grid_size: int = 180, iterations: int = 5000,
) -> WSGGFit:
    """Fit gray-gas weights and kappas to one condition slice.

    The target must be emissivity from LBL at a fixed T/composition/pressure.
    Coefficients are per condition; fitting T/composition dependence requires
    fitting each slice and then regressing each coefficient against those axes.
    """
    if len(path_lengths_m) != len(target_emissivities) or len(path_lengths_m) < n_gases + 1:
        raise ValueError("need matching arrays and at least n_gases+1 samples")
    if n_gases < 1 or grid_size < 2 or iterations < 1:
        raise ValueError("invalid fit controls")
    if any((not math.isfinite(l) or l < 0) for l in path_lengths_m):
        raise ValueError("path lengths must be finite and nonnegative")
    if any((not math.isfinite(e) or e < 0 or e > 1) for e in target_emissivities):
        raise ValueError("target emissivities must be finite and in [0, 1]")
    logs = [math.log(kappa_min) + i*(math.log(kappa_max)-math.log(kappa_min))/(grid_size-1)
            for i in range(grid_size)]
    candidates = [math.exp(x) for x in logs]
    # Select kappas greedily by residual correlation, then solve weights via projected
    # coordinate descent on a linear least-squares objective.
    selected = [candidates[0], candidates[-1]]
    while len(selected) < n_gases:
        best_k, best_score = candidates[0], -1.0
        for k in candidates:
            if any(abs(math.log(k/s)) < 1e-9 for s in selected):
                continue
            basis = [1-math.exp(-k*l) for l in path_lengths_m]
            score = abs(sum((e - sum(1/len(selected)*(1-math.exp(-s*l)) for s in selected))
                            * b for e, b in zip(target_emissivities, basis)))
            if score > best_score:
                best_k, best_score = k, score
        selected.append(best_k)
    kappas = sorted(selected)
    basis = [[1-math.exp(-k*l) for k in kappas] for l in path_lengths_m]
    weights = [1.0/n_gases] * n_gases
    # Coordinate updates with exact one-dimensional nonnegative least-squares steps.
    for _ in range(iterations):
        largest = 0.0
        for j in range(n_gases):
            numerator = denominator = 0.0
            for row, target in zip(basis, target_emissivities):
                residual = target - sum(weights[q]*row[q] for q in range(n_gases) if q != j)
                numerator += row[j]*residual
                denominator += row[j]*row[j]
            new = max(0.0, numerator/denominator) if denominator else 0.0
            largest = max(largest, abs(new-weights[j]))
            weights[j] = new
        # Convex gas weights must sum <= 1; scale if unconstrained fit exceeds 1.
        total = sum(weights)
        if total > 1:
            weights = [w/total for w in weights]
        if largest < 1e-12:
            break
    errors = [sum(w*b for w,b in zip(weights,row))-e for row,e in zip(basis,target_emissivities)]
    rmse = math.sqrt(sum(e*e for e in errors)/len(errors))
    return WSGGFit(tuple(weights), tuple(kappas), rmse, max(abs(e) for e in errors), len(errors))
