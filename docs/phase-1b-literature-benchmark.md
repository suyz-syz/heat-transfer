# Literature-reference emissivity benchmark (transition stage)

**Reference source:** Marzouk, O. A. (2025), *Dataset of total emissivity for CO2, H2O, and H2O-CO2 mixtures; over a temperature range of 300-2900 K and a pressure-pathlength range of 0.01-50 atm.m*, Data in Brief 59, 111428. DOI: 10.17632/x5wjzk6sjs.1. Public dataset: https://data.mendeley.com/datasets/x5wjzk6sjs/1 (CC BY 4.0).

**Scientific label:** this is the published EM2C statistical narrow-band model (SNB) emissivity dataset. It is *not* an HITEMP line-by-line data file and must not be described as a Bordbar/Cassol/Johansen HITEMP-LBL ground truth. It is a transition benchmark for testing WSGG fitting and error accounting while local HITEMP downloads are pending.

## Scope and known limitations

- 10 gas compositions (H2O:CO2 molar ratios from pure CO2 to pure H2O), 300–2900 K, 90 pressure-pathlength points from 0.01 to 50 atm.m.
- The source dataset states total pressure is fixed at 1 atm. Its varying variable is pressure × path length, not independent total pressure. It cannot validate an independent 0.1–10 atm pressure sweep.
- Ground truth is spectrally integrated total emissivity, not spectral line data or wall heat flux.
- Optional heat-flux output is only a gray black-wall flux proxy, abs(delta_epsilon) * sigma * abs(Tgas^4 - Twall^4), and requires an explicitly supplied wall temperature. Do not interpret it as a general non-gray wall heat-flux solution.
- N=3,4,5 parameters are fitted per composition. The shared gray-gas absorption coefficients are common across temperature within a composition; weights are fitted at each temperature and then regressed as a quartic polynomial in T/1000 K. Polynomial extrapolation beyond the source range is not validated.

## Run the benchmark

Download the public dataset ZIP from the Mendeley Data page and unpack the desired R=..._EM2C-SNB_totalEmissivities_90 × 105.dat files locally. For one composition:

~~~bash
python scripts/benchmark_literature_emissivity.py \
  --input /path/to/R=01.000_EM2C-SNB_totalEmissivities_90x105.dat \
  --output reports/literature_wsgg_R1.json \
  --wall-temperature-k 800
~~~

The runner trains on alternating pressure-pathlength samples and reports held-out emissivity MAPE, maximum absolute emissivity error, the worst case, shared kappa values, polynomial weight coefficients, and optional gray flux-proxy deviation. Omit the wall-temperature option to avoid presenting a proxy as a wall heat-flux result.

Run all compositions by supplying repeated --input arguments. Retain the original downloaded files and cite the dataset DOI with any report.

## Acceptance and handoff

This benchmark can establish whether the WSGG fitting and error-reporting pipeline behaves correctly against a published integrated-emissivity reference. It does not establish HITEMP LBL accuracy, independent pressure generalization, or engineering acceptance for a rotary kiln. Those remain blocked until local HITEMP line lists/TIPS tables are used for the spectral LBL calculations and the owner approves error thresholds.
