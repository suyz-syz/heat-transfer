"""Create a documented line-strength subset for tractable offline LBL grids."""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
from pathlib import Path


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument("--minimum-sw", type=float, default=1e-26)
    args = parser.parse_args()
    run_dir = args.run_dir.resolve()
    source = run_dir / "hitemp2010_lines_1000_4000_full.csv"
    target = run_dir / f"hitemp2010_lines_sw_ge_{args.minimum_sw:.0e}.csv"
    total = kept = 0
    with source.open(newline="", encoding="utf-8-sig") as inp, target.open("w", newline="", encoding="utf-8") as out:
        reader = csv.DictReader(inp)
        writer = csv.DictWriter(out, fieldnames=reader.fieldnames, lineterminator="\n")
        writer.writeheader()
        for row in reader:
            total += 1
            if float(row["sw"]) >= args.minimum_sw:
                writer.writerow(row)
                kept += 1
    report = {"source_file": source.name, "source_sha256": sha256_file(source),
              "source_rows": total, "minimum_sw_cm_per_molecule": args.minimum_sw,
              "kept_rows": kept, "removed_rows": total - kept,
              "output_file": target.name, "output_sha256": sha256_file(target),
              "warning": "This thresholded subset is used only for a tractable exploratory LBL grid; "
                         "threshold sensitivity and missing weak-line contribution remain to be validated."}
    (run_dir / "line_strength_filter_report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
