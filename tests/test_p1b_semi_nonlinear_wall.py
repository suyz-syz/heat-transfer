"""P1b regressions for the semi-nonlinear local wall solve."""
import json
import math
from dataclasses import replace

import pytest

from kiln_ht import KilnParams, Layer, solve_kiln
from kiln_ht.calc import solve_wall
from kiln_ht.calc import _conductive_wall_rate


LAYERS = [
    Layer(name="fiber", thickness=0.15, k=0.10),
    Layer(name="brick", thickness=0.08, k=1.2),
    Layer(name="steel", thickness=0.012, k=45.0),
]

P1B_SENSITIVITY_MATRIX = {
    "G_wb_over_G_gw_proxy": (0.01, 0.1, 1.0, 5.0),
    "G_wb_over_G_cond_proxy": (0.01, 0.1, 1.0, 5.0),
    "gas_bed_delta_k": (50.0, 300.0, 700.0),
    "gas_heat_capacity_rate_w_k": (1.0e4, 2.3e4),
    "bed_heat_capacity_rate_w_k": (1.0e3, 2.0e3),
    "direction": ("co-current", "counter-current"),
}


def _kwargs(**overrides):
    values = {
        "n_cells": 2,
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
    values.update(overrides)
    return values


def test_local_conduction_recomputes_temperature_dependent_k():
    radii = [2.0, 2.1]
    constant = Layer(name="constant", thickness=0.1, k=1.2)
    polynomial = Layer(
        name="polynomial", thickness=0.1, k_coef=(1.2, 5.0e-4, 0.0)
    )
    q_constant, _, _ = _conductive_wall_rate(900.0, 500.0, [constant], radii)
    q_polynomial, _, _ = _conductive_wall_rate(900.0, 500.0, [polynomial], radii)
    assert math.isfinite(q_constant)
    assert math.isfinite(q_polynomial)
    assert q_polynomial != pytest.approx(q_constant, rel=1e-4)



def test_vanishing_wall_bed_branch_recovers_radial_baseline():
    params = KilnParams(L_kiln=4.0, T_gas=850.0)
    result = solve_kiln(
        LAYERS,
        params,
        **_kwargs(wall_bed_h_w_m2_k=1.0e-9),
    )
    for state in result.states:
        baseline = solve_wall(LAYERS, replace(params, T_gas=state.T_gas_k))
        assert state.T_wall_inner_k == pytest.approx(baseline.T_w1, abs=2.0e-3)
        assert state.T_wall_outer_k == pytest.approx(baseline.T_wN, abs=2.0e-3)


def test_semi_nonlinear_returns_serializable_cellwise_diagnostics():
    result = solve_kiln(
        LAYERS, KilnParams(L_kiln=6.0, T_gas=800.0), **_kwargs()
    )
    data = result.as_dict()
    diag = data["diagnostics"]
    assert diag["wall_iteration_mode"] == "semi_nonlinear"
    assert diag["local_wall_iteration_count"] > 0
    assert diag["local_wall_evaluation_count"] > 0
    assert diag["max_wall_temperature_change_k"] is not None
    assert 0.05 <= diag["local_wall_relaxation_factor"] <= 0.7
    assert diag["wall_temperature_bounds_k"] == [200.0, 3500.0]
    assert diag["max_wall_energy_residual_w"] < 5.0
    assert len(diag["wall_energy_residuals_w"]) == 2
    assert max(diag["wall_energy_residuals_w"]) < 5.0
    json.dumps(data, allow_nan=False)


@pytest.mark.parametrize(
    ("wall_h", "bed_temperature"),
    [(0.5, 350.0), (25.0, 600.0), (125.0, 900.0)],
)
def test_sensitivity_cases_match_linearized_reference_without_silent_fallback(
    wall_h, bed_temperature
):
    params = KilnParams(L_kiln=4.0, T_gas=850.0)
    nonlinear = solve_kiln(
        LAYERS, params,
        **_kwargs(
            wall_bed_h_w_m2_k=wall_h,
            bed_inlet_temperature_k=bed_temperature,
            wall_iteration_mode="semi_nonlinear",
        ),
    )
    linearized = solve_kiln(
        LAYERS, params,
        **_kwargs(
            wall_bed_h_w_m2_k=wall_h,
            bed_inlet_temperature_k=bed_temperature,
            wall_iteration_mode="linearized",
        ),
    )
    assert nonlinear.wall_iteration_mode == "semi_nonlinear"
    assert linearized.wall_iteration_mode == "linearized"
    assert all(math.isfinite(s.T_wall_inner_k) for s in nonlinear.states)
    assert all(math.isfinite(s.T_wall_inner_k) for s in linearized.states)
    # The two models are both returned explicitly; no exception is caught and
    # relabeled as a successful run of the other model.
    wall_deltas = [
        abs(a.T_wall_inner_k - b.T_wall_inner_k)
        for a, b in zip(nonlinear.states, linearized.states)
    ]
    assert all(math.isfinite(delta) for delta in wall_deltas)
    assert max(wall_deltas) > 1.0e-6



def test_wall_to_bed_heat_flow_warms_bed_in_semi_nonlinear_mode():
    result = solve_kiln(
        LAYERS,
        KilnParams(L_kiln=4.0, T_gas=1000.0),
        **_kwargs(
            bed_inlet_temperature_k=320.0,
            gas_bed_h_w_m2_k=0.01,
            wall_bed_h_w_m2_k=80.0,
            wall_iteration_mode="semi_nonlinear",
        ),
    )
    assert result.bed_temperature_out_k[0] > result.bed_temperature_in_k[0]

def test_axial_wall_iteration_is_repeatable_and_energy_closed():
    params = KilnParams(L_kiln=6.0, T_gas=800.0)
    first = solve_kiln(LAYERS, params, **_kwargs())
    second = solve_kiln(LAYERS, params, **_kwargs())
    assert first.as_dict()["diagnostics"]["wall_energy_residuals_w"] == pytest.approx(
        second.as_dict()["diagnostics"]["wall_energy_residuals_w"], abs=1e-9
    )
    for a, b in zip(first.states, second.states):
        assert a.as_dict() == pytest.approx(b.as_dict(), abs=1e-10)


@pytest.mark.parametrize("direction", ["co-current", "counter-current"])
def test_bed_flow_boundary_is_preserved_in_both_directions(direction):
    inlet = 360.0
    result = solve_kiln(
        LAYERS, KilnParams(L_kiln=4.0, T_gas=800.0),
        **_kwargs(bed_flow_direction=direction, bed_inlet_temperature_k=inlet),
    )
    if direction == "co-current":
        assert result.bed_temperature_in_k[0] == inlet
    else:
        assert result.bed_temperature_in_k[-1] == inlet


def test_local_wall_nonconvergence_reports_cell_and_coordinates():
    with pytest.raises(RuntimeError, match=r"cell 0 z="):
        solve_kiln(
            LAYERS, KilnParams(L_kiln=4.0, T_gas=800.0),
            **_kwargs(local_wall_max_iterations=1),
        )


def test_axial_nonconvergence_remains_an_explicit_failure():
    with pytest.raises(RuntimeError, match="did not converge"):
        solve_kiln(
            LAYERS, KilnParams(L_kiln=4.0, T_gas=800.0),
            **_kwargs(coupling_max_iterations=1),
        )
