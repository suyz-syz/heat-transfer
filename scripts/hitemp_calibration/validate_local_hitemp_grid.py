"""Stream-validate an offline HITEMP alpha/tau grid against physical bounds."""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path


def sha256_file(path):
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-dir", type=Path, required=True)
    args = parser.parse_args()
    run = args.run_dir.resolve()
    grid_path = run / "spectral_grid_alpha_tau.csv"
    manifest = json.loads((run / "spectral_grid_manifest.json").read_text(encoding="utf-8"))
    tau_cols = []
    counts, first_last, previous_nu = Counter(), {}, {}
    bad_numeric = bad_alpha = bad_tau = bad_order = zero_species_errors = 0
    tau_monotonic_errors = 0
    with grid_path.open(newline="", encoding="utf-8-sig") as stream:
        reader = csv.DictReader(stream)
        tau_cols = [c for c in (reader.fieldnames or []) if c.startswith("tau_L")]
        if len(tau_cols) < 2:
            raise RuntimeError("expected multiple optical-path transmittance columns")
        for row in reader:
            key = (row["temperature_K"], row["pressure_atm"], row["composition"])
            counts[key] += 1
            try:
                nu = float(row["wavenumber_cm-1"])
                alpha = float(row["alpha_m-1"])
                taus = [float(row[c]) for c in tau_cols]
            except (TypeError, ValueError):
                bad_numeric += 1
                continue
            if not all(math.isfinite(x) for x in (nu, alpha, *taus)):
                bad_numeric += 1
                continue
            if alpha < 0:
                bad_alpha += 1
            if any(t < 0 or t > 1 for t in taus):
                bad_tau += 1
            if any(taus[i] + 1e-12 < taus[i + 1] for i in range(len(taus) - 1)):
                tau_monotonic_errors += 1
            if row["composition"] == "zero" and (alpha != 0 or any(t != 1 for t in taus)):
                zero_species_errors += 1
            if key not in first_last:
                first_last[key] = [nu, nu]
            else:
                if nu <= previous_nu[key]:
                    bad_order += 1
                first_last[key][1] = nu
            previous_nu[key] = nu
    expected_per_case = int(manifest["spectral_grid_cm-1"]["points"])
    wrong_counts = {"|".join(k): v for k, v in counts.items() if v != expected_per_case}
    result = {
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "grid_file": grid_path.name,
        "grid_sha256": sha256_file(grid_path),
        "rows": sum(counts.values()), "condition_spectra": len(counts),
        "expected_points_per_spectrum": expected_per_case,
        "wrong_spectrum_row_counts": wrong_counts,
        "first_last_wavenumber_cm-1": {"min": min(v[0] for v in first_last.values()),
                                      "max": max(v[1] for v in first_last.values())},
        "checks": {"nonfinite_numeric_rows": bad_numeric, "negative_alpha_values": bad_alpha,
                   "tau_outside_0_1": bad_tau, "tau_not_decreasing_with_path": tau_monotonic_errors,
                   "zero_species_not_transparent": zero_species_errors,
                   "nonincreasing_wavenumber_steps": bad_order},
    }
    result["passed"] = (not wrong_counts and not any(result["checks"].values())
                        and len(counts) == manifest["condition_spectra"])
    path = run / "grid_validation_report.json"
    path.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps(result, indent=2))
    if not result["passed"]:
        raise SystemExit("grid validation failed; see grid_validation_report.json")


if __name__ == "__main__":
    main()
