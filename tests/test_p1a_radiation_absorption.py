import math

import pytest

from kiln_ht.models.radiation import leckner, wsgg
from kiln_ht.radiation import get_gas_radiation


P_CO2 = 1.0e4
P_H2O = 1.0e4
PATH = 1.0


def test_leckner_hottel_absorptivity_matches_emissivity_at_equal_temperature():
    result = leckner.evaluate(1400.0, 1400.0, P_CO2, P_H2O, PATH)
    assert result.absorptivity == pytest.approx(result.emissivity, rel=0.0, abs=1e-15)


def test_species_scaled_absorptivity_differs_at_large_temperature_gap():
    result = leckner.evaluate(1800.0, 900.0, P_CO2, P_H2O, PATH)
    assert math.isfinite(result.emissivity)
    assert math.isfinite(result.absorptivity)
    assert 0.0 <= result.absorptivity <= 1.0
    assert result.absorptivity != pytest.approx(result.emissivity, rel=1e-5)


@pytest.mark.parametrize("model", ["leckner", "wsgg"])
def test_equal_gas_and_wall_temperature_has_zero_net_radiation(model):
    result = get_gas_radiation(
        1300.0, 1300.0, P_CO2, P_H2O, PATH, eps_wall=0.85, model=model
    )
    assert result.q_rad == 0.0
    assert math.isfinite(result.h_rad)
    assert result.h_rad >= 0.0


@pytest.mark.parametrize("model", ["leckner", "wsgg"])
def test_zero_radiating_partial_pressures_are_safe_and_return_zero(model):
    result = get_gas_radiation(
        1800.0, 700.0, 0.0, 0.0, PATH, eps_wall=0.85, model=model
    )
    assert result.emissivity == 0.0
    assert result.absorptivity == 0.0
    assert result.q_rad == 0.0
    assert result.h_rad == 0.0


def test_reversing_temperature_difference_reverses_net_heat_flux():
    gas_hot = get_gas_radiation(
        1800.0, 900.0, P_CO2, P_H2O, PATH, eps_wall=0.85, model="leckner"
    )
    wall_hot = get_gas_radiation(
        900.0, 1800.0, P_CO2, P_H2O, PATH, eps_wall=0.85, model="leckner"
    )
    assert gas_hot.q_rad > 0.0
    assert wall_hot.q_rad < 0.0


@pytest.mark.parametrize("model", ["leckner", "wsgg"])
def test_large_temperature_difference_remains_finite(model):
    result = get_gas_radiation(
        2400.0, 450.0, 2.0e4, 1.5e4, 1.8, eps_wall=0.9, model=model
    )
    assert math.isfinite(result.q_rad)
    assert math.isfinite(result.h_rad)
    assert math.isfinite(result.emissivity)
    assert math.isfinite(result.absorptivity)


@pytest.mark.parametrize("eps_wall", [0.0, 0.7, 0.5])
def test_near_black_wall_formula_rejects_low_wall_emissivity(eps_wall):
    with pytest.raises(ValueError, match="eps_wall"):
        get_gas_radiation(1200.0, 900.0, P_CO2, P_H2O, PATH,
                          eps_wall=eps_wall, model="leckner")


def test_wsgg_remains_explicitly_provisional():
    assert wsgg.WSGGResult.__dataclass_fields__["model_name"].default == "wsgg"
    assert "provisional" in wsgg.__doc__.lower()
