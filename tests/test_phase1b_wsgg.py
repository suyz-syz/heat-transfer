import math

import pytest

from kiln_ht.models.radiation.hitemp_lbl import (
    SpectralLine, absorption_spectrum, gas_emissivity_from_spectrum, line_strength,
)
from kiln_ht.models.radiation.wsgg_fit import fit_wsgg, wsgg_emissivity


def test_line_strength_temperature_scaling_is_finite():
    line = SpectralLine("CO2", 2200.0, 1e-22, 100.0, 0.07, 0.1,
                        0.7, 1.0, 1.5)
    for t in (300, 500, 800, 1200, 1600, 2000):
        assert math.isfinite(line_strength(line, t))
        assert line_strength(line, t) >= 0


def test_lbl_spectrum_and_planck_weighted_emissivity():
    lines = [
        SpectralLine("CO2", 2200.0, 1e-22, 100.0, 0.07, 0.1, 0.7, 1.0, 1.5),
        SpectralLine("H2O", 1800.0, 2e-22, 200.0, 0.08, 0.2, 0.7, 1.0, 1.5),
    ]
    grid = [1500.0 + i*5.0 for i in range(201)]
    alpha = absorption_spectrum(lines, grid, 1200.0, 1.0,
                                {"CO2": 0.12, "H2O": 0.08}, 1.5)
    assert len(alpha) == len(grid)
    assert all(math.isfinite(x) and x >= 0 for x in alpha)
    eps = gas_emissivity_from_spectrum(alpha, grid, 1200.0, 1.5)
    assert 0 <= eps <= 1


def test_planck_weight_uses_cm_inverse_with_cm_kelvin_constant():
    # For a constant absorption coefficient the emissivity is constant; use
    # a piecewise spectrum to verify the Planck weights are evaluated with
    # C2 in cm K and wavenumber in cm^-1 (not an extra factor of 100).
    grid = [2000.0, 2100.0, 2200.0, 2300.0, 2400.0]
    alpha = [0.0, 0.0, 1.0, 1.0, 1.0]
    temperature = 1200.0
    path = 1.0
    actual = gas_emissivity_from_spectrum(alpha, grid, temperature, path)
    c2 = 1.438776877
    weights = []
    absorptances = [0.0, 1.0 - math.exp(-0.5), 1.0 - math.exp(-1.0),
                    1.0 - math.exp(-1.0)]
    for left, right in zip(grid, grid[1:]):
        wn = 0.5 * (left + right)
        weights.append(wn**3 / math.expm1(c2 * wn / temperature))
    expected = sum(w * a for w, a in zip(weights, absorptances)) / sum(weights)
    assert actual == pytest.approx(expected, rel=1e-12)


def test_wsgg_fit_recovers_synthetic_emissivity_curve():
    lengths = [0.05 + i*0.05 for i in range(30)]
    target = [wsgg_emissivity((0.25, 0.35, 0.2), (0.2, 2.0, 20.0), l)
              for l in lengths]
    fitted = fit_wsgg(lengths, target, n_gases=3, kappa_min=0.05,
                      kappa_max=30, grid_size=100, iterations=3000)
    assert fitted.samples == len(lengths)
    assert fitted.rmse < 0.03
    assert fitted.max_abs_error < 0.06
    assert all(w >= 0 for w in fitted.weights)
    assert all(k >= 0 for k in fitted.kappa)


def test_wsgg_rejects_invalid_inputs():
    with pytest.raises(ValueError):
        wsgg_emissivity((-0.1,), (1.0,), 1.0)
    with pytest.raises(ValueError):
        fit_wsgg((1.0,), (0.2,), n_gases=2)



def test_tips_partition_table_overrides_power_law_approximation():
    line = SpectralLine("CO2", 2200.0, 1e-22, 100.0, 0.07, 0.1,
                        0.7, 1.0, 9.0)
    table = {"CO2": [(296.0, 100.0), (1000.0, 1000.0), (2500.0, 5000.0)]}
    ratio = line_strength(line, 1000.0, partition_sums=table) / line_strength(
        SpectralLine("CO2", 2200.0, 1e-22, 100.0, 0.07, 0.1,
                     0.7, 1.0, 0.0), 1000.0
    )
    assert ratio == pytest.approx(0.1, rel=1e-12)


def test_absorption_coefficient_unit_conversion_has_no_extra_factor_100():
    from kiln_ht.models.radiation import hitemp_lbl

    line = SpectralLine("CO2", 2200.0, 1e-22, 100.0, 0.07, 0.1,
                        0.7, 1.0, 0.0)
    temperature = 296.0
    pressure = 1.0
    xco2 = 0.1
    alpha = absorption_spectrum([line], [line.nu], temperature, pressure,
                                {"CO2": xco2}, 1.0)[0]
    mass_kg = 44.0095 / 1000.0 / 6.02214076e23
    sigma_d = line.nu * math.sqrt(
        hitemp_lbl.K_B * temperature / (mass_kg * 299792458.0**2)
    )
    gamma = pressure * (line.air_gamma * (1.0-xco2) + line.self_gamma*xco2)
    profile = hitemp_lbl._pseudo_voigt(0.0, sigma_d, gamma)
    number_density = xco2 * pressure * 101325.0 / (hitemp_lbl.K_B*temperature)
    expected = line.strength_ref * profile * number_density * 1e-4
    assert alpha == pytest.approx(expected, rel=1e-12)


def test_spectral_net_flux_is_finite_and_positive_for_hot_gas():
    from kiln_ht.models.radiation.hitemp_lbl import spectral_net_radiative_flux

    q = spectral_net_radiative_flux(
        [0.2] * 5, [500.0, 1000.0, 1500.0, 2000.0, 2500.0],
        1200.0, 700.0, 1.5,
    )
    assert math.isfinite(q)
    assert q > 0


