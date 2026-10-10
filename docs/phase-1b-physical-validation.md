# Phase 1B Physical Accuracy Assessment

**Status: NOT YET SCIENTIFICALLY VALIDATED — do not merge on the strength of CI alone.**

Date: 2026-10-09  
Branch: `feat/phase-1b-hitemp-wsgg`  
Scope: HITEMP line-by-line (LBL) ingestion, spectral absorption/emission, and WSGG fitting.

## Executive finding

A source audit found a unit-conversion defect in the initial LBL implementation. HITRAN/HITEMP line intensity is conventionally reported in `cm^-1/(molecule cm^-2)`, equivalent to `cm/molecule`. With a normalized line profile in `cm`, the product is a cross-section in `cm^2/molecule`. Multiplying by number density in `molecule/m^3` requires conversion of `cm^2` to `m^2` by `1e-4`; the previous expression included an additional factor of 100. This has been corrected.

The line-strength temperature correction now accepts tabulated partition sums and performs log-log interpolation without extrapolation. If no table is supplied, it still uses a power-law approximation; results from that fallback must not be described as HITEMP/TIPS-validated.

The LBL heat-flux path now integrates the spectral net exchange over the supplied wavenumber grid. A total-flux claim requires both sufficiently broad spectral coverage and grid-convergence checks. A narrow band or incomplete line list gives a band-limited result, not a validated total radiative heat flux.

## Scientific data availability

No real HITEMP line-list file or TIPS partition-sum table was bundled with this repository or available in the checked-out branch at the time of this assessment. The official HITEMP download flow is hosted at <https://www.hitran.org/hitemp/> and may require a HITRANonline account. The source files and their provenance must be recorded before producing numerical accuracy claims.

Expected normalized line-list CSV columns:
- `molecule`
- `nu` (vacuum wavenumber, cm^-1)
- `strength_ref` (296 K line intensity, cm^-1/(molecule cm^-2))
- `lower_energy` (cm^-1)
- `air_gamma`, `self_gamma` (HWHM, cm^-1/atm at 296 K)
- `temp_exponent`
- `partition_ref`, `partition_exponent` (fallback only)
- optional `isotope`

The CSV must be a documented conversion from a named HITEMP release, not hand-entered synthetic data. Partition-sum tables passed to the API must cover 296 K and every simulated temperature (300–2400 K); keys are molecule names or `MOLECULE:isotope` identifiers.

## Current verification matrix

| Item | Result |
|---|---|
| CI software regression | **67 passed** on commit `5750c0ba7eb78b0a026c6dd8636f87bd70556130` (GitHub Actions run 37863445652) |
| Synthetic WSGG recovery | Software test only; not evidence of HITEMP accuracy |
| LBL line-strength unit conversion | Corrected and covered by an analytical unit test; CI passed |
| TIPS table interpolation / no extrapolation | Added and tested; CI passed |
| Spectral net flux integration | Added and tested; CI passed |
| Actual HITEMP CO2/H2O benchmark | **Not run — source data not supplied/available in this workspace** |
| 300–2400 K × 0.1–10 atm × CO2/H2O composition sweep | **Not run on real spectral data** |
| Mean / maximum relative heat-flux error | **Not available; must not be fabricated** |
| Deployable temperature/composition-dependent WSGG coefficients | **Not available** |

## Calibration method to run when source data are available

1. Record the HITEMP release, download date, species/isotopologue IDs, wavenumber coverage, original filenames, checksums, and the exact CSV conversion script.
2. Load matching TIPS partition sums for each isotopologue. Do not use the power-law fallback for the scientific acceptance run.
3. Use a broad spectral grid covering the relevant Planck emission range and run a grid-spacing convergence check. The line list and grid must cover the same declared spectral domain.
4. For each state in the requested temperature, pressure, and CO2/H2O composition matrix, calculate LBL emissivity versus path length.
5. Fit WSGG coefficients on training path lengths and evaluate only on held-out path lengths. The current calibration sweep fits state-specific coefficients; a separate regression and held-out state validation is required before these coefficients can be used as a generalized `a_j(T, composition, pressure)` correlation.
6. Report mean absolute relative heat-flux error, maximum absolute relative error, maximum absolute deviation in W/m², and worst-case state. Exclude or separately flag points where the LBL net flux is near zero, because relative error is ill-conditioned there.
7. Compare results at increasing gray-gas counts (for example N=3, 4, 5, 6) and select N by held-out performance and stability, not training error alone.

## Acceptance criteria (to be agreed before seeing results)

Do not silently choose or loosen thresholds after observing the result. The project owner should define allowable mean and maximum heat-flux errors for the intended kiln application. In the absence of approved limits and real HITEMP/TIPS inputs, no “accuracy passed” conclusion is possible.

## Current conclusion

The audit identified and corrected a material unit-conversion defect and added more physically appropriate spectral heat-flux and partition-sum interfaces. These are necessary corrections, not proof of accuracy. PR #4 should remain unmerged until the real-data sweep, spectral/grid convergence, and held-out WSGG validation are complete.
