# HITEMP/TIPS offline calibration data

The committed files in this directory are a narrow-band sample for offline
pipeline validation. They are not a complete HITEMP line database and do not
support total-spectrum or industrial-release claims.

## Canonical CSV contract

Line CSV columns, in order:

`molec_id,local_iso_id,nu,sw,a,gamma_air,gamma_self,elower,n_air,delta_air`

The molecule value is the numeric HITRAN ID (1=H2O, 2=CO2); the isotope value
is its local isotopologue ID. Wavenumber and broadening fields retain the source
units and numerical values. TIPS columns are
`molecule,isotope,temperature_K,Q`, where molecule and isotope are numeric IDs.
Both calibration command-line entrypoints accept these same line and TIPS
schemas. The current offline trial filters line centers to 1975–2425 cm⁻¹ and
evaluates the 2000–2400 cm⁻¹ band; the wider sample file range does not imply
full-spectrum validation.

The fixed-width conversion rules are in
`scripts/prepare_hitemp_benchmark.py`; the audit is reproducible with:

```sh
python scripts/audit_hitemp_manifest.py --check
python scripts/audit_hitemp_manifest.py --write
```

The checked-in [manifest](../reports/hitemp_dataset_manifest.json) records
SHA-256 digests, byte and record counts, observed wavenumber/temperature ranges,
and per-isotopologue line/TIPS coverage. The exact upstream HITEMP and TIPS
release identifiers are not recorded in the repository, so their authenticity
and completeness remain unverified. Do not infer completeness from observed
isotope IDs.

All LBL, parsing, calibration, and fitting code is isolated in
`scripts/hitemp_calibration/`. It is not imported by the runtime heat-transfer
solver. Production radiation paths and the provisional status are unchanged.

## Experimental runtime lookup grid

`spectral_grid_alpha_tau.csv` is a separately archived, opt-in lookup table for
the `hitemp_grid` radiation model. It contains pseudo-Voigt LBL absorption
coefficients over 1025–3975 cm⁻¹ at 0.25 cm⁻¹ spacing. The 25 cm⁻¹ margins
come from line centers extracted over 1000–4000 cm⁻¹. The source line list was
filtered at `sw >= 1e-26 cm/molecule` for this grid. This is a band-limited
experimental model, not total-spectrum radiation or an independently validated
production coefficient set.

The `hitemp_grid` option is disabled by default; Leckner remains the baseline.
The lookup refuses temperatures, pressures, compositions, or path lengths
outside the recorded grid domain and never silently extrapolates or falls back.
`manifest.json` records source archive hashes, grid axes, line-selection
statistics, and the spectral grid checksum. The large grid CSV is stored with
Git LFS; the 3.4 GB full extracted line table is not part of this data directory.
