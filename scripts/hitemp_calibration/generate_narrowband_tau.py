#!/usr/bin/env python3
"""Generate band-averaged 2000-2400 cm-1 transmittance references from HITEMP/TIPS.

The LBL model is the repository's pseudo-Voigt implementation. The output is a
condition/path table consumed by fit_wsgg_narrowband.py; it is offline trial
data, not independently validated spectroscopy or a production coefficient set.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import math
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.hitemp_calibration.hitemp_wsgg_calibration import (  # noqa: E402
    COMPOSITIONS,
    PATHS_M,
    PRESSURES_ATM,
    TEMPERATURES_K,
    band_emissivity,
    lbl_spectrum,
    load_inputs,
)

FIELDNAMES = (
    "temperature_K", "pressure_atm", "x_co2", "x_h2o", "path_m", "tau_reference",
)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def generate(line_csv: Path, tips_csv: Path, output_csv: Path) -> dict:
    if not line_csv.is_file() or not tips_csv.is_file():
        raise FileNotFoundError("both HITEMP line CSV and TIPS partition-sum CSV are required")
    lines, tips_map = load_inputs(line_csv, tips_csv)
    output_csv.parent.mkdir(parents=True, exist_ok=True)
    row_count = 0
    with output_csv.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=FIELDNAMES, lineterminator="\n")
        writer.writeheader()
        for temperature in TEMPERATURES_K:
            for pressure in PRESSURES_ATM:
                for x_co2, x_h2o in COMPOSITIONS:
                    wn, alpha = lbl_spectrum(
                        lines, tips_map, float(temperature), float(pressure),
                        float(x_co2), float(x_h2o), step=0.01,
                    )
                    for path_m in PATHS_M:
                        emissivity = band_emissivity(
                            wn, alpha, float(temperature), float(path_m),
                        )
                        tau = 1.0 - emissivity
                        if not math.isfinite(tau) or not 0.0 <= tau <= 1.0:
                            raise ValueError("LBL produced transmittance outside [0, 1]")
                        writer.writerow({
                            "temperature_K": f"{temperature:.12g}",
                            "pressure_atm": f"{pressure:.12g}",
                            "x_co2": f"{x_co2:.12g}",
                            "x_h2o": f"{x_h2o:.12g}",
                            "path_m": f"{path_m:.15g}",
                            "tau_reference": f"{tau:.17g}",
                        })
                        row_count += 1
    return {
        "output_csv": str(output_csv),
        "output_sha256": sha256_file(output_csv),
        "row_count": row_count,
        "condition_group_count": len(TEMPERATURES_K) * len(PRESSURES_ATM) * len(COMPOSITIONS),
        "line_csv_sha256": sha256_file(line_csv),
        "tips_csv_sha256": sha256_file(tips_csv),
        "reference_model": "pseudo-Voigt LBL, 0.01 cm-1 grid, Planck-weighted 2000-2400 cm-1 transmittance",
        "temperatures_K": list(TEMPERATURES_K),
        "pressures_atm": list(PRESSURES_ATM),
        "compositions_mole_fraction": [
            {"CO2": float(co2), "H2O": float(h2o)} for co2, h2o in COMPOSITIONS
        ],
        "path_count_per_condition": len(PATHS_M),
        "limitations": [
            "The committed line sample is not a complete HITEMP database.",
            "Pseudo-Voigt LBL is not independently validated Hartmann-Tran spectroscopy.",
            "The reference is limited to 2000-2400 cm-1 and inherits input-data uncertainty.",
        ],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--line-csv", type=Path,
        default=ROOT / "data/hitemp_co2_h2o_1000_4000_sample.csv",
    )
    parser.add_argument(
        "--tips-csv", type=Path,
        default=ROOT / "data/tips_partition_sums_296_2400.csv",
    )
    parser.add_argument(
        "--output", type=Path,
        default=ROOT / "data/hitemp_narrowband_tau_reference.csv",
    )
    args = parser.parse_args()
    print(__import__("json").dumps(
        generate(args.line_csv, args.tips_csv, args.output), indent=2,
    ))


if __name__ == "__main__":
    main()
