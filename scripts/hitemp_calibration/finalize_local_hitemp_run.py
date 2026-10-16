"""Finalize source hashes, CSV statistics, and TIPS-2021 coverage for a run."""
from __future__ import annotations

import argparse
import bisect
import csv
import hashlib
import json
import math
import re
import zipfile
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

import numpy as np


def sha256_file(path):
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def load_hapi_tips(path):
    with zipfile.ZipFile(path) as archive:
        name = next(n for n in archive.namelist() if n.endswith("hapi.py"))
        source = archive.read(name).decode("utf-8", "replace")
    source = re.sub(r"\bfloat64\b", "numpy.float64", source)
    start = source.find("TIPS_2021_ISOT_HASH = {}")
    end = source.find("def BD_TIPS_2021_PYTHON", start)
    if start < 0 or end < 0:
        raise RuntimeError("HAPI archive does not expose the expected TIPS-2021 block")
    g = {"numpy": np, "__FloatType__": np.float64}
    for key in ("float32", "float64", "int64", "zeros", "array", "linspace", "arange",
                "convolve", "polyval", "exp", "sqrt", "place", "where", "minimum", "maximum"):
        g.setdefault(key, getattr(np, key))
    a = source.find("def AtoB(aa,A,B,npt):")
    if a < 0:
        raise RuntimeError("HAPI TIPS interpolator AtoB was not found")
    exec(source[a:source.find("def ", a + 8)], g)
    exec(source[start:end], g)
    end_eval = source.find("# =========================/TIPS2021", end)
    exec(source[end:end_eval], g)
    return g["BD_TIPS_2021_PYTHON"]


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--source", type=Path, default=Path(r"E:\tmp\hitemp2010"))
    p.add_argument("--run-dir", type=Path, required=True)
    args = p.parse_args()
    source, run = args.source.resolve(), args.run_dir.resolve()
    line_csv = run / "hitemp2010_lines_1000_4000_full.csv"
    if not line_csv.is_file():
        raise FileNotFoundError(line_csv)
    zips = sorted(source.glob("*_HITEMP2010.zip"))
    if len(zips) != 22:
        raise RuntimeError(f"expected 22 source ZIPs, found {len(zips)}")
    archive_info = []
    ranges = {}
    for z in zips:
        m = re.match(r"0([12])_(\d+)-(\d+)_HITEMP2010\.zip$", z.name)
        if not m:
            raise ValueError(f"unexpected archive name {z.name}")
        mol, lo, hi = int(m.group(1)), float(m.group(2)), float(m.group(3))
        with zipfile.ZipFile(z) as zz:
            files = [x for x in zz.infolist() if not x.is_dir()]
            if len(files) != 1:
                raise RuntimeError(f"{z.name}: expected one PAR member")
            member = files[0]
        item = {"name": z.name, "size_bytes": z.stat().st_size, "sha256": sha256_file(z),
                "member": member.filename, "uncompressed_size_bytes": member.file_size,
                "molecule_id": mol, "chunk_interval_cm-1": [lo, hi]}
        archive_info.append(item)
        ranges.setdefault(mol, []).append((lo, hi, item))
        print(f"[hash {len(archive_info)}/22] {z.name}", flush=True)
    for mol, chunks in ranges.items():
        chunks.sort()
        if chunks[0][0] != 1000 or chunks[-1][1] < 4000:
            raise RuntimeError(f"molecule {mol}: incomplete source interval")
        for a, b in zip(chunks, chunks[1:]):
            if not math.isclose(a[1], b[0], abs_tol=1e-9):
                raise RuntimeError(f"molecule {mol}: source chunk gap/overlap at {a[1]} vs {b[0]}")
    range_starts = {mol: [x[0] for x in chunks] for mol, chunks in ranges.items()}

    iso_counts, species_counts, binsets = Counter(), Counter(), {1: set(), 2: set()}
    archive_line_counts = Counter()
    row_count = 0
    with line_csv.open(newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for row in reader:
            mol, iso, nu, sw = int(row["molec_id"]), int(row["local_iso_id"]), float(row["nu"]), float(row["sw"])
            row_count += 1
            species_counts[mol] += 1
            iso_counts[(mol, iso)] += 1
            binsets[mol].add(int(nu - 1000.0))
            idx = bisect.bisect_right(range_starts[mol], nu) - 1
            if idx >= 0:
                lo, hi, item = ranges[mol][idx]
                if lo <= nu < hi or (nu == 4000 and hi == 4000):
                    archive_line_counts[item["name"]] += 1
    if row_count == 0:
        raise RuntimeError("empty extracted CSV")
    for item in archive_info:
        item["kept_lines_in_1000_4000_cm-1"] = archive_line_counts[item["name"]]

    hapi = source / "hapi.zip"
    bd = load_hapi_tips(hapi)
    tip_path = run / "tips_partition_sums_296_2400.csv"
    temperatures = list(range(296, 2401, 25))
    if temperatures[-1] != 2400:
        temperatures.append(2400)
    tips_rows = 0
    with tip_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f, lineterminator="\n")
        writer.writerow(("molecule", "isotope", "temperature_K", "Q"))
        for mol, iso in sorted(iso_counts):
            for temp in temperatures:
                _, q = bd(mol, iso, temp)
                q = float(q)
                if not math.isfinite(q) or q <= 0:
                    raise RuntimeError(f"invalid TIPS Q for {mol}:{iso} at {temp} K")
                writer.writerow((mol, iso, temp, f"{q:.12e}"))
                tips_rows += 1

    full_count = row_count
    threshold_count = 0
    with line_csv.open(newline="", encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            if float(row["sw"]) >= 1e-26:
                threshold_count += 1
    manifest = {
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "source_directory": str(source), "run_directory": str(run),
        "source_spectral_interval_cm-1": [1000.0, 4000.0],
        "archive_count": len(archive_info), "archives": archive_info,
        "source_chunk_coverage": {"H2O": "continuous 1000-4150 cm-1 chunks; extracted through 4000",
                                   "CO2": "continuous 1000-4000 cm-1 chunks"},
        "full_line_csv": {"file": line_csv.name, "rows_no_strength_cutoff": full_count,
                          "counts_by_molecule_id": {str(k): v for k, v in species_counts.items()},
                          "counts_by_isotopologue": {f"{m}:{i}": v for (m, i), v in sorted(iso_counts.items())},
                          "rows_at_legacy_sw_ge_1e-26": threshold_count,
                          "rows_below_legacy_threshold": full_count-threshold_count,
                          "sha256": sha256_file(line_csv), "size_bytes": line_csv.stat().st_size},
        "tips": {"file": tip_path.name, "source_hapi": str(hapi), "hapi_sha256": sha256_file(hapi),
                 "temperature_K": [min(temperatures), max(temperatures)],
                 "isotopologue_count": len(iso_counts), "rows": tips_rows,
                 "Q_validation": "all generated values finite and positive; no missing isotope/temperature pairs"},
        "limitations": ["The 1000-4000 cm-1 line interval is not a total-spectrum database.",
                        "Line-strength threshold is reported but not applied to canonical full CSV.",
                        "HITEMP provenance is represented by local archive hashes; upstream licensing/release metadata still needs independent documentation."],
    }
    (run / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    (run / "extraction_summary.json").write_text(json.dumps({"full_rows": full_count,
        "counts_by_molecule_id": manifest["full_line_csv"]["counts_by_molecule_id"],
        "counts_by_isotopologue": manifest["full_line_csv"]["counts_by_isotopologue"],
        "rows_at_legacy_sw_ge_1e-26": threshold_count, "tips_rows": tips_rows,
        "archive_count": len(archive_info)}, indent=2), encoding="utf-8")
    print(json.dumps({"full_rows": full_count, "threshold_rows": threshold_count,
                      "by_species": manifest["full_line_csv"]["counts_by_molecule_id"],
                      "isotopologues": len(iso_counts), "tips_rows": tips_rows,
                      "line_csv_sha256": manifest["full_line_csv"]["sha256"]}, indent=2))


if __name__ == "__main__":
    main()
