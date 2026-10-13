"""P2 bed geometry helper and solver integration regressions."""
import json
import math
from dataclasses import replace

import pytest

from kiln_ht import (
    KilnParams, Layer, calculate_bed_geometry, filling_angle_from_fraction,
    filling_fraction_from_angle, resolve_bed_geometry, solve_kiln,
)
from kiln_ht.calc import solve_wall


LAYERS = [
    Layer(name="fiber", thickness=0.15, k=0.10),
    Layer(name="brick", thickness=0.08, k=1.2),
    Layer(name="steel", thickness=0.012, k=45.0),
]


def bed_kwargs(**overrides):
    values = {
        "n_cells": 2, "mass_flow_kg_s": 10.0, "cp_gas_j_kg_k": 1150.0,
        "bed_inlet_temperature_k": 350.0, "bed_mass_flow_kg_s": 2.0,
        "cp_bed_j_kg_k": 1000.0, "gas_bed_h_w_m2_k": 20.0,
        "wall_bed_h_w_m2_k": 50.0,
    }
    values.update(overrides)
    return values


@pytest.mark.parametrize("fraction", [0.0, 0.001, 0.1, 0.5, 0.9, 0.999, 1.0])
def test_fill_fraction_angle_round_trip_and_geometry_endpoints(fraction):
    beta = filling_angle_from_fraction(fraction)
    assert filling_fraction_from_angle(beta) == pytest.approx(fraction, abs=2.0e-13)
    g = calculate_bed_geometry(4.0, filling_fraction=fraction)
    assert g["filling_fraction"] == pytest.approx(fraction)
    if fraction == 0.0:
        assert g["wall_bed_contact_per_length_m_computed"] == 0.0
        assert g["gas_bed_area_per_length_m_computed"] == 0.0
    elif fraction == 1.0:
        assert g["wall_bed_contact_per_length_m_computed"] == pytest.approx(4.0 * math.pi)
        assert g["gas_bed_area_per_length_m_computed"] == 0.0
    else:
        assert g["wall_bed_contact_per_length_m_computed"] > 0.0
        assert g["gas_bed_area_per_length_m_computed"] > 0.0


def test_half_fill_uses_semicircle_and_expected_arc_and_chord():
    g = calculate_bed_geometry(4.0, filling_fraction=0.5)
    assert g["filling_angle_deg"] == pytest.approx(180.0)
    assert g["wall_bed_contact_per_length_m_computed"] == pytest.approx(2.0 * math.pi)
    assert g["gas_bed_area_per_length_m_computed"] == pytest.approx(4.0)


@pytest.mark.parametrize("kwargs", [
    {"filling_fraction": -0.1}, {"filling_fraction": 1.1},
    {"filling_angle_deg": -1}, {"filling_angle_deg": 361},
])
def test_geometry_rejects_out_of_domain_values(kwargs):
    with pytest.raises(ValueError):
        calculate_bed_geometry(4.0, **kwargs)


def test_geometry_requires_exactly_one_input_and_positive_diameter():
    with pytest.raises(ValueError):
        calculate_bed_geometry(4.0)
    with pytest.raises(ValueError):
        calculate_bed_geometry(4.0, filling_fraction=0.4, filling_angle_deg=120)
    with pytest.raises(ValueError):
        calculate_bed_geometry(0.0, filling_fraction=0.4)


def test_manual_area_overrides_are_independent_and_reported():
    gas, wall, metadata = resolve_bed_geometry(
        {"enabled": True, "input_mode": "filling_fraction", "filling_fraction": 0.25},
        4.0, gas_bed_area_per_length_m=8.0,
    )
    assert gas == 8.0
    assert wall == metadata["wall_bed_contact_per_length_m_computed"]
    assert metadata["gas_bed_area_source"] == "manual_override"
    assert metadata["wall_bed_area_source"] == "geometry"


def test_filling_angle_input_and_disabled_legacy_path():
    _, _, angle_meta = resolve_bed_geometry(
        {"enabled": True, "input_mode": "filling_angle", "filling_angle_deg": 180.0}, 4.0
    )
    assert angle_meta["filling_fraction"] == pytest.approx(0.5)
    gas, wall, disabled = resolve_bed_geometry(None, 4.0, gas_bed_area_per_length_m=1.4)
    assert (gas, wall) == (1.4, None)
    assert disabled["enabled"] is False
    assert disabled["gas_bed_area_source"] == "manual"


