#!/usr/bin/env python3
"""Build a small, provenance-tracked HITEMP feature-band benchmark from source files.

This tool deliberately does not synthesize or invent spectroscopic records. Supply
official HITEMP fixed-width .par files and a normalized TIPS CSV obtained from
HITRANonline. The normalized outputs are intended for the Phase 1B LBL runner.

TIPS CSV schema: molecule,isotope,temperature_K,Q
Molecule names: CO2 or H2O. Isotope IDs are the numeric HITRAN isotopologue IDs.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
from pathlib import Path
from typing import Iterable

MOLECULE_IDS = {"01": "H2O", "02": "CO2"}
LINE_FIELDS = [
    "molecule", "nu", "strength_ref", "lower_energy", "air_gamma",
    "self_gamma", "temp_exponent", "partition_ref", "partition_exponent", "isotope",
]


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def parse_hitemp_line(raw: str, source: Path) -> dict | None:
    """Parse standard 160-column HITRAN/HITEMP fixed-width transition records."""
    if len(raw.rstrip("\r\n")) < 67:
        return None
    molecule_id = raw[0:2]
    molecule = MOLECULE_IDS.get(molecule_id)
    if molecule is None:
        return None
    try:
        isotope = raw[2:3].strip()
        nu = float(raw[3:15])
        strength = float(raw[15:25])
        gamma_air = float(raw[35:40])
        gamma_self = float(raw[40:45])
        lower_energy = float(raw[45:55])
        temp_exponent = float(raw[55:59])
    except ValueError as exc:
        raise ValueError(f"invalid fixed-width record in {source}: {raw[:67]!r}") from exc
    values = (nu, strength, gamma_air, gamma_self, lower_energy, temp_exponent)
    if not all(math.isfinite(v) for v in values):
        raise ValueError(f"non-finite fixed-width record in {source}: {raw[:67]!r}")
    if nu <= 0 or strength < 0 or gamma_air < 0 or gamma_self < 0:
        raise ValueError(f"invalid spectroscopic value in {source}: {raw[:67]!r}")
    return {
        "molecule": molecule, "nu": nu, "strength_ref": strength,
        "lower_energy": lower_energy, "air_gamma": gamma_air,
        "self_gamma": gamma_self, "temp_exponent": temp_exponent,
        # These two fields are required by the current loader but ignored when
        # the matching tabulated TIPS values are passed to line_strength().
        "partition_ref": 1.0, "partition_exponent": 0.0, "isotope": isotope,
    }


def extract_lines(
    sources: Iterable[Path], wn_min: float, wn_max: float, wing_margin: float
) -> list[dict]:
    selected = []
    low, high = wn_min - wing_margin, wn_max + wing_margin
    for source in sources:
        with source.open("r", encoding="ascii", errors="strict") as stream:
            for line_number, raw in enumerate(stream, 1):
                if not raw.strip():
                    continue
                row = parse_hitemp_line(raw, source)
                if row is None:
                    continue
                if low <= row["nu"] <= high:
                    row["source_file"] = source.name
                    row["source_line"] = line_number
                    selected.append(row)
    selected.sort(key=lambda row: (row["molecule"], int(row["isotope"] or 0), row["nu"]))
    if not selected:
        raise ValueError("no CO2/H2O transitions found in the requested band and wing margin")
    return selected


def load_and_validate_tips(path: Path, isotopologues: set[tuple[str, str]]) -> list[dict]:
    tables: dict[tuple[str, str], list[tuple[float, float]]] = {}
    with path.open(newline="", encoding="utf-8-sig") as stream:
        reader = csv.DictReader(stream)
        required = {"molecule", "isotope", "temperature_K", "Q"}
        if not required.issubset(reader.fieldnames or []):
            raise ValueError(f"TIPS CSV must contain columns {sorted(required)}")
        for row in reader:
            key = (row["molecule"].strip().upper(), row["isotope"].strip())
            try:
                temperature, q = float(row["temperature_K"]), float(row["Q"])
            except ValueError as exc:
                raise ValueError(f"invalid TIPS row for {key}") from exc
            if not math.isfinite(temperature) or not math.isfinite(q) or temperature <= 0 or q <= 0:
                raise ValueError(f"TIPS temperatures and Q must be finite and positive for {key}")
            tables.setdefault(key, []).append((temperature, q))

    normalized = []
    for key in sorted(isotopologues):
        points = sorted(tables.get(key, []))
        if not points:
            raise ValueError(f"missing TIPS table for {key[0]} isotope {key[1]}")
        temps = [t for t, _ in points]
        if len(set(temps)) != len(temps):
            raise ValueError(f"duplicate TIPS temperatures for {key}")
        if temps[0] > 296.0 or temps[-1] < 2400.0:
            raise ValueError(f"TIPS table for {key} must cover 296-2400 K")
        for temperature, q in points:
            if 296.0 <= temperature <= 2400.0:
                normalized.append({
                    "molecule": key[0], "isotope": key[1],
                    "temperature_K": temperature, "Q": q,
                })
    return normalized


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--line-file", action="append", required=True, type=Path,
                        help="official HITEMP .par file; repeat for CO2/H2O and isotopologues")
    parser.add_argument("--tips-csv", required=True, type=Path,
                        help="normalized official TIPS CSV: molecule,isotope,temperature_K,Q")
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--release", required=True,
                        help="exact HITEMP release/version for provenance, e.g. CO2-2024 + H2O-2010")
    parser.add_argument("--wn-min", type=float, default=1000.0)
    parser.add_argument("--wn-max", type=float, default=4000.0)
    parser.add_argument("--wing-margin", type=float, default=25.0,
                        help="include line centers this far outside the target band (cm-1)")
    args = parser.parse_args()
    if (not math.isfinite(args.wn_min) or not math.isfinite(args.wn_max)
            or not math.isfinite(args.wing_margin) or args.wn_min <= 0
            or args.wn_max <= args.wn_min or args.wing_margin < 0):
        parser.error("invalid wavenumber range or wing margin")
    if not args.tips_csv.is_file() or any(not p.is_file() for p in args.line_file):
        parser.error("all source line-list and TIPS files must exist")

    lines = extract_lines(args.line_file, args.wn_min, args.wn_max, args.wing_margin)
    isotopologues = {(row["molecule"], row["isotope"]) for row in lines}
    tips = load_and_validate_tips(args.tips_csv, isotopologues)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    line_output = args.output_dir / "hitemp_co2_h2o_1000_4000.csv"
    tips_output = args.output_dir / "tips_partition_sums_296_2400.csv"
    manifest_output = args.output_dir / "source_manifest.json"

    with line_output.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=LINE_FIELDS)
        writer.writeheader()
        writer.writerows({k: row[k] for k in LINE_FIELDS} for row in lines)
    with tips_output.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=["molecule", "isotope", "temperature_K", "Q"])
        writer.writeheader()
        writer.writerows(tips)

    manifest = {
        "status": "source-derived benchmark sample; not a complete all-spectrum database",
        "hitemp_release": args.release,
        "target_band_cm-1": [args.wn_min, args.wn_max],
        "line_center_selection_cm-1": [
            args.wn_min - args.wing_margin, args.wn_max + args.wing_margin
        ],
        "wing_margin_cm-1": args.wing_margin,
        "line_count": len(lines),
        "isotopologues": [
            {"molecule": molecule, "isotope": isotope}
            for molecule, isotope in sorted(isotopologues)
        ],
        "line_files": [{"path": str(p), "sha256": sha256_file(p)} for p in args.line_file],
        "tips_source": {"path": str(args.tips_csv), "sha256": sha256_file(args.tips_csv)},
        "outputs": {
            line_output.name: sha256_file(line_output),
            tips_output.name: sha256_file(tips_output),
        },
        "limitations": [
            "Band-limited sample; not suitable by itself for claiming total-spectrum heat flux.",
            "Current LBL line profile is pseudo-Voigt, not a metrology-grade Hartmann-Tran profile.",
            "Confirm HITEMP fixed-width edition layout against the source release before use.",
            "Keep source licenses/terms and citations with the benchmark artifact.",
        ],
    }
    manifest_output.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(f"Wrote {len(lines)} transitions across {len(isotopologues)} isotopologues")
    print(f"Lines: {line_output}")
    print(f"TIPS: {tips_output}")
    print(f"Manifest: {manifest_output}")


if __name__ == "__main__":
    main()
