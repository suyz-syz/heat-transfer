import numpy as np
import pytest
import pandas as pd

from scripts.assess_hitemp_grid_convergence import (
    BAND_CM_INV,
    CO2_FRACTIONS,
    DEFAULT_THRESHOLDS,
    GAS_TEMPERATURES_K,
    H2O_FRACTIONS,
    PRESSURE_CASES_ATM,
    _align_fine_to_coarse,
    _metrics_pass,
    compare_grids,
    composition_matrix,
    matched_wall_temperatures,
)


def test_pointwise_transmittance_max_is_diagnostic_not_convergence_gate():
    metrics = {name: 0.0 for name in DEFAULT_THRESHOLDS}
    metrics["transmittance_mean_absolute"] = DEFAULT_THRESHOLDS[
        "transmittance_mean_absolute"
    ]
    metrics["transmittance_max_absolute"] = 0.05
    assert _metrics_pass(metrics)
    metrics["transmittance_mean_absolute"] += 1e-9
    assert not _metrics_pass(metrics)


def test_reference_matrix_covers_required_temperatures_pressures_and_independent_compositions():
    assert GAS_TEMPERATURES_K == (600.0, 1000.0, 1200.0, 1600.0, 2000.0, 2400.0)
    assert PRESSURE_CASES_ATM == (0.3, 1.0, 3.0)
    pairs = composition_matrix()
    assert len(pairs) == len(CO2_FRACTIONS) * len(H2O_FRACTIONS) - 1
    assert (0.20, 0.0) in pairs
    assert (0.0, 0.15) in pairs
    assert all(0.0 <= co2 < 1.0 and 0.0 <= h2o < 1.0 and co2 + h2o < 1.0
               for co2, h2o in pairs)
    assert BAND_CM_INV == (2000.0, 2400.0)


def test_wall_temperature_points_are_bounded_and_matched_to_gas_temperature():
    for gas_temperature in GAS_TEMPERATURES_K:
        wall = matched_wall_temperatures(gas_temperature)
        assert len(wall) == 3
        assert all(0 < tw <= gas_temperature for tw in wall)
        assert wall[0] == pytest.approx(max(300.0, 0.5 * gas_temperature))


def test_grid_alignment_rejects_noninteger_refinement():
    coarse = np.linspace(2000.0, 2400.0, 5)
    fine = np.linspace(2000.0, 2400.0, 9)
    assert np.array_equal(_align_fine_to_coarse(coarse, fine, fine), coarse)
    with pytest.raises(ValueError, match="integer"):
        _align_fine_to_coarse(coarse, np.linspace(2000.0, 2400.0, 7), np.zeros(7))


def test_identical_lbl_grids_have_zero_convergence_error():
    wn_coarse = np.linspace(2000.0, 2400.0, 401)
    wn_fine = np.linspace(2000.0, 2400.0, 801)
    alpha_coarse = np.full_like(wn_coarse, 0.2)
    alpha_fine = np.full_like(wn_fine, 0.2)
    coarse = (wn_coarse, alpha_coarse)
    fine = (wn_fine, alpha_fine)
    metrics = compare_grids(
        coarse, fine, 1200.0, (600.0, 900.0, 1080.0), (0.05, 0.5, 5.0)
    )
    assert metrics["alpha_integral_relative"] == pytest.approx(0.0, abs=1e-6)
    assert metrics["transmittance_max_absolute"] == pytest.approx(0.0, abs=1e-6)
    assert metrics["band_emissivity_max_absolute"] == pytest.approx(0.0, abs=1e-6)
    assert metrics["black_wall_flux_max_relative"] == pytest.approx(0.0, abs=1e-6)


def test_grid_metrics_detect_a_changed_spectrum():
    coarse_wn = np.linspace(2000.0, 2400.0, 401)
    fine_wn = np.linspace(2000.0, 2400.0, 801)
    coarse_alpha = np.ones_like(coarse_wn) * 0.1
    fine_alpha = np.ones_like(fine_wn) * 0.2
    metrics = compare_grids(
        (coarse_wn, coarse_alpha), (fine_wn, fine_alpha),
        1200.0, (600.0, 900.0), (0.1, 1.0),
    )
    assert metrics["alpha_integral_relative"] > 0
    assert metrics["transmittance_max_absolute"] > 0
    assert metrics["band_emissivity_max_absolute"] > 0


def test_grid_comparison_detects_features_between_coarse_nodes():
    coarse_wn = np.linspace(2000.0, 2400.0, 401)
    fine_wn = np.linspace(2000.0, 2400.0, 801)
    coarse_alpha = np.full_like(coarse_wn, 0.1)
    # A narrow feature centered halfway between coarse nodes would be invisible
    # to a comparison that only sampled the fine spectrum at shared nodes.
    fine_alpha = 0.1 + 0.5 * np.exp(-((fine_wn - 2000.5) / 0.08) ** 2)
    metrics = compare_grids(
        (coarse_wn, coarse_alpha), (fine_wn, fine_alpha),
        1200.0, (600.0, 900.0), (0.1, 1.0),
    )
    assert metrics["alpha_integral_relative"] > 0
    assert metrics["transmittance_max_absolute"] > 0

def test_lbl_grid_has_exact_band_endpoints_at_both_resolutions():
    from scripts.hitemp_calibration.hitemp_wsgg_calibration import lbl_spectrum

    lines = pd.DataFrame([{
        "molec_id": 1, "local_iso_id": 1, "nu": 2200.0, "sw": 1e-22,
        "a": 1.0, "gamma_air": 0.07, "gamma_self": 0.3,
        "elower": 50.0, "n_air": 0.7, "delta_air": 0.0,
    }])
    tips = {(1, 1): (np.array([296.0, 2400.0]), np.array([100.0, 1000.0]))}
    for step, expected_points in ((0.01, 40001), (0.005, 80001), (0.0025, 160001)):
        wn, alpha = lbl_spectrum(lines, tips, 1200.0, 1.0, 0.12, 0.08, step=step)
        assert len(wn) == len(alpha) == expected_points
        assert wn[0] == 2000.0
        assert wn[-1] == 2400.0
