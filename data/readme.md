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
schemas.

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
