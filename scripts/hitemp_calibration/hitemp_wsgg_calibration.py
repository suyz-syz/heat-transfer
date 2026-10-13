"""Reproducible band-limited HITEMP/TIPS WSGG calibration.

The reference is a pseudo-Voigt LBL model and is explicitly not a
metrology-grade Hartmann-Tran implementation. Input CSVs are supplied by the
user; they are not bundled here. Requires numpy, pandas, and scipy.
"""
from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.optimize import least_squares, lsq_linear

C2_CM_K = 1.438776877
T_REF_K = 296.0
K_B = 1.380649e-23
N_A = 6.02214076e23
C_LIGHT = 299792458.0
H_PLANCK = 6.62607015e-34
SPECIES = {1: ("H2O", 18.01528), 2: ("CO2", 44.0095)}
COMPOSITIONS = ((0.12, 0.08), (0.08, 0.04), (0.20, 0.10))
TEMPERATURES_K = (600.0, 1000.0, 1200.0, 1400.0, 1800.0, 2400.0)
PRESSURES_ATM = (0.3, 1.0, 3.0)
PATHS_M = tuple(float(x) for x in np.geomspace(0.05, 5.0, 12))


def sha256_file(path: str | Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def load_inputs(line_path: str | Path, tips_path: str | Path):
    lines = pd.read_csv(line_path)
    required = {"molec_id", "local_iso_id", "nu", "sw", "a", "gamma_air",
                "gamma_self", "elower", "n_air", "delta_air"}
    if not required.issubset(lines.columns):
        raise ValueError(f"line CSV missing columns: {sorted(required - set(lines.columns))}")
    tips = pd.read_csv(tips_path)
    if not {"molecule", "isotope", "temperature_K", "Q"}.issubset(tips.columns):
        raise ValueError("TIPS CSV requires molecule,isotope,temperature_K,Q")
    numeric = list(required)
    if not np.isfinite(lines[numeric].to_numpy(dtype=float)).all():
        raise ValueError("line CSV contains non-finite numeric values")
    if (lines["nu"].le(0).any() or lines["sw"].lt(0).any()
            or lines["gamma_air"].lt(0).any() or lines["gamma_self"].lt(0).any()):
        raise ValueError("line CSV contains invalid frequency/strength/broadening")
    if not np.isfinite(tips[["temperature_K", "Q"]].to_numpy(dtype=float)).all():
        raise ValueError("TIPS contains non-finite values")
    if (tips["temperature_K"].le(0).any() or tips["Q"].le(0).any()):
        raise ValueError("TIPS temperatures and Q values must be positive")
    tips_map = {}
    for (mol, iso), g in tips.groupby(["molecule", "isotope"]):
        g = g.sort_values("temperature_K")
        if g["temperature_K"].duplicated().any():
            raise ValueError(f"duplicate TIPS temperatures for {mol}:{iso}")
        tips_map[(int(mol), int(iso))] = (
            g["temperature_K"].to_numpy(float), g["Q"].to_numpy(float))
    pairs = set(zip(lines["molec_id"].astype(int), lines["local_iso_id"].astype(int)))
    missing = sorted(p for p in pairs if p not in tips_map)
    if missing:
        raise ValueError(f"missing TIPS isotopologues: {missing}")
    # This report targets only H2O/CO2, and only lines with finite wings into the band.
    lines = lines[(lines["molec_id"].isin(SPECIES))
                  & (lines["nu"] >= 1975.0) & (lines["nu"] <= 2425.0)].copy()
    lines = lines.sort_values("nu").reset_index(drop=True)
    if lines.empty:
        raise ValueError("no H2O/CO2 lines overlap the selected band and wing margin")
    return lines, tips_map


def _q_value(tips_map, mol: int, iso: int, temperature: float) -> float:
    tx, qx = tips_map[(mol, iso)]
    if temperature < tx[0] or temperature > tx[-1]:
        raise ValueError(f"TIPS table for {mol}:{iso} does not cover {temperature:g} K")
    return float(np.exp(np.interp(np.log(temperature), np.log(tx), np.log(qx))))


def lbl_spectrum(lines, tips_map, temperature: float, pressure: float,
                 x_co2: float, x_h2o: float, *, step: float = 0.01,
                 wing: float = 25.0):
    if step <= 0 or pressure <= 0 or temperature <= 0:
        raise ValueError("step, pressure, and temperature must be positive")
    wn = np.arange(2000.0, 2400.0 + step * 0.5, step)
    alpha = np.zeros(wn.size, dtype=float)
    mol = lines["molec_id"].to_numpy(int)
    iso = lines["local_iso_id"].to_numpy(int)
    xmol = np.where(mol == 1, x_h2o, x_co2)
    nu = lines["nu"].to_numpy(float)
    sw = lines["sw"].to_numpy(float)
    elower = lines["elower"].to_numpy(float)
    ga = lines["gamma_air"].to_numpy(float)
    gs = lines["gamma_self"].to_numpy(float)
    n_air = lines["n_air"].to_numpy(float)
    delta = lines["delta_air"].to_numpy(float)
    qratio = np.array([
        _q_value(tips_map, int(m), int(i), T_REF_K) /
        _q_value(tips_map, int(m), int(i), temperature)
        for m, i in zip(mol, iso)
    ])
    boltz = np.exp(-C2_CM_K * elower * (1.0 / temperature - 1.0 / T_REF_K))
    stim_t = -np.expm1(-C2_CM_K * nu / temperature)
    stim_ref = -np.expm1(-C2_CM_K * nu / T_REF_K)
    strength = sw * qratio * boltz * stim_t / stim_ref
    # HITRAN delta_air is an air-broadening shift; self-shift is not in this CSV.
    center = nu + delta * pressure * (1.0 - xmol)
    gamma = pressure * (T_REF_K / temperature) ** n_air * (
        ga * (1.0 - xmol) + gs * xmol)
    mass_kg = np.where(mol == 1, SPECIES[1][1], SPECIES[2][1]) / 1000.0 / N_A
    sigma_d = center * np.sqrt(K_B * temperature /
                               (mass_kg * C_LIGHT ** 2))
    number_density = xmol * pressure * 101325.0 / (K_B * temperature)
    use = ((center + wing >= 2000.0) & (center - wing <= 2400.0)
           & (strength > 0))
    center, gamma, sigma_d = center[use], gamma[use], sigma_d[use]
    strength, number_density = strength[use], number_density[use]
    batch = 32
    root = math.sqrt(4.0 * math.log(2.0) / math.pi)
    sqrt2ln2 = math.sqrt(2.0 * math.log(2.0))
    for start in range(0, center.size, batch):
        end = min(start + batch, center.size)
        lo = max(0, int(math.floor((center[start:end].min() - wing - 2000.0) / step)))
        hi = min(wn.size, int(math.ceil(
            (center[start:end].max() + wing - 2000.0) / step)) + 1)
        wsub = wn[lo:hi]
        x = wsub[None, :] - center[start:end, None]
        fg = 2.0 * sqrt2ln2 * sigma_d[start:end, None]
        fl = 2.0 * gamma[start:end, None]
        f = (fg**5 + 2.69269*fg**4*fl + 2.42843*fg**3*fl**2
             + 4.47163*fg**2*fl**3 + 0.07842*fg*fl**4) ** 0.2
        f = np.maximum(f, 1e-30)
        ratio = fl / f
        eta = np.clip(1.36603*ratio - 0.47719*ratio**2 + 0.11116*ratio**3, 0.0, 1.0)
        gaussian = root / f * np.exp(-4.0 * math.log(2.0) * (x / f)**2)
        lorentz = (f / (2.0 * math.pi)) / (x**2 + (f / 2.0)**2)
        profile = eta * lorentz + (1.0 - eta) * gaussian
        profile = np.where(np.abs(x) <= wing, profile, 0.0)
        alpha[lo:hi] += np.sum(
            (strength[start:end] * number_density[start:end] * 1e-4)[:, None] * profile,
            axis=0)
    return wn, alpha


def band_emissivity(wn, alpha, temperature: float, path_m: float) -> float:
    mid = 0.5 * (wn[:-1] + wn[1:])
    planck = mid**3 / np.expm1(C2_CM_K * mid / temperature)
    absorptance = -np.expm1(-0.5 * (alpha[:-1] + alpha[1:]) * path_m)
    return float(np.sum(planck * absorptance * np.diff(wn)) /
                 np.sum(planck * np.diff(wn)))


def simplex_weights(logits) -> np.ndarray:
    """Stable softmax; produces weights >= 0 whose sum is exactly one numerically."""
    z = np.asarray(logits, dtype=float)
    z = z - np.max(z)
    w = np.exp(z)
    return w / w.sum()


def constrained_bernstein_coefficients(temperatures, weights, degree: int = 3):
    """Nonnegative Bernstein coefficients; normalized gas weights remain on simplex."""
    t = np.asarray(temperatures, dtype=float)
    w = np.asarray(weights, dtype=float)
    if w.ndim != 2 or w.shape[0] != t.size or np.any(w < 0):
        raise ValueError("weights must be a nonnegative (temperature, gas) matrix")
    if not np.allclose(w.sum(axis=1), 1.0, atol=1e-8):
        raise ValueError("input weights must sum to one at every temperature")
    theta = (t - t.min()) / (t.max() - t.min())
    basis = np.stack([math.comb(degree, j) * theta**j * (1-theta)**(degree-j)
                      for j in range(degree + 1)], axis=1)
    coeff = np.stack([
        lsq_linear(basis, w[:, j], bounds=(0.0, np.inf)).x
        for j in range(w.shape[1])
    ])
    return coeff


def evaluate_bernstein_weights(temperature: float, temperature_range, coefficients):
    lo, hi = temperature_range
    if not lo <= temperature <= hi:
        raise ValueError("temperature outside calibrated Bernstein interval")
    c = np.asarray(coefficients, dtype=float)
    degree = c.shape[1] - 1
    x = (temperature - lo) / (hi - lo)
    basis = np.array([math.comb(degree, j) * x**j * (1-x)**(degree-j)
                      for j in range(degree + 1)])
    raw = c @ basis
    return raw / raw.sum()


def fit_global_wsgg(rows, n_gases: int):
    """Fit shared pressure-normalized kappas and per-temperature simplex weights."""
    temperatures = sorted({float(r["temperature_K"]) for r in rows})
    ti = {t: i for i, t in enumerate(temperatures)}
    y = np.array([r["target"] for r in rows], dtype=float)
    n_t = len(temperatures)

    def predict(params):
        kappas = np.exp(params[:n_gases])
        out = np.empty(len(rows))
        for idx, r in enumerate(rows):
            start = n_gases + ti[float(r["temperature_K"])] * (n_gases - 1)
            weights = simplex_weights(np.r_[params[start:start+n_gases-1], 0.0])
            out[idx] = np.sum(weights * -np.expm1(
                -kappas * float(r["pressure_atm"]) * float(r["path_m"])))
        return out

    best = None
    for scale in (0.3, 1.0, 3.0):
        initial = list(np.log(np.geomspace(0.02, 40.0, n_gases) * scale))
        initial.extend([0.0] * (n_t * (n_gases - 1)))
        lower = np.r_[np.full(n_gases, np.log(1e-5)),
                      np.full(n_t * (n_gases - 1), -12.0)]
        upper = np.r_[np.full(n_gases, np.log(1e3)),
                      np.full(n_t * (n_gases - 1), 12.0)]
        result = least_squares(lambda p: predict(p) - y, np.asarray(initial),
                               bounds=(lower, upper), max_nfev=1200,
                               ftol=1e-10, xtol=1e-10, gtol=1e-10)
        score = float(np.dot(result.fun, result.fun))
        if best is None or score < best[0]:
            best = (score, result.x)
    params = best[1]
    weights = {}
    for t, i in ti.items():
        start = n_gases + i * (n_gases - 1)
        weights[t] = simplex_weights(np.r_[params[start:start+n_gases-1], 0.0])
    return np.exp(params[:n_gases]), weights


def flux_metrics(rows, predictions):
    target = np.array([r["target"] for r in rows])
    pred = np.asarray(predictions)
    mape = float(np.mean(np.abs(pred-target) / np.maximum(target, 1e-8)) * 100.0)
    flux_bias = []
    for r, y, p in zip(rows, target, pred):
        wn = np.linspace(2000.0, 2400.0, 40001)
        z = C2_CM_K * wn / float(r["temperature_K"])
        spectral_exitance = (2.0 * math.pi * H_PLANCK * C_LIGHT**2 *
                             (100.0 * wn)**3 / np.expm1(z) * 100.0)
        band_exitance = float(np.trapezoid(spectral_exitance, wn))
        flux_bias.append((p-y) * band_exitance)
    return {
        "point_count": len(rows),
        "mape_percent": mape,
        "mean_absolute_band_flux_bias_W_m2": float(np.mean(np.abs(flux_bias))),
        "max_absolute_band_flux_bias_W_m2": float(np.max(np.abs(flux_bias))),
        "signed_mean_band_flux_bias_W_m2": float(np.mean(flux_bias)),
    }


def run_calibration(line_path, tips_path, output_path, *, release="user-supplied HITEMP/TIPS CSV"):
    lines, tips_map = load_inputs(line_path, tips_path)
    paths = np.asarray(PATHS_M)
    spectra = {}
    for t in TEMPERATURES_K:
        for comp in COMPOSITIONS:
            for pressure in PRESSURES_ATM:
                spectra[(t, comp, pressure)] = lbl_spectrum(
                    lines, tips_map, t, pressure, comp[0], comp[1], step=0.01)

    train, holdout = [], []
    for t in TEMPERATURES_K:
        for pressure in PRESSURES_ATM:
            wn, alpha = spectra[(t, COMPOSITIONS[0], pressure)]
            for path in paths:
                train.append({"temperature_K": t, "pressure_atm": pressure, "path_m": float(path),
                              "target": band_emissivity(wn, alpha, t, float(path))})
            for comp in COMPOSITIONS[1:]:
                wn_h, alpha_h = spectra[(t, comp, pressure)]
                for path in paths:
                    holdout.append({"temperature_K": t, "pressure_atm": pressure, "path_m": float(path),
                                    "target": band_emissivity(wn_h, alpha_h, t, float(path)),
                                    "composition_mole_fraction": {"CO2": comp[0], "H2O": comp[1]}})

    result_by_n = {}
    for n in (3, 4, 5):
        kappa, weights_by_t = fit_global_wsgg(train, n)
        degree = 3
        coeff = constrained_bernstein_coefficients(
            TEMPERATURES_K, np.stack([weights_by_t[t] for t in TEMPERATURES_K]), degree)

        def predict_rows(rows, polynomial):
            out = []
            for r in rows:
                t = float(r["temperature_K"])
                a = (evaluate_bernstein_weights(t, (TEMPERATURES_K[0], TEMPERATURES_K[-1]), coeff)
                     if polynomial else weights_by_t[t])
                out.append(float(np.sum(a * -np.expm1(
                    -kappa * float(r["pressure_atm"]) * float(r["path_m"])))))
            return np.asarray(out)

        result_by_n[str(n)] = {
            "global_kappa_atm_inv_m_inv": kappa.tolist(),
            "weights_by_temperature": {str(int(t)): weights_by_t[t].tolist() for t in TEMPERATURES_K},
            "bernstein_weights": {
                "degree": degree,
                "temperature_interval_K": [TEMPERATURES_K[0], TEMPERATURES_K[-1]],
                "coefficients_by_gas": coeff.tolist(),
                "constraint": "coefficients >= 0; normalized across gases at evaluation, so a_j >= 0 and sum(a_j)=1",
            },
            "direct_slice_weights": {
                "training": flux_metrics(train, predict_rows(train, False)),
                "holdout": flux_metrics(holdout, predict_rows(holdout, False)),
            },
            "bernstein_temperature_weights": {
                "training": flux_metrics(train, predict_rows(train, True)),
                "holdout": flux_metrics(holdout, predict_rows(holdout, True)),
            },
        }

    # Explicit convergence check: 0.01 vs 0.005 cm-1 for a representative condition.
    wn01, a01 = spectra[(1200.0, COMPOSITIONS[0], 1.0)]
    wn005, a005 = lbl_spectrum(lines, tips_map, 1200.0, 1.0, 0.12, 0.08, step=0.005)
    convergence = []
    for path in paths:
        e01 = band_emissivity(wn01, a01, 1200.0, float(path))
        e005 = band_emissivity(wn005, a005, 1200.0, float(path))
        convergence.append({"path_m": float(path), "eps_step_0p01": e01,
                            "eps_step_0p005": e005,
                            "relative_difference_percent": abs(e01-e005)/max(e005, 1e-8)*100.0})

    report = {
        "report_type": "HITEMP/TIPS-derived band-limited WSGG calibration",
        "status": "requires independent physical validation before engineering release",
        "provenance": {
            "release": release,
            "line_csv": str(line_path), "line_csv_sha256": sha256_file(line_path),
            "line_count_full_file": int(len(pd.read_csv(line_path))),
            "tips_csv": str(tips_path), "tips_csv_sha256": sha256_file(tips_path),
            "tips_rows": int(len(pd.read_csv(tips_path))),
        },
        "model": {
            "band_cm-1": [2000.0, 2400.0], "grid_step_cm-1": 0.01,
            "grid_point_count": 40001, "line_wing_cutoff_cm-1": 25.0,
            "line_profile": "pseudo-Voigt approximation",
            "pressure_shift": "nu0=nu+delta_air*P_atm*(1-x_molecule); self-shift unavailable",
            "temperature_broadening": "gamma=P*(Tref/T)^n_air*(gamma_air*(1-x)+gamma_self*x)",
            "kappa_unit": "atm^-1 m^-1",
            "emissivity_model": "sum_j a_j(T)*(1-exp(-kappa_j*P_atm*L_m))",
        },
        "training_design": {"temperatures_K": list(TEMPERATURES_K),
                            "pressures_atm": list(PRESSURES_ATM),
                            "composition_mole_fraction": {"CO2": 0.12, "H2O": 0.08},
                            "path_lengths_m": paths.tolist()},
        "holdout_design": {"temperatures_K": list(TEMPERATURES_K),
                           "pressures_atm": list(PRESSURES_ATM),
                           "compositions": [{"CO2": c[0], "H2O": c[1]} for c in COMPOSITIONS[1:]],
                           "path_lengths_m": paths.tolist(),
                           "holdout_type": "composition holdout within calibrated T/P domain"},
        "grid_convergence": {
            "temperature_K": 1200.0, "pressure_atm": 1.0,
            "standard_step_cm-1": 0.01, "reference_step_cm-1": 0.005,
            "max_relative_emissivity_difference_percent": max(
                x["relative_difference_percent"] for x in convergence),
            "per_path": convergence,
        },
        "results_by_n_gray_gases": result_by_n,
        "limitations": [
            "The supplied line list is a sample; completeness against a specific licensed HITEMP release was not independently authenticated.",
            "The LBL reference uses pseudo-Voigt profiles and a +/-25 cm-1 line-wing cutoff, not a validated Hartmann-Tran model.",
            "The 2000-2400 cm-1 band metrics are not total-spectrum emissivity or net wall-flux validation.",
            "Holdout varies composition but remains inside the calibrated temperature and pressure domain.",
            "Independent EM2C-SNB/experimental validation is still required before production use.",
        ],
    }
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    Path(output_path).write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    return report
