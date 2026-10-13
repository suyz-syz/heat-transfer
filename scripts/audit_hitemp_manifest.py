#!/usr/bin/env python3
"""Audit committed HITEMP/TIPS benchmark inputs and write/check their manifest.

This is an offline data-governance tool. It does not run the LBL solver or
change any production model. Run from the repository root:
  python scripts/audit_hitemp_manifest.py --write
  python scripts/audit_hitemp_manifest.py --check
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

LINE_COLUMNS = (
    "molec_id", "local_iso_id", "nu", "sw", "a", "gamma_air",
    "gamma_self", "elower", "n_air", "delta_air",
)
TIPS_COLUMNS = ("molecule", "isotope", "temperature_K", "Q")
SPECIES = {"1": "H2O", "2": "CO2"}
DEFAULT_LINES = Path("data/hitemp_co2_h2o_1000_4000_sample.csv")
DEFAULT_TIPS = Path("data/tips_partition_sums_296_2400.csv")
DEFAULT_MANIFEST = Path("reports/hitemp_dataset_manifest.json")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _load_csv(path: Path, expected: tuple[str, ...]) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8-sig") as stream:
        reader = csv.DictReader(stream)
        if tuple(reader.fieldnames or ()) != expected:
            raise ValueError(f"{path}: expected exact columns {expected}, got {reader.fieldnames}")
        return list(reader)


def build_manifest(line_path: Path = DEFAULT_LINES, tips_path: Path = DEFAULT_TIPS) -> dict[str, Any]:
    lines = _load_csv(line_path, LINE_COLUMNS)
    tips = _load_csv(tips_path, TIPS_COLUMNS)
    counts: Counter[tuple[str, str]] = Counter()
    wavenumbers: list[float] = []
    for row in lines:
        molecule_id, isotope = row["molec_id"].strip(), row["local_iso_id"].strip()
        if molecule_id not in SPECIES or not isotope.isdigit():
            raise ValueError(f"unsupported molecule/isotopologue ID: {(molecule_id, isotope)}")
        values = {key: float(row[key]) for key in LINE_COLUMNS[2:]}
        if not all(math.isfinite(value) for value in values.values()):
            raise ValueError("line list contains non-finite numeric values")
        if values["nu"] <= 0 or values["sw"] < 0 or values["gamma_air"] < 0 or values["gamma_self"] < 0:
            raise ValueError(f"invalid frequency/strength/broadening: {(molecule_id, isotope)}")
        counts[(molecule_id, isotope)] += 1
        wavenumbers.append(values["nu"])

    tips_by_key: dict[tuple[str, str], list[float]] = defaultdict(list)
    for row in tips:
        molecule_id, isotope = row["molecule"].strip(), row["isotope"].strip()
        if molecule_id not in SPECIES or not isotope.isdigit():
            raise ValueError(f"TIPS IDs must be numeric HITRAN IDs: {(molecule_id, isotope)}")
        temperature, q_value = float(row["temperature_K"]), float(row["Q"])
        if not (math.isfinite(temperature) and math.isfinite(q_value) and temperature > 0 and q_value > 0):
            raise ValueError(f"invalid TIPS values for {(molecule_id, isotope)}")
        tips_by_key[(molecule_id, isotope)].append(temperature)

    line_keys = set(counts)
    if line_keys != set(tips_by_key):
        raise ValueError(f"line/TIPS isotopologue mismatch: line-only={sorted(line_keys-set(tips_by_key))}, "
                         f"tips-only={sorted(set(tips_by_key)-line_keys)}")

    isotope_inventory = []
    for molecule_id, isotope in sorted(line_keys, key=lambda key: (int(key[0]), int(key[1]))):
        temps = tips_by_key[(molecule_id, isotope)]
        if len(temps) != len(set(temps)):
            raise ValueError(f"duplicate TIPS temperature for {(molecule_id, isotope)}")
        isotope_inventory.append({
            "molec_id": int(molecule_id),
            "species": SPECIES[molecule_id],
            "local_iso_id": int(isotope),
            "line_count": counts[(molecule_id, isotope)],
            "tips_rows": len(temps),
            "tips_temperature_K": [min(temps), max(temps)],
        })

    return {
        "manifest_schema_version": 1,
        "dataset_id": "hitemp_co2_h2o_narrow_band_sample",
        "data_scope": "offline narrow-band calibration input; not a complete line database",
        "provenance": {
            "hitemp_release": "not recorded in repository; independent source/version audit pending",
            "tips_release": "not recorded in repository; independent source/version audit pending",
            "source_authenticity": "not independently authenticated",
            "isotope_ids": "HITRAN molecule ID plus local isotopologue ID",
        },
        "files": {
            line_path.as_posix(): {
                "sha256": sha256_file(line_path),
                "bytes": line_path.stat().st_size,
                "records": len(lines),
                "columns": list(LINE_COLUMNS),
                "wavenumber_cm-1": [min(wavenumbers), max(wavenumbers)],
            },
            tips_path.as_posix(): {
                "sha256": sha256_file(tips_path),
                "bytes": tips_path.stat().st_size,
                "records": len(tips),
                "columns": list(TIPS_COLUMNS),
                "temperature_K": [min(float(row["temperature_K"]) for row in tips),
                                  max(float(row["temperature_K"]) for row in tips)],
            },
        },
        "isotopologue_coverage": isotope_inventory,
        "conversion_rules": {
            "line_source": "HITEMP/HITRAN 160-character fixed-width .par record",
            "line_columns": {
                "molec_id": "characters 1-2; numeric HITRAN molecule ID",
                "local_iso_id": "character 3; local isotopologue ID",
                "nu": "characters 4-15; cm^-1",
                "sw": "characters 16-25; reference line intensity at 296 K",
                "a": "characters 26-35; Einstein A value, retained as source field",
                "gamma_air": "characters 36-40",
                "gamma_self": "characters 41-45",
                "elower": "characters 46-55; cm^-1",
                "n_air": "characters 56-59; air-broadening temperature exponent",
                "delta_air": "characters 60-67; air pressure shift",
            },
            "tips_columns": {
                "molecule": "numeric HITRAN molecule ID (1=H2O, 2=CO2)",
                "isotope": "numeric local isotopologue ID",
                "temperature_K": "kelvin",
                "Q": "partition sum",
            },
            "preprocessor": "scripts/prepare_hitemp_benchmark.py",
            "normalization": "CSV headers use the canonical source-style line fields; values are not rescaled",
        },
        "limitations": [
            "The exact source release/version and upstream checksum are not documented in the repository.",
            "Observed isotope IDs describe this sample only and do not establish completeness for either species.",
            "The sample covers a narrow calibration band and cannot support full-spectrum claims.",
            "The offline pseudo-Voigt LBL approximation is not an independently validated reference standard.",
        ],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--write", action="store_true", help="write/rebuild the committed manifest")
    mode.add_argument("--check", action="store_true", help="fail if data or manifest differs")
    parser.add_argument("--line-csv", type=Path, default=DEFAULT_LINES)
    parser.add_argument("--tips-csv", type=Path, default=DEFAULT_TIPS)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    args = parser.parse_args()
    manifest = build_manifest(args.line_csv, args.tips_csv)
    if args.write:
        args.manifest.parent.mkdir(parents=True, exist_ok=True)
        args.manifest.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
        print(f"Wrote {args.manifest}")
        return
    recorded = json.loads(args.manifest.read_text(encoding="utf-8"))
    if recorded != manifest:
        raise SystemExit("manifest mismatch: run scripts/audit_hitemp_manifest.py --write and review the diff")
    print(f"Manifest verified: {args.manifest}")


if __name__ == "__main__":
    main()
