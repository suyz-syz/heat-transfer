import numpy as np
import pytest

from kiln_ht.models.radiation.hitemp_wsgg_calibration import (
    constrained_bernstein_coefficients,
    evaluate_bernstein_weights,
    simplex_weights,
)


def test_softmax_weights_obey_hard_simplex_constraints():
    for logits in ([0.0, 0.0], [20.0, -20.0, 0.5], [-100.0, 0.0, 100.0]):
        weights = simplex_weights(logits)
        assert np.all(weights >= 0.0)
        assert np.sum(weights) == pytest.approx(1.0, abs=1e-14)


def test_nonnegative_bernstein_coefficients_preserve_simplex():
    temperatures = np.array([600.0, 1000.0, 1400.0, 1800.0, 2400.0])
    weights = np.array([
        [0.7, 0.2, 0.1],
        [0.6, 0.25, 0.15],
        [0.5, 0.3, 0.2],
        [0.4, 0.35, 0.25],
        [0.3, 0.4, 0.3],
    ])
    coeff = constrained_bernstein_coefficients(temperatures, weights, degree=3)
    assert np.all(coeff >= 0.0)
    for temperature in np.linspace(600.0, 2400.0, 31):
        result = evaluate_bernstein_weights(temperature, (600.0, 2400.0), coeff)
        assert np.all(result >= 0.0)
        assert np.sum(result) == pytest.approx(1.0, abs=1e-14)


def test_bernstein_temperature_extrapolation_is_rejected():
    coeff = np.ones((3, 4))
    with pytest.raises(ValueError, match="outside"):
        evaluate_bernstein_weights(2500.0, (600.0, 2400.0), coeff)
