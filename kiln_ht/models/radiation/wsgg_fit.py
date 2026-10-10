"""Fit a WSGG approximation to LBL emissivity tables without external dependencies.

The fitter uses nonnegative coordinate descent for weights and greedy forward
selection on a log-spaced absorption-coefficient grid. It is a calibration
utility, not a source of coefficients by itself: targets must come from a
documented LBL/HITEMP calculation.
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
    if (not math.isfinite(path_length_m) or path_length_m < 0
            or any(not math.isfinite(x) for x in (*weights, *kappa))):
        raise ValueError("non-finite coefficients or negative path length")
    if any(w < 0 for w in weights) or any(k < 0 for k in kappa):
        raise ValueError("WSGG weights and absorption coefficients must be nonnegative")
    return sum(w * (-math.expm1(-k * path_length_m)) for w, k in zip(weights, kappa))


def _fit_weights(
    basis: Sequence[Sequence[float]], targets: Sequence[float], iterations: int
) -> tuple[list[float], float]:
    """Nonnegative least-squares coordinate descent with sum(weights) <= 1."""
    n_gases = len(basis[0])
    weights = [1.0 / n_gases] * n_gases
    for _ in range(iterations):
        largest = 0.0
        for j in range(n_gases):
            numerator = denominator = 0.0
            for row, target in zip(basis, targets):
                residual = target - sum(
                    weights[q] * row[q] for q in range(n_gases) if q != j
                )
                numerator += row[j] * residual
                denominator += row[j] * row[j]
            new = max(0.0, numerator / denominator) if denominator else 0.0
            largest = max(largest, abs(new - weights[j]))
            weights[j] = new
        total = sum(weights)
        if total > 1.0:
            weights = [w / total for w in weights]
        if largest < 1e-12:
            break
    sse = sum(
        (sum(w * b for w, b in zip(weights, row)) - target) ** 2
        for row, target in zip(basis, targets)
    )
    return weights, sse


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
    if n_gases < 1 or len(path_lengths_m) != len(target_emissivities) or len(path_lengths_m) < n_gases + 1:
        raise ValueError("need matching arrays and at least n_gases+1 samples")
    if grid_size < 2 or iterations < 1:
        raise ValueError("invalid fit controls")
    if (not math.isfinite(kappa_min) or not math.isfinite(kappa_max)
            or kappa_min <= 0 or kappa_max <= kappa_min):
        raise ValueError("kappa bounds must be finite, positive, and increasing")
    if any((not math.isfinite(length) or length < 0) for length in path_lengths_m):
        raise ValueError("path lengths must be finite and nonnegative")
    if any((not math.isfinite(e) or e < 0 or e > 1) for e in target_emissivities):
        raise ValueError("target emissivities must be finite and in [0, 1]")

    log_min, log_max = math.log(kappa_min), math.log(kappa_max)
    candidates = [
        math.exp(log_min + i * (log_max - log_min) / (grid_size - 1))
        for i in range(grid_size)
    ]

    # Forward selection: evaluate each candidate by the best nonnegative fit
    # available with the already-selected gases, rather than correlating against
    # an arbitrary equal-weight approximation.
    selected: list[float] = []
    for _ in range(n_gases):
        best_kappa, best_sse = None, math.inf
        for candidate in candidates:
            if any(abs(math.log(candidate / old)) < 1e-9 for old in selected):
                continue
            trial_kappas = sorted((*selected, candidate))
            trial_basis = [
                [(-math.expm1(-k * length)) for k in trial_kappas]
                for length in path_lengths_m
            ]
            _, sse = _fit_weights(trial_basis, target_emissivities, min(iterations, 100))
            if sse < best_sse:
                best_kappa, best_sse = candidate, sse
        assert best_kappa is not None
        selected.append(best_kappa)

    kappas = tuple(sorted(selected))
    basis = [
        [(-math.expm1(-k * length)) for k in kappas]
        for length in path_lengths_m
    ]
    weights, _ = _fit_weights(basis, target_emissivities, iterations)
    errors = [
        sum(w * b for w, b in zip(weights, row)) - target
        for row, target in zip(basis, target_emissivities)
    ]
    rmse = math.sqrt(sum(error * error for error in errors) / len(errors))
    return WSGGFit(
        tuple(weights), kappas, rmse, max(abs(error) for error in errors), len(errors)
    )
