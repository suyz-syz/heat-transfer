"""Regression tests for normalized kiln gas operating modes."""
import pytest

from kiln_ht import KilnParams, Layer, gas_fractions_for_mode, solve_wall


def test_combustion_mode_fills_residual_with_legacy_n2_o2_ratio():
    default = gas_fractions_for_mode(0.20, 0.08)
    assert default == pytest.approx(
        {"CO2": 0.20, "H2O": 0.08, "N2": 0.69, "O2": 0.03}
    )

    adjusted = gas_fractions_for_mode(0.18, 0.10)
    assert sum(adjusted.values()) == pytest.approx(1.0)
    assert adjusted["CO2"] == pytest.approx(0.18)
    assert adjusted["H2O"] == pytest.approx(0.10)
    assert adjusted["N2"] / adjusted["O2"] == pytest.approx(0.69 / 0.03)


def test_hot_air_mode_uses_clean_air_and_accepts_zero_co2():
    fractions = gas_fractions_for_mode(0.20, 0.08, mode="hot_air")
    assert fractions == {"CO2": 0.0, "H2O": 0.0, "N2": 0.79, "O2": 0.21}

    solution = solve_wall(
        [Layer(name="lining", thickness=0.10, k=1.8)],
        KilnParams(**fractions),
    )
    assert solution.Qprime > 0.0
    assert solution.eg == 0.0


def test_combustion_mode_rejects_co2_h2o_sum_above_one():
    with pytest.raises(ValueError, match="不能超过 1"):
        gas_fractions_for_mode(0.7, 0.31)


def test_unknown_gas_mode_is_rejected():
    with pytest.raises(ValueError, match="气相模式"):
        gas_fractions_for_mode(0.2, 0.08, mode="unknown")
