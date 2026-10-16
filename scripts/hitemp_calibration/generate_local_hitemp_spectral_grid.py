"""Generate offline HITEMP/TIPS alpha_nu and transmittance condition grids.

The default grid is a spectral reference over the source-supported interior
1025--3975 cm-1. A 25 cm-1 line-wing margin is retained from the extracted
1000--4000 cm-1 source interval. This remains a band-limited pseudo-Voigt LBL
calculation, not a validated total-spectrum or production radiation model.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

C2 = 1.438776877
TREF = 296.0
KB = 1.380649e-23
NA = 6.02214076e23
CLIGHT = 299792458.0
SPECIES = {1: ("H2O", 18.01528), 2: ("CO2", 44.0095)}
CONDITIONS = (
    ("zero", 0.0, 0.0),
    ("trace_equal", 0.005, 0.005),
    ("low", 0.04, 0.08),
    ("nominal", 0.08, 0.12),
    ("high", 0.20, 0.20),
    ("co2_rich", 0.20, 0.05),
    ("h2o_rich", 0.05, 0.20),
)


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def load_tips(path: Path):
    table = pd.read_csv(path)
    result = {}
    for (mol, iso), group in table.groupby(["molecule", "isotope"]):
        group = group.sort_values("temperature_K")
        t = group["temperature_K"].to_numpy(float)
        q = group["Q"].to_numpy(float)
        if (len(t) < 2 or not np.isfinite(t).all() or not np.isfinite(q).all()
                or np.any(t <= 0) or np.any(q <= 0) or np.any(np.diff(t) <= 0)):
            raise ValueError(f"invalid TIPS table for {mol}:{iso}")
        result[(int(mol), int(iso))] = (t, q)
    return result


def q_at(tips, molecule, isotope, temperature):
    tx, qx = tips[(int(molecule), int(isotope))]
    if temperature < tx[0] or temperature > tx[-1]:
        raise ValueError(f"TIPS domain does not cover {temperature} K")
    return float(np.exp(np.interp(np.log(temperature), np.log(tx), np.log(qx))))


def absorption_spectrum(lines, tips, wn, temperature, pressure, x_co2, x_h2o,
                       wing=25.0, batch=32):
    """Return alpha [1/m] on wn for an ideal-gas, air/self-broadened mixture."""
    if pressure <= 0 or temperature <= 0 or min(x_co2, x_h2o) < 0 or x_co2 + x_h2o > 1:
        raise ValueError("invalid pressure, temperature, or mole fractions")
    alpha = np.zeros(wn.size, dtype=np.float64)
    for mol_id, (name, molar_mass) in SPECIES.items():
        xmol = x_h2o if mol_id == 1 else x_co2
        if xmol == 0:
            continue
        part = lines[lines.molec_id == mol_id]
        iso = part.local_iso_id.to_numpy(int)
        nu = part.nu.to_numpy(float)
        sw = part.sw.to_numpy(float)
        elower = part.elower.to_numpy(float)
        ga = part.gamma_air.to_numpy(float)
        gs = part.gamma_self.to_numpy(float)
        n_air = part.n_air.to_numpy(float)
        delta = part.delta_air.to_numpy(float)
        qratio = np.array([q_at(tips, mol_id, i, TREF) / q_at(tips, mol_id, i, temperature)
                           for i in iso])
        strength = (sw * qratio * np.exp(-C2 * elower * (1.0 / temperature - 1.0 / TREF))
                    * (-np.expm1(-C2 * nu / temperature))
                    / (-np.expm1(-C2 * nu / TREF)))
        center = nu + delta * pressure * (1.0 - xmol)
        gamma = pressure * (TREF / temperature) ** n_air * (ga * (1.0 - xmol) + gs * xmol)
        mass_kg = molar_mass / 1000.0 / NA
        sigma_d = center * np.sqrt(KB * temperature / (mass_kg * CLIGHT ** 2))
        number_density = xmol * pressure * 101325.0 / (KB * temperature)
        selected = ((center + wing >= wn[0]) & (center - wing <= wn[-1]) & (strength > 0))
        center, gamma, sigma_d = center[selected], gamma[selected], sigma_d[selected]
        strength = strength[selected]
        root = math.sqrt(4.0 * math.log(2.0) / math.pi)
        sqrt2ln2 = math.sqrt(2.0 * math.log(2.0))
        step = wn[1] - wn[0]
        for start in range(0, center.size, batch):
            end = min(start + batch, center.size)
            lo = max(0, int(math.floor((center[start:end].min() - wing - wn[0]) / step)))
            hi = min(wn.size, int(math.ceil((center[start:end].max() + wing - wn[0]) / step)) + 1)
            wsub = wn[lo:hi]
            x = wsub[None, :] - center[start:end, None]
            fg = 2.0 * sqrt2ln2 * sigma_d[start:end, None]
            fl = 2.0 * gamma[start:end, None]
            f = (fg**5 + 2.69269 * fg**4 * fl + 2.42843 * fg**3 * fl**2
                 + 4.47163 * fg**2 * fl**3 + 0.07842 * fg * fl**4) ** 0.2
            f = np.maximum(f, 1e-30)
            ratio = fl / f
            eta = np.clip(1.36603 * ratio - 0.47719 * ratio**2 + 0.11116 * ratio**3, 0.0, 1.0)
            gaussian = root / f * np.exp(-4.0 * math.log(2.0) * (x / f) ** 2)
            lorentz = (f / (2.0 * math.pi)) / (x**2 + (f / 2.0) ** 2)
            profile = eta * lorentz + (1.0 - eta) * gaussian
            profile = np.where(np.abs(x) <= wing, profile, 0.0)
            alpha[lo:hi] += np.sum((strength[start:end] * number_density * 1e-4)[:, None] * profile,
                                   axis=0)
    if not np.isfinite(alpha).all() or np.any(alpha < 0):
        raise ValueError("LBL returned non-finite or negative absorption coefficients")
    return alpha


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument("--temperature-step", type=float, default=300.0)
    parser.add_argument("--pressure-atm", type=float, nargs="+", default=[0.3, 1.0, 3.0])
    parser.add_argument("--nu-min", type=float, default=1025.0)
    parser.add_argument("--nu-max", type=float, default=3975.0)
    parser.add_argument("--nu-step", type=float, default=0.25)
    parser.add_argument("--wing", type=float, default=25.0)
    parser.add_argument("--path-m", type=float, nargs="+", default=[0.1, 1.0, 5.0])
    args = parser.parse_args()
    run_dir = args.run_dir.resolve()
    line_csv = run_dir / "hitemp2010_lines_1000_4000_full.csv"
    filtered_csv = run_dir / "hitemp2010_lines_sw_ge_1e-26.csv"
    tips_csv = run_dir / "tips_partition_sums_296_2400.csv"
    if not line_csv.is_file() or not filtered_csv.is_file() or not tips_csv.is_file():
        raise FileNotFoundError("run prepare_local_hitemp.py and filter_hitemp_lines_for_lbl.py first")
    if args.nu_step <= 0 or args.nu_max <= args.nu_min or args.temperature_step <= 0:
        raise ValueError("invalid grid spacing or interval")
    count = round((args.nu_max - args.nu_min) / args.nu_step)
    if not math.isclose(args.nu_min + count * args.nu_step, args.nu_max, abs_tol=1e-9):
        raise ValueError("nu-step must divide the spectral interval exactly")
    wn = np.linspace(args.nu_min, args.nu_max, count + 1)
    temperatures = np.arange(600.0, 2400.0 + args.temperature_step / 2, args.temperature_step)
    if temperatures[-1] != 2400.0:
        temperatures = np.append(temperatures[temperatures < 2400.0], 2400.0)
    if temperatures[0] != 600.0 or temperatures[-1] != 2400.0:
        raise ValueError("temperature-step must create a grid spanning 600 to 2400 K")
    pressures = sorted(set(float(x) for x in args.pressure_atm))
    paths = sorted(set(float(x) for x in args.path_m))
    if any(p <= 0 for p in pressures) or any(L <= 0 for L in paths):
        raise ValueError("pressure and path values must be positive")
    # The complete canonical CSV is retained; the documented thresholded
    # subset controls the exploratory grid's computational cost.
    lines = pd.read_csv(filtered_csv)
    tips = load_tips(tips_csv)
    present = set(zip(lines.molec_id.astype(int), lines.local_iso_id.astype(int)))
    if present - set(tips):
        raise ValueError(f"missing TIPS isotopologues: {sorted(present-set(tips))}")
    output = run_dir / "spectral_grid_alpha_tau.csv"
    fieldnames = ["temperature_K", "pressure_atm", "composition", "x_co2", "x_h2o",
                  "wavenumber_cm-1", "alpha_m-1"] + [f"tau_L{L:g}_m" for L in paths]
    total_cases = len(temperatures) * len(pressures) * len(CONDITIONS)
    report = {"created_utc": datetime.now(timezone.utc).isoformat(),
              "source_complete_line_csv_sha256": sha256_file(line_csv),
              "source_grid_subset_csv_sha256": sha256_file(filtered_csv),
              "grid_subset_minimum_sw_cm_per_molecule": 1e-26,
              "tips_csv_sha256": sha256_file(tips_csv),
              "reference_model": "pseudo-Voigt LBL; air/self broadening; ideal-gas number density",
              "spectral_grid_cm-1": {"min": args.nu_min, "max": args.nu_max, "step": args.nu_step,
                                     "points": len(wn), "line_wing_cutoff": args.wing},
              "source_line_center_interval_cm-1": [1000.0, 4000.0],
              "temperature_K": temperatures.tolist(), "pressure_atm": pressures,
              "compositions": [{"name": n, "x_co2": x, "x_h2o": y} for n, x, y in CONDITIONS],
              "path_m": paths, "condition_spectra": total_cases,
              "output_file": output.name,
              "limitations": ["Band-limited 1025-3975 cm-1; not full-spectrum radiation.",
                              "Pseudo-Voigt approximation is not independent high-resolution spectroscopy validation.",
                              "Air/self broadening approximates all non-absorbing bath gas as air.",
                              "Results inherit any source completeness and line-strength filtering limitations."]}
    with output.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=fieldnames, lineterminator="\n")
        writer.writeheader()
        case_idx = 0
        for temperature in temperatures:
            for pressure in pressures:
                for comp_name, x_co2, x_h2o in CONDITIONS:
                    case_idx += 1
                    alpha = absorption_spectrum(lines, tips, wn, float(temperature), pressure,
                                                x_co2, x_h2o, args.wing)
                    for idx, nu in enumerate(wn):
                        row = {"temperature_K": f"{temperature:g}", "pressure_atm": f"{pressure:g}",
                               "composition": comp_name, "x_co2": f"{x_co2:g}", "x_h2o": f"{x_h2o:g}",
                               "wavenumber_cm-1": f"{nu:.8g}", "alpha_m-1": f"{alpha[idx]:.12e}"}
                        for path in paths:
                            row[f"tau_L{path:g}_m"] = f"{math.exp(-alpha[idx] * path):.12e}"
                        writer.writerow(row)
                    print(f"[{case_idx}/{total_cases}] T={temperature:g} K p={pressure:g} atm "
                          f"{comp_name}: alpha_max={alpha.max():.6g} 1/m", flush=True)
    report["output_rows"] = len(wn) * total_cases
    report["output_bytes"] = output.stat().st_size
    report["output_sha256"] = sha256_file(output)
    (run_dir / "spectral_grid_manifest.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
