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
        f"{0.70:4.2f}"
    )
    parsed = parse_hitemp_line(raw, Path("fixture.par"))
    assert parsed is not None
    assert parsed["molecule"] == "CO2"
    assert parsed["isotope"] == "1"
    assert parsed["nu"] == pytest.approx(2200.123456)
    assert parsed["strength_ref"] == pytest.approx(1.0e-22)
    assert parsed["lower_energy"] == pytest.approx(100.0)
    assert parsed["temp_exponent"] == pytest.approx(0.70)
