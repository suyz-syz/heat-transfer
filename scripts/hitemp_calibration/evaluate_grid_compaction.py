"""Compare compact/float32 and coarse spectral grids through the wall solver.

This is an empirical discretization study of the current band-limited data,
not a validation of the underlying HITEMP LBL physics against experiment.
"""
from __future__ import annotations

import argparse
import array
import csv
import json
import math
import sys
from dataclasses import replace
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from kiln_ht import calc
from kiln_ht.models.radiation import hitemp_grid as hgrid


def read_csv_spectra(path: Path, expected: dict) -> dict:
    arrays = {(it, ip, ic): array.array("d")
              for it in range(len(expected["temperatures"]))
              for ip in range(len(expected["pressures"]))
              for ic in range(len(expected["names"]))}
    t_idx = {v: i for i, v in enumerate(expected["temperatures"])}
    p_idx = {v: i for i, v in enumerate(expected["pressures"])}
    c_idx = {v: i for i, v in enumerate(expected["names"])}
    with path.open("r", newline="", encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            key = (t_idx[float(row["temperature_K"])], p_idx[float(row["pressure_atm"])],
                   c_idx[row["composition"]])
            arrays[key].append(float(row["alpha_m-1"]))
    return arrays


def solve(grid, temperature: float, pressure_atm: float = 1.0,
          x_co2: float = 0.08, x_h2o: float = 0.12) -> dict:
    hgrid._GRID = grid
    hgrid._cached_spectrum.cache_clear()
    hgrid._emissivity_cached.cache_clear()
    hgrid._absorptivity_cached.cache_clear()
    params = calc.KilnParams(
        T_gas=temperature, L_char=4.0, L_kiln=30.0, P_total=pressure_atm * 1.01325,
        CO2=x_co2, H2O=x_h2o, N2=1.0 - x_co2 - x_h2o, O2=0.0, radiation_model="hitemp_grid",
        property_model="air", eps_wall=0.85, T_env=298.15, v_gas=3.0, v_amb=2.0,
    )
    layers = [
        calc.Layer(name="refractory", thickness=0.20, k=1.5),
        calc.Layer(name="insulation", thickness=0.10, k=0.22),
        calc.Layer(name="steel", thickness=0.015, k=45.0),
    ]
    result = calc.solve_wall(layers, params)
    return {"T_w1_K": result.T_w1, "T_wN_K": result.T_wN,
            "Qprime_W_m": result.Qprime, "q_out_W_m2": result.q_out,
            "h_rad_in_W_m2K": result.h_rad_in, "emissivity": result.eg}


def variant(base, stride: int, single_precision: bool):
    spectra = {}
    for key, values in base.spectra.items():
        vals = values[::stride]
        spectra[key] = array.array("f" if single_precision else "d", vals)
    wns = base.wavenumbers[::stride]
    # Endpoint is included for these evenly divisible strides.
    if wns[-1] != base.wavenumbers[-1]:
        raise ValueError("spectral stride did not retain endpoint")
    return replace(base, spectra=spectra, wavenumbers=wns)


def relative_error(a: float, b: float) -> float:
    return abs(a - b) / max(abs(a), 1e-300)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data-dir", type=Path, default=ROOT / "data")
    ap.add_argument("--reference-csv", type=Path, default=None,
                    help="canonical 0.25 cm-1 CSV, normally in the offline run archive")
    ap.add_argument("--report", type=Path,
                    default=ROOT / "reports" / "hitemp_grid_compaction_precision.json")
    args = ap.parse_args()
    manifest = json.loads((args.data_dir / "manifest.json").read_text(encoding="utf-8"))
    meta = manifest["spectral_grid"]
    reference_csv = args.reference_csv or (ROOT / "scripts" / "hitemp_calibration" / "offline_runs" /
                                           "hitemp2010_20261016" / "spectral_grid_alpha_tau.csv")
    if not reference_csv.is_file():
        reference_csv = args.data_dir / "spectral_grid_alpha_tau.csv"
    if not reference_csv.is_file():
        raise SystemExit("reference CSV unavailable; pass --reference-csv")
    csv_bytes = reference_csv.stat().st_size
    compact_bytes = (args.data_dir / meta["compact_binary"]["file"]).stat().st_size
    base = hgrid._load_grid()
    # Reference precision is reconstructed from the canonical CSV.
    names = [c["name"] for c in meta["compositions"]]
    tvals, pvals = [float(v) for v in meta["temperature_K"]], [float(v) for v in meta["pressure_atm"]]
    csv_arrays = read_csv_spectra(reference_csv, {
        "temperatures": tvals, "pressures": pvals, "names": names,
    })
    csv_grid = replace(base, spectra=csv_arrays)
    f32_grid = base
    coarse_1 = variant(base, 4, False)
    coarse_2 = variant(base, 8, False)
    strides = {"packed_float32_0.25cm-1": f32_grid,
               "float64_1.0cm-1": coarse_1, "float64_2.0cm-1": coarse_2}
    paths = [0.1, 1.0, 3.8, 5.0]
    spectral_sweep = {}
    for name, candidate in strides.items():
        max_errors = {str(path): {"absolute_emissivity_error": -1.0} for path in paths}
        for it, temperature in enumerate(base.temperatures):
            for ip, pressure in enumerate(base.pressures):
                for ic, (composition, xco2, xh2o) in enumerate(base.compositions):
                    key = (it, ip, ic)
                    ref_alpha = csv_arrays[key]
                    candidate_alpha = candidate.spectra[key]
                    for path in paths:
                        ref_eps = hgrid._band_emissivity(csv_grid, ref_alpha, temperature, path)
                        cand_eps = hgrid._band_emissivity(candidate, candidate_alpha, temperature, path)
                        error = abs(cand_eps - ref_eps)
                        entry = max_errors[str(path)]
                        if error > entry["absolute_emissivity_error"]:
                            max_errors[str(path)] = {
                                "absolute_emissivity_error": error,
                                "temperature_K": temperature, "pressure_atm": pressure,
                                "composition": composition, "x_co2": xco2, "x_h2o": xh2o,
                                "reference_emissivity": ref_eps, "candidate_emissivity": cand_eps,
                            }
        spectral_sweep[name] = max_errors

    # Wall-solver comparison at the worst epsilon-error condition for the actual
    # 3.8 m representative beam path, plus a central nominal point.
    wall_condition_sets = {"nominal_1atm": {"temperature_K": 1800.0, "pressure_atm": 1.0,
                                             "x_co2": 0.08, "x_h2o": 0.12}}
    for model_name, max_by_path in spectral_sweep.items():
        worst = max_by_path["3.8"]
        wall_condition_sets[f"worst_{model_name}"] = {k: worst[k] for k in
            ("temperature_K", "pressure_atm", "x_co2", "x_h2o")}
    wall_results = {}
    for case_name, case in wall_condition_sets.items():
        t = float(case["temperature_K"])
        p = float(case["pressure_atm"])
        xco2, xh2o = float(case["x_co2"]), float(case["x_h2o"])
        reference = solve(csv_grid, t, p, xco2, xh2o)
        wall_results[case_name] = {"condition": case, "reference_csv_float64": reference, "candidates": {}}
        for model_name, candidate in strides.items():
            output = solve(candidate, t, p, xco2, xh2o)
            wall_results[case_name]["candidates"][model_name] = {
                "result": output,
                "delta_inner_wall_C": output["T_w1_K"] - reference["T_w1_K"],
                "delta_outer_wall_C": output["T_wN_K"] - reference["T_wN_K"],
                "delta_Qprime_W_m": output["Qprime_W_m"] - reference["Qprime_W_m"],
                "relative_Qprime_error": relative_error(output["Qprime_W_m"], reference["Qprime_W_m"]),
            }
    report = {
        "scope": "Empirical comparison against the canonical band-limited CSV through kiln_ht.calc.solve_wall; not validation against physical truth.",
        "reference_csv": str(reference_csv),
        "input_csv_bytes": csv_bytes,
        "compact_float32_bytes": compact_bytes,
        "size_ratio_compact_to_csv": compact_bytes / csv_bytes,
        "storage_reduction_percent": (1 - compact_bytes / csv_bytes) * 100,
        "grid": meta["spectral_grid_cm-1"],
        "sweep": {"condition_nodes": len(base.temperatures) * len(base.pressures) * len(base.compositions),
                  "paths_m": paths, "maximum_emissivity_errors": spectral_sweep},
        "wall_solver_cases": wall_results,
        "acceptance_thresholds": {"wall_temperature_absolute_C": 1.0},
        "interpretation": "The ≤1 C condition is assessed only for the listed wall-solver cases and relative to the current CSV model. It does not bound errors from the band-limited/filtered/pseudo-Voigt spectroscopy or sparse thermochemical grid.",
    }
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"report": str(args.report), "size_reduction_percent": report["storage_reduction_percent"],
                      "maximum_emissivity_errors": spectral_sweep,
                      "wall_solver_cases": {name: value["candidates"]
                                            for name, value in wall_results.items()}}, indent=2))


if __name__ == "__main__":
    main()
