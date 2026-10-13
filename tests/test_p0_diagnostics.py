"""P0 regressions for result meaning, solver diagnostics, and balance closure.

The sensitivity matrix is intentionally a reserved P1 experiment design. P0
defines its axes but does not sweep them or introduce a new physical model.
"""
import json
import math

import pytest

from kiln_ht import KilnParams, Layer, solve_kiln, solve_wall
from kiln_ht.export import build_report
from kiln_ht.visualization import axial_plot_data

LAYERS = [
    Layer(name="fiber", thickness=0.15, k=0.10),
    Layer(name="brick", thickness=0.08, k=1.2),
    Layer(name="steel", thickness=0.012, k=45.0),
]

# P1 sensitivity-scan axes (no P0 numerical claims are made from this matrix).
P1_SENSITIVITY_MATRIX = {
    "G_wb_over_G_gw": (0.01, 0.1, 1.0, 10.0),
    "G_wb_over_G_cond": (0.01, 0.1, 1.0, 10.0),
    "gas_bed_temperature_difference_k": (50.0, 300.0, 800.0),
    "gas_heat_capacity_rate_w_k": (1.0e4, 1.0e5),
    "bed_heat_capacity_rate_w_k": (1.0e3, 1.0e4),
    "bed_flow_direction": ("co-current", "counter-current"),
}


def _three_phase_kwargs(**overrides):
    result = {
        "n_cells": 3,
        "mass_flow_kg_s": 10.0,
        "cp_gas_j_kg_k": 1150.0,
        "bed_inlet_temperature_k": 350.0,
        "bed_mass_flow_kg_s": 2.0,
        "cp_bed_j_kg_k": 1000.0,
        "gas_bed_h_w_m2_k": 20.0,
        "wall_bed_h_w_m2_k": 50.0,
        "gas_bed_area_per_length_m": 1.0,
        "wall_bed_contact_per_length_m": 0.2,
        "bed_flow_direction": "counter-current",
    }
    result.update(overrides)
    return result


def test_success_results_always_have_serializable_diagnostics():
    params = KilnParams(L_kiln=6.0, T_gas=800.0)
    radial = solve_wall(LAYERS, params)
    radial_data = radial.as_dict()
    assert radial_data["diagnostics"]["converged"] is True
    assert radial_data["diagnostics"]["iteration_count"] > 0
    assert math.isfinite(radial_data["diagnostics"]["max_temperature_change_k"])
    assert math.isfinite(radial_data["diagnostics"]["max_energy_residual_relative"])

    two_phase = solve_kiln(LAYERS, params, n_cells=2, mass_flow_kg_s=20.0)
    two_data = two_phase.as_dict()
    assert two_data["diagnostics"]["converged"] is True
    assert two_data["diagnostics"]["iteration_count"] is None
    assert two_data["diagnostics"]["max_temperature_change_k"] is None
    assert math.isfinite(two_data["diagnostics"]["max_energy_residual_w"])

    three_phase = solve_kiln(LAYERS, params, **_three_phase_kwargs())
    three_data = three_phase.as_dict()
    assert three_data["diagnostics"]["iteration_count"] > 0
    assert three_data["diagnostics"]["max_temperature_change_k"] is not None
    assert three_data["diagnostics"]["energy_residual_status"] == "checked"
    # Strict JSON encoding catches missing defaults and non-finite values.
    json.dumps({"radial": radial_data, "two_phase": two_data, "three_phase": three_data},
               allow_nan=False)


def test_zero_bed_exchange_limit_returns_the_local_radial_baseline():
    params = KilnParams(L_kiln=2.0, T_gas=800.0)
    result = solve_kiln(
        LAYERS,
        params,
        n_cells=1,
        mass_flow_kg_s=20.0,
        cp_gas_j_kg_k=1150.0,
        bed_inlet_temperature_k=350.0,
        bed_mass_flow_kg_s=2.0,
        cp_bed_j_kg_k=1000.0,
        gas_bed_h_w_m2_k=1.0e-12,
        wall_bed_h_w_m2_k=1.0e-12,
        gas_bed_area_per_length_m=1.0,
        wall_bed_contact_per_length_m=0.2,
        coupling_tolerance_k=1.0e-8,
    )
    # In the zero exchange limit, coupled wall nodes recover the radial
    # baseline conductance solution evaluated at that cell's mean gas temp.
    baseline = result.wall_solutions[0]
    state = result.states[0]
    assert state.T_wall_inner_k == pytest.approx(baseline.T_w1, abs=1.0e-5)
    assert state.T_wall_outer_k == pytest.approx(baseline.T_wN, abs=1.0e-5)


@pytest.mark.parametrize("direction", ["co-current", "counter-current"])
def test_three_phase_energy_residual_covers_all_cells_and_is_repeatable(direction):
    params = KilnParams(L_kiln=6.0, T_gas=800.0)
    kwargs = _three_phase_kwargs(bed_flow_direction=direction)
    first = solve_kiln(LAYERS, params, **kwargs)
    second = solve_kiln(LAYERS, params, **kwargs)
    assert first.max_energy_residual_w < 5.0
    assert first.as_dict()["diagnostics"]["max_energy_residual_w"] == pytest.approx(
        first.max_energy_residual_w
    )
    for state_a, state_b in zip(first.states, second.states):
        assert state_a.as_dict() == pytest.approx(state_b.as_dict(), abs=1.0e-10)


def test_three_phase_nonconvergence_is_an_explicit_failure():
    params = KilnParams(L_kiln=6.0, T_gas=800.0)
    with pytest.raises(RuntimeError, match="did not converge"):
        solve_kiln(
            LAYERS,
            params,
            **_three_phase_kwargs(coupling_max_iterations=1),
        )


def test_axial_adapter_and_export_preserve_model_semantics():
    params = KilnParams(L_kiln=6.0, T_gas=800.0)
    result = solve_kiln(LAYERS, params, **_three_phase_kwargs())
    axial = axial_plot_data(result)
    assert axial["model_semantics"]["states"].startswith("authoritative")
    assert axial["model_semantics"]["wall_solutions"].startswith("radial")
    assert axial["model_semantics"]["three_phase_wall_model"] == "linearized network approximation"
    report = build_report(LAYERS, params, result.wall_solutions[0])
    assert "线性化网络近似" in report
    assert "provisional" in report
    assert "不构成工业定型或热应力绝对保证值" in report


def test_p1_sensitivity_matrix_declares_required_dimensions():
    assert set(P1_SENSITIVITY_MATRIX) == {
        "G_wb_over_G_gw",
        "G_wb_over_G_cond",
        "gas_bed_temperature_difference_k",
        "gas_heat_capacity_rate_w_k",
        "bed_heat_capacity_rate_w_k",
        "bed_flow_direction",
    }
    assert P1_SENSITIVITY_MATRIX["bed_flow_direction"] == (
        "co-current",
        "counter-current",
    )


def test_api_solve_response_has_radial_scope_and_stable_diagnostic_keys():
    from server import LayerIn, SolveRequest, solve

    response = solve(SolveRequest(layers=[
        LayerIn(name="fiber", thickness=0.15, k=0.1),
        LayerIn(name="steel", thickness=0.012, k=45.0),
    ]))
    assert response["model_semantics"]["result"] == "radial steady-state wall baseline"
    assert response["model_semantics"]["wsgg_status"] == "provisional"
    assert response["diagnostics"]["converged"] is True
    json.dumps(response, allow_nan=False)