def test_hitemp_benchmark_builder_parses_standard_molecule_ids():
    from pathlib import Path
    from scripts.prepare_hitemp_benchmark import parse_hitemp_line

    # Standard fixed-width identifiers are right-justified (" 2" for CO2).
    raw = (
        f"{2:2d}{1:1d}{2200.123456:12.6f}{1.0e-22:10.3E}"
        f"{1.0:10.3E}{0.070:5.3f}{0.100:5.3f}{100.0000:10.4f}"
        f"{0.70:4.2f}" + " " * 101
    )
    parsed = parse_hitemp_line(raw, Path("fixture.par"))
    assert parsed is not None
    assert parsed["molecule"] == "CO2"
    assert parsed["isotope"] == "1"
    assert parsed["nu"] == pytest.approx(2200.123456)
    assert parsed["strength_ref"] == pytest.approx(1.0e-22)
    assert parsed["lower_energy"] == pytest.approx(100.0)
    assert parsed["temp_exponent"] == pytest.approx(0.70)


def test_literature_emissivity_parser_and_fit_smoke(tmp_path):
    from scripts.benchmark_literature_emissivity import parse_emissivity_table, run_fit

    source = tmp_path / "R=01.000_EM2C-SNB_totalEmissivities_90x105.dat"
    pls = [0.01 * (1.5 ** i) for i in range(8)]
    temperatures = [300.0, 600.0, 900.0, 1200.0, 1500.0]
    with source.open("w", encoding="utf-8") as stream:
        stream.write("Synthetic parser fixture for software testing only; not literature data.\n")
        stream.write("90 105 0.01 300 2900 metadata fields must be ignored\n")
        for pl in pls:
            for temp in temperatures:
                eps = 0.2 * (1.0 - math.exp(-0.8 * pl)) + 0.3 * (
                    1.0 - math.exp(-8.0 * pl)
                )
                stream.write(f"{pl:.10g} {temp:.1f} {eps:.12g}\n")

    data = parse_emissivity_table(source)
    assert len(data["temperature_K"]) == len(temperatures)
    assert len(data["pressure_pathlength_atm_m"]) == len(pls)
    result = run_fit(data, n_gases=3, wall_temperature_k=800.0)
    assert len(result["shared_kappa_per_atm_m_inverse"]) == 3
    assert len(result["weight_polynomial_coefficients_low_to_high"]) == 3
    assert result["temperature_polynomial_weight_holdout_metrics"]["heldout_points"] > 0
    assert result["temperature_polynomial_weight_holdout_metrics"][
        "max_black_wall_flux_proxy_error_W_m2"
    ] >= 0



def test_builtin_physics_inspired_ground_truth_domain_and_label():
    from scripts.benchmark_literature_emissivity import generate_builtin_ground_truth

    data = generate_builtin_ground_truth()
    assert data["temperature_K"][0] == 300.0
    assert data["temperature_K"][-1] == 2500.0
    assert min(data["pressure_pathlength_atm_m"]) == pytest.approx(0.01)
    assert max(data["pressure_pathlength_atm_m"]) == pytest.approx(10.0)
    assert len(data["temperature_K"]) == 23
    assert len(data["pressure_pathlength_atm_m"]) == 31
    assert data["ground_truth_model"]["not_a_leckner_or_snb_solver"] is True
    assert data["ground_truth_model"]["not_hitemp_lbl"] is True
    for temp in data["temperature_K"]:
        values = data["emissivity"][str(temp)]
        assert len(values) == 31
        assert all(0.0 <= value <= 1.0 for value in values)
        assert values == sorted(values)


def test_hitemp_calibration_runner_generates_n345_provenance_report(tmp_path):
    import csv
    import json
    from scripts.calibrate_hitemp_wsgg import run_calibration

    line_csv = tmp_path / "lines.csv"
    with line_csv.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=[
            "molecule", "nu", "strength_ref", "lower_energy", "air_gamma",
            "self_gamma", "temp_exponent", "partition_ref",
            "partition_exponent", "isotope",
        ])
        writer.writeheader()
        writer.writerow({
            "molecule": "CO2", "nu": 2200.0, "strength_ref": 1e-20,
            "lower_energy": 100.0, "air_gamma": 0.07, "self_gamma": 0.1,
            "temp_exponent": 0.7, "partition_ref": 1.0,
            "partition_exponent": 0.0, "isotope": "1",
        })
    tips_csv = tmp_path / "tips.csv"
    with tips_csv.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=[
            "molecule", "isotope", "temperature_K", "Q",
        ])
        writer.writeheader()
        for temp, q_value in ((296.0, 100.0), (500.0, 200.0), (800.0, 400.0)):
            writer.writerow({
                "molecule": "CO2", "isotope": "1",
                "temperature_K": temp, "Q": q_value,
            })
    output = tmp_path / "report.json"
    report = run_calibration(
        line_csv, tips_csv, output, release="synthetic-test-fixture",
        wn_min_cm=2190.0, wn_max_cm=2210.0, wn_step_cm=1.0,
        temperatures_k=(500.0,), path_min_m=0.05, path_max_m=2.0,
        path_count=8, fit_grid_size=20, fit_iterations=30,
    )
    saved = json.loads(output.read_text(encoding="utf-8"))
    assert report["report_type"].startswith("HITEMP/TIPS-derived")
    assert saved["provenance"]["line_count"] == 1
    assert set(saved["results"][0]["fits_by_n_gray_gases"]) == {"3", "4", "5"}
    assert "not total-spectrum emissivity" in " ".join(saved["limitations"])
