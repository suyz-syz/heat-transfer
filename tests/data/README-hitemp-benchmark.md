# Phase 1B HITEMP feature-band benchmark data

No synthetic spectra or hand-entered line parameters are accepted as physical ground truth. This directory is intentionally data-empty until source HITEMP and matching TIPS files are supplied and their provenance can be recorded.

## Prepare a source-derived sample

1. Obtain the appropriate HITEMP CO2 and H2O .par files from [HITRANonline HITEMP](https://www.hitran.org/hitemp/). Record the release/version for each species; the current CO2 and H2O lists may come from different releases.
2. Obtain the partition-sum Q(T) files for every isotopologue represented in the selected line lists from [HITRANonline isotopologue metadata](https://hitran.org/docs/iso-meta/). Convert the values into a UTF-8 CSV with columns molecule,isotope,temperature_K,Q, using molecule CO2 or H2O and the numeric HITRAN isotopologue ID. The table must cover 296–2400 K and have positive, unique values at each temperature.
3. Run the builder from the repository root, supplying each source file separately:

\`\`\`bash
python scripts/prepare_hitemp_benchmark.py \\
  --line-file /path/to/hitemp_co2.par \\
  --line-file /path/to/hitemp_h2o.par \\
  --tips-csv /path/to/tips_partition_sums.csv \\
  --release "CO2-HITEMP-2024; H2O-HITEMP-2010" \\
  --output-dir tests/data/generated
\`\`\`

The builder selects line centers from 975–4025 cm-1 by default to retain a 25 cm-1 wing margin around the nominal 1000–4000 cm-1 band. It writes a normalized line CSV, a 296–2400 K TIPS CSV, and a manifest containing source/output SHA-256 hashes, selected isotopologues, release labels, and limitations. Review the exact source layout and release notes before treating the output as valid.

## Important limitations

- The generated feature-band sample is truncated. It can support a **band-limited benchmark only**, not a claim about total-spectrum kiln heat flux.
- The present LBL engine uses pseudo-Voigt profiles and simplified air/self pressure broadening. Passing this sample benchmark is not, by itself, metrology-grade validation.
- Do not commit source data unless their distribution terms explicitly permit repository redistribution. Keep the manifest and source references with any approved benchmark artifact.
- No sample lines, TIPS values, fitted WSGG coefficients, or error metrics are included here yet because no authentic source files were available in the execution environment.
