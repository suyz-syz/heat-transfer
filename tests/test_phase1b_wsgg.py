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
