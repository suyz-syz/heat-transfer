"""Audit local HITEMP2010 archives and create an offline canonical line CSV.

This utility only reads the source archives and writes below the requested output
directory. It deliberately preserves every line in the configured spectral
interval; a legacy line-strength cutoff is reported as a diagnostic, not applied.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import re
import zipfile
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

FIELDS = ("molec_id", "local_iso_id", "nu", "sw", "a", "gamma_air",
          "gamma_self", "elower", "n_air", "delta_air")
WIDTHS = ((1, 2), (3, 3), (4, 15), (16, 25), (26, 35), (36, 40),
          (41, 45), (46, 55), (56, 60), (61, 65))
LEGACY_SW_CUTOFF = 1e-26


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def parse_row(raw: bytes):
    if len(raw) < 65:
        raise ValueError("record shorter than 65 characters")
    line = raw.decode("ascii")
    tokens = [line[a - 1:b].strip() for a, b in WIDTHS]
    # HITEMP2010 uses a trailing minus as a field pad for both positive and
    # negative n_air values; remove only that final pad and preserve the sign.
    na = tokens[8]
    if na.endswith("-"):
        tokens[8] = na[:-1]
    molecule, isotope = int(tokens[0]), int(tokens[1])
    nu, strength = float(tokens[2]), float(tokens[3])
    vals = [float(x) for x in tokens[2:]]
    if molecule not in (1, 2) or isotope <= 0:
        raise ValueError(f"unsupported molecule/isotope: {molecule}/{isotope}")
    if any(x != x or abs(x) == float("inf") for x in vals):
        raise ValueError("non-finite numeric value")
    if nu <= 0 or strength < 0 or float(tokens[5]) < 0 or float(tokens[6]) < 0:
        raise ValueError("invalid frequency, strength, or broadening")
    return tokens, molecule, isotope, nu, strength


def chunk_interval(path: Path):
    match = re.match(r"(?P<mol>0[12])_(?P<lo>\d+)-(?P<hi>\d+)_HITEMP2010\.zip$", path.name)
    if not match:
        raise ValueError(f"unexpected archive name: {path.name}")
    return int(match.group("mol")), float(match.group("lo")), float(match.group("hi"))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=Path(r"E:\tmp\hitemp2010"))
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--nu-min", type=float, default=1000.0)
    parser.add_argument("--nu-max", type=float, default=4000.0)
    parser.add_argument("--coverage-step", type=float, default=1.0)
    args = parser.parse_args()
    source = args.source.resolve()
    out = args.output_dir.resolve()
    out.mkdir(parents=True, exist_ok=True)
    archives = sorted(source.glob("*_HITEMP2010.zip"))
    if len(archives) != 22:
        raise RuntimeError(f"expected 22 HITEMP2010 archives (12 H2O + 10 CO2), found {len(archives)}")
    by_molecule = Counter(chunk_interval(p)[0] for p in archives)
    if by_molecule != {1: 12, 2: 10}:
        raise RuntimeError(f"unexpected archive counts by molecule ID: {dict(by_molecule)}")
    intervals = {1: [], 2: []}
    for archive in archives:
        mol_id, lo, hi = chunk_interval(archive)
        intervals[mol_id].append((lo, hi, archive.name))
    for mol_id, chunks in intervals.items():
        chunks.sort()
        if chunks[0][0] != args.nu_min or chunks[-1][1] < args.nu_max:
            raise RuntimeError(f"molecule {mol_id}: source chunks do not span requested interval")
        for left, right in zip(chunks, chunks[1:]):
            if not math.isclose(left[1], right[0], abs_tol=1e-9):
                raise RuntimeError(f"molecule {mol_id}: chunk gap/overlap between {left[2]} and {right[2]}")

    manifest = {
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "source_directory": str(source),
        "output_directory": str(out),
        "spectral_interval_cm-1": [args.nu_min, args.nu_max],
        "canonical_columns": list(FIELDS),
        "selection": "all valid lines in interval; no line-strength cutoff applied",
        "legacy_sw_cutoff_diagnostic_cm_per_molecule": LEGACY_SW_CUTOFF,
        "archive_count": len(archives),
        "archives": [],
    }
    csv_path = out / "hitemp2010_lines_1000_4000_full.csv"
    counts = Counter()
    iso_counts = Counter()
    nu_min, nu_max = {}, {}
    coverage = {1: set(), 2: set()}
    parse_errors = []
    with csv_path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.writer(stream, lineterminator="\n")
        writer.writerow(FIELDS)
        for archive in archives:
            mol_id, chunk_lo, chunk_hi = chunk_interval(archive)
            entry = {"name": archive.name, "size_bytes": archive.stat().st_size,
                     "sha256": sha256_file(archive), "declared_molecule_id": mol_id,
                     "chunk_interval_cm-1": [chunk_lo, chunk_hi]}
            with zipfile.ZipFile(archive) as zf:
                members = [i for i in zf.infolist() if not i.is_dir()]
                if len(members) != 1:
                    raise RuntimeError(f"{archive.name}: expected one PAR member, found {len(members)}")
                info = members[0]
                entry["member"] = info.filename
                entry["uncompressed_size_bytes"] = info.file_size
                raw_count = malformed = nonmonotonic = 0
                previous_nu = None
                file_kept = file_threshold = 0
                with zf.open(info) as data:
                    for line_number, raw in enumerate(data, 1):
                        raw_count += 1
                        try:
                            tokens, mol, iso, nu, strength = parse_row(raw)
                            if mol != mol_id:
                                raise ValueError(f"molecule ID {mol} disagrees with archive prefix {mol_id}")
                        except Exception as exc:
                            malformed += 1
                            if len(parse_errors) < 20:
                                parse_errors.append({"archive": archive.name, "line": line_number,
                                                    "error": str(exc)})
                            continue
                        if previous_nu is not None and nu < previous_nu:
                            nonmonotonic += 1
                        previous_nu = nu
                        if args.nu_min <= nu <= args.nu_max:
                            writer.writerow(tokens)
                            file_kept += 1
                            counts[mol] += 1
                            iso_counts[(mol, iso)] += 1
                            nu_min[mol] = min(nu_min.get(mol, nu), nu)
                            nu_max[mol] = max(nu_max.get(mol, nu), nu)
                            coverage[mol].add(int((nu - args.nu_min) // args.coverage_step))
                            if strength >= LEGACY_SW_CUTOFF:
                                file_threshold += 1
                entry.update({"raw_record_count": raw_count, "malformed_record_count": malformed,
                              "nonmonotonic_frequency_steps": nonmonotonic,
                              "kept_in_interval": file_kept,
                              "kept_if_legacy_cutoff_applied": file_threshold})
                manifest["archives"].append(entry)
                print(f"[{len(manifest['archives']):02d}/22] {archive.name}: {file_kept:,} interval lines; "
                      f"sha256={entry['sha256'][:16]}...", flush=True)

    expected_bins = int((args.nu_max - args.nu_min) / args.coverage_step)
    coverage_report = {}
    for mol in (1, 2):
        missing = sorted(set(range(expected_bins)) - coverage[mol])
        coverage_report[str(mol)] = {
            "molecule": {"1": "H2O", "2": "CO2"}[str(mol)],
            "observed_line_count": counts[mol],
            "observed_nu_min_cm-1": nu_min.get(mol),
            "observed_nu_max_cm-1": nu_max.get(mol),
            "covered_bins": len(coverage[mol]), "expected_bins": expected_bins,
            "empty_line_center_bins": missing,
            "empty_bin_means_no_line_centers_not_missing_source_chunk": True,
        }
    manifest["summary"] = {
        "records_in_interval_all_lines": sum(counts.values()),
        "records_if_legacy_cutoff_applied": sum(e["kept_if_legacy_cutoff_applied"] for e in manifest["archives"]),
        "counts_by_molecule_id": {str(k): v for k, v in counts.items()},
        "counts_by_isotopologue": {f"{m}:{i}": n for (m, i), n in sorted(iso_counts.items())},
        "coverage_by_molecule": coverage_report,
        "parse_error_samples": parse_errors,
        "csv_size_bytes": csv_path.stat().st_size,
        "csv_sha256": sha256_file(csv_path),
    }
    # Audit the existing TIPS table, but leave authoritative regeneration to
    # finalize_local_hitemp_run.py, which rebuilds it for newly observed isotopes.
    tips_src = source / "tips_partition_sums_296_2400.csv"
    hapi_src = source / "hapi.zip"
    tips_pairs = Counter()
    tips_ranges = {}
    with tips_src.open(newline="", encoding="utf-8-sig") as stream:
        reader = csv.DictReader(stream)
        needed = {"molecule", "isotope", "temperature_K", "Q"}
        if not needed.issubset(reader.fieldnames or []):
            raise RuntimeError("TIPS table is missing required columns")
        for row in reader:
            mol, iso = int(row["molecule"]), int(row["isotope"])
            temp, q = float(row["temperature_K"]), float(row["Q"])
            if not math.isfinite(temp) or not math.isfinite(q) or temp <= 0 or q <= 0:
                raise RuntimeError(f"invalid TIPS value: {row}")
            tips_pairs[(mol, iso)] += 1
            tips_ranges.setdefault((mol, iso), []).append(temp)
    line_pairs = {(m, i) for (m, i), n in iso_counts.items() if n}
    missing_tips = sorted(line_pairs - set(tips_pairs))
    extra_tips = sorted(set(tips_pairs) - line_pairs)
    tips_invalid = []
    for pair, temps in tips_ranges.items():
        if len(temps) != len(set(temps)) or min(temps) > 296 or max(temps) < 2400:
            tips_invalid.append(f"temperature coverage invalid for {pair}")
    manifest["existing_tips_audit"] = {
        "source": str(tips_src), "source_sha256": sha256_file(tips_src),
        "hapi_source": str(hapi_src), "hapi_sha256": sha256_file(hapi_src),
        "isotopologue_count": len(tips_pairs), "rows": sum(tips_pairs.values()),
        "missing_for_extracted_lines": missing_tips, "unexpected_isotopologues": extra_tips,
        "validation_issues": tips_invalid,
        "status": "requires regeneration" if missing_tips or extra_tips or tips_invalid else "coverage matches",
        "next_step": "run finalize_local_hitemp_run.py to generate the exact current TIPS-2021 table",
    }
    manifest_path = out / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    (out / "extraction_summary.json").write_text(json.dumps(manifest["summary"], indent=2), encoding="utf-8")
    if parse_errors:
        raise RuntimeError(f"encountered {sum(e['malformed_record_count'] for e in manifest['archives'])} malformed rows; examples saved in manifest")
    print(json.dumps(manifest["summary"], indent=2))


if __name__ == "__main__":
    main()
