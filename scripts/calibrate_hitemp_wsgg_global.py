#!/usr/bin/env python3
"""Generate reports/hitemp_wsgg_calibration.json from user-supplied HITEMP/TIPS CSVs."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

# Running a script sets sys.path[0] to scripts/, not the repository root.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from kiln_ht.models.radiation.hitemp_wsgg_calibration import run_calibration


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--line-csv", type=Path, required=True)
    parser.add_argument("--tips-csv", type=Path, required=True)
    parser.add_argument("--release", default="user-supplied HITEMP/TIPS CSV")
    parser.add_argument("--output", type=Path,
                        default=Path("reports/hitemp_wsgg_calibration.json"))
    args = parser.parse_args()
    report = run_calibration(args.line_csv, args.tips_csv, args.output, release=args.release)
    print(f"Report: {args.output}")
    print(f"Lines: {report['provenance']['line_count_full_file']}; "
          f"TIPS rows: {report['provenance']['tips_rows']}")
    for n, result in report["results_by_n_gray_gases"].items():
        direct = result["direct_slice_weights"]["holdout"]
        poly = result["bernstein_temperature_weights"]["holdout"]
        print(f"N={n}: direct holdout MAPE={direct['mape_percent']:.4f}%; "
              f"Bernstein holdout MAPE={poly['mape_percent']:.4f}%")


if __name__ == "__main__":
    main()