def test_empty_bed_geometry_recovers_radial_wall_baseline_and_serializes():
    params = KilnParams(L_kiln=4.0, T_gas=850.0)
    result = solve_kiln(
        LAYERS, params,
        bed_geometry={"enabled": True, "input_mode": "filling_fraction", "filling_fraction": 0.0},
        **bed_kwargs(),
    )
    assert result.bed_geometry["filling_fraction"] == 0.0
    assert result.bed_geometry["gas_bed_area_per_length_m_effective"] == 0.0
    for state in result.states:
        baseline = solve_wall(LAYERS, replace(params, T_gas=state.T_gas_k))
        assert state.T_wall_inner_k == pytest.approx(baseline.T_w1, abs=2.0e-3)
        assert state.T_wall_outer_k == pytest.approx(baseline.T_wN, abs=2.0e-3)
    json.dumps(result.as_dict(), allow_nan=False)


def test_full_fill_rejected_for_three_phase_plug_flow():
    with pytest.raises(ValueError, match="no gas passage"):
        solve_kiln(
            LAYERS, KilnParams(L_kiln=4.0, T_gas=850.0),
            bed_geometry={"enabled": True, "input_mode": "filling_fraction", "filling_fraction": 1.0},
            **bed_kwargs(),
        )


def test_manual_overrides_win_inside_solver_metadata():
    result = solve_kiln(
        LAYERS, KilnParams(L_kiln=4.0, T_gas=850.0),
        bed_geometry={"enabled": True, "input_mode": "filling_fraction", "filling_fraction": 0.5},
        gas_bed_area_per_length_m=0.75,
        wall_bed_contact_per_length_m=0.33,
        **bed_kwargs(),
    )
    data = result.as_dict()
    assert data["bed_geometry"]["gas_bed_area_per_length_m_effective"] == 0.75
    assert data["bed_geometry"]["wall_bed_contact_per_length_m_effective"] == 0.33
    assert data["bed_geometry"]["gas_bed_area_source"] == "manual_override"
    assert data["bed_geometry"]["wall_bed_area_source"] == "manual_override"
    json.dumps(data, allow_nan=False)


def test_api_response_and_visualization_keep_geometry_metadata_serializable():
    from kiln_ht.visualization import axial_plot_data
    from server import AxialSolveRequest, axial_solve

    request = AxialSolveRequest(
        layers=[{"name": "brick", "thickness": 0.1, "k": 1.2}],
        params={"T_gas": 850.0, "L_kiln": 2.0, "L_char": 2.0},
        n_cells=1, mass_flow_kg_s=20.0,
        bed_inlet_temperature_k=350.0, bed_mass_flow_kg_s=2.0,
        cp_bed_j_kg_k=1000.0, gas_bed_h_w_m2_k=20.0,
        wall_bed_h_w_m2_k=50.0,
        bed_geometry={"enabled": True, "input_mode": "filling_angle", "filling_angle_deg": 120.0},
    )
    api_result = axial_solve(request)
    meta = api_result["bed_geometry"]
    assert meta["source"] == "filling_angle_deg"
    assert meta["filling_angle_deg"] == pytest.approx(120.0)
    assert meta["gas_bed_area_source"] == "geometry"
    json.dumps(api_result, allow_nan=False)

    solution = solve_kiln(
        LAYERS, KilnParams(L_kiln=2.0, T_gas=850.0),
        bed_geometry={"enabled": True, "input_mode": "filling_fraction", "filling_fraction": 0.3},
        **bed_kwargs(n_cells=1),
    )
    plotted = axial_plot_data(solution)
    assert plotted["bed_geometry"] == solution.as_dict()["bed_geometry"]
    json.dumps(plotted, allow_nan=False)

    from kiln_ht.calc import solve_wall
    from kiln_ht.export import build_report
    params = KilnParams(L_kiln=2.0, T_gas=850.0)
    report = build_report(LAYERS, params, solve_wall(LAYERS, params), axial_data=plotted)
    assert "【床层几何】" in report
    assert "assumptions" in report
    assert "filling_fraction" in report


def test_schema_config_preserves_and_validates_bed_geometry():
    from kiln_ht.config_schema import normalize_config

    config = normalize_config({
        "layers": [{"name": "brick", "thickness_m": 0.1, "k": 1.2}],
        "bed_geometry": {
            "enabled": True, "input_mode": "filling_fraction",
            "filling_fraction": 0.3, "gas_bed_area_per_length_m": 0.7,
        },
    })
    assert config["bed_geometry"]["filling_fraction"] == pytest.approx(0.3)
    assert config["bed_geometry"]["gas_bed_area_per_length_m"] == pytest.approx(0.7)
    with pytest.raises(ValueError):
        normalize_config({
            "layers": [],
            "bed_geometry": {"enabled": True, "input_mode": "filling_fraction", "filling_fraction": 1.2},
        })
