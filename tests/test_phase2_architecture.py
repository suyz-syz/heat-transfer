import math

import pytest

from kiln_ht import (
    ConvectionEvaluation,
    GnielinskiPipeModel,
    KilnParams,
    Layer,
    RotaryKilnCorrelationAdapter,
    solve_kiln,
    solve_wall,
)


LAYERS = [
    Layer(name="fiber", thickness=0.15, k=0.10),
    Layer(name="brick", thickness=0.08, k=1.2),
    Layer(name="steel", thickness=0.012, k=45.0),
]


def test_solve_kiln_builds_axial_cells_and_cools_gas():
    params = KilnParams(L_kiln=20.0, T_gas=1200.0, T_env=298.15)
    result = solve_kiln(
        LAYERS, params, n_cells=4, mass_flow_kg_s=20.0,
        cp_gas_j_kg_k=1150.0,
    )
    assert len(result.z_faces_m) == 5
    assert result.z_faces_m == pytest.approx([0.0, 5.0, 10.0, 15.0, 20.0])
    assert len(result.wall_solutions) == 4
    assert len(result.heat_transfer_w) == 4
    assert result.gas_temperature_in_k[0] == pytest.approx(params.T_gas)
    assert all(a > b for a, b in zip(
        result.gas_temperature_in_k, result.gas_temperature_out_k
    ))
    assert all(result.gas_temperature_out_k[i] == pytest.approx(
        result.gas_temperature_in_k[i + 1]
    ) for i in range(3))
    assert all(result.gas_temperature_out_k[i] > params.T_env for i in range(4))
    assert result.total_heat_transfer_w == pytest.approx(sum(result.heat_transfer_w))
    assert result.as_dict()["model_scope"].startswith("steady 1-D plug-flow")


def test_solve_wall_api_and_result_remain_compatible():
    params = KilnParams(L_kiln=20.0, T_gas=1200.0)
    legacy = solve_wall(LAYERS, params)
    axial_first = solve_kiln(
        LAYERS, params, n_cells=2, mass_flow_kg_s=100.0
    ).wall_solutions[0]
    # The first cell uses the original inlet gas temperature and the same params.
    assert axial_first.Qprime == pytest.approx(legacy.Qprime, rel=1e-9)
    assert axial_first.T_w1 == pytest.approx(legacy.T_w1, rel=1e-9)


@pytest.mark.parametrize("kwargs", [
    {"n_cells": 0},
    {"mass_flow_kg_s": 0.0},
    {"cp_gas_j_kg_k": -1.0},
    {"inlet_gas_temperature_k": 0.0},
])
def test_solve_kiln_rejects_invalid_axial_inputs(kwargs):
    with pytest.raises(ValueError):
        solve_kiln(LAYERS, KilnParams(), **kwargs)


def test_gnielinski_wrapper_reports_pipe_flow_limitation():
    result = GnielinskiPipeModel().evaluate(
        bulk_temperature_k=1000.0,
        wall_temperature_k=800.0,
        velocity_m_s=3.0,
        characteristic_diameter_m=4.0,
        length_m=60.0,
        pressure_pa=101325.0,
    )
    assert isinstance(result, ConvectionEvaluation)
    assert math.isfinite(result.h_w_m2_k) and result.h_w_m2_k > 0.0
    assert "rotary-kiln-specific" in result.warnings[0]


def test_rotary_kiln_adapter_is_injectable_and_validates_h():
    seen = {}

    def evaluator(**kwargs):
        seen.update(kwargs)
        return 42.0

    model = RotaryKilnCorrelationAdapter(
        model_name="example-adapter",
        source="test-only synthetic callback (not a physical correlation)",
        applicability="unit test only",
        evaluator=evaluator,
    )
    result = model.evaluate(
        bulk_temperature_k=1200.0,
        wall_temperature_k=900.0,
        velocity_m_s=2.0,
        characteristic_diameter_m=3.0,
        length_m=30.0,
        pressure_pa=101325.0,
        rotation_rpm=1.5,
    )
    assert result.h_w_m2_k == pytest.approx(42.0)
    assert seen["rotation_rpm"] == pytest.approx(1.5)

    invalid = RotaryKilnCorrelationAdapter(
        model_name="bad", source="test", applicability="test",
        evaluator=lambda **kwargs: float("nan"),
    )
    with pytest.raises(ValueError):
        invalid.evaluate(
            bulk_temperature_k=1200.0, wall_temperature_k=900.0,
            velocity_m_s=2.0, characteristic_diameter_m=3.0,
            length_m=30.0, pressure_pa=101325.0,
        )



def test_rotary_adapter_requires_source_and_applicability_metadata():
    model = RotaryKilnCorrelationAdapter(
        model_name="unreferenced",
        source="",
        applicability="",
        evaluator=lambda **kwargs: 10.0,
    )
    with pytest.raises(ValueError):
        model.evaluate(
            bulk_temperature_k=1000.0,
            wall_temperature_k=800.0,
            velocity_m_s=2.0,
            characteristic_diameter_m=3.0,
            length_m=20.0,
            pressure_pa=101325.0,
        )


def _tw_inputs():
    return dict(
        bulk_temperature_k=450.0,
        wall_temperature_k=420.0,
        velocity_m_s=0.4,
        characteristic_diameter_m=0.19,
        length_m=2.5,
        pressure_pa=101325.0,
        properties={
            "thermal_conductivity_w_m_k": 0.035,
            "kinematic_viscosity_m2_s": 1.5e-5,
            "filling_degree": 0.10,
        },
        rotation_rpm=2.0,
    )


def test_tscheng_watkinson_published_correlations_reproduce_dimensionless_forms():
    from kiln_ht import TschengWatkinsonGasBed, TschengWatkinsonGasWall

    wall = TschengWatkinsonGasWall().evaluate(**_tw_inputs())
    bed = TschengWatkinsonGasBed().evaluate(**_tw_inputs())
    # Formula regression fixture based on the published dimensionless equations,
    # not a claim that this synthetic input is a measured experimental point.
    assert wall.h_w_m2_k == pytest.approx(6.22197, rel=2e-5)
    assert bed.h_w_m2_k == pytest.approx(12.59468, rel=2e-5)
    assert wall.model_name.endswith("gas-wall")
    assert bed.model_name.endswith("gas-bed")
    assert "Re_F=1600-7800" in wall.applicability
    assert "not a cement-kiln validation" in wall.warnings[0]


def test_tscheng_watkinson_trends_and_domain_guardrails():
    from kiln_ht import TschengWatkinsonGasBed, TschengWatkinsonGasWall

    base = _tw_inputs()
    wall_model = TschengWatkinsonGasWall()
    bed_model = TschengWatkinsonGasBed()
    wall_base = wall_model.evaluate(**base).h_w_m2_k
    faster = dict(base, velocity_m_s=0.45)
    assert wall_model.evaluate(**faster).h_w_m2_k > wall_base
    slower_rotation = dict(base, rotation_rpm=1.0)
    assert wall_model.evaluate(**slower_rotation).h_w_m2_k > wall_base
    lower_fill = dict(base, properties=dict(base["properties"], filling_degree=0.05))
    assert bed_model.evaluate(**lower_fill).h_w_m2_k > bed_model.evaluate(**base).h_w_m2_k
    with pytest.raises(ValueError, match="350-590 K"):
        wall_model.evaluate(**dict(base, bulk_temperature_k=700.0))
    with pytest.raises(ValueError, match="Re_F"):
        wall_model.evaluate(**dict(base, velocity_m_s=0.05))


@pytest.mark.parametrize("direction", ["co-current", "counter-current"])
def test_solve_kiln_three_phase_conserves_energy_and_populates_state(direction):
    params = KilnParams(L_kiln=6.0, T_gas=800.0, T_env=298.15)
    result = solve_kiln(
        LAYERS, params, n_cells=3, mass_flow_kg_s=10.0,
        cp_gas_j_kg_k=1150.0, bed_inlet_temperature_k=350.0,
        bed_mass_flow_kg_s=2.0, cp_bed_j_kg_k=1000.0,
        gas_bed_h_w_m2_k=20.0, wall_bed_h_w_m2_k=50.0,
        gas_bed_area_per_length_m=1.0,
        wall_bed_contact_per_length_m=0.2,
        bed_flow_direction=direction,
    )
    assert len(result.states) == 3
    assert result.bed_flow_direction == direction
    assert result.coupling_iterations > 0
    assert result.max_energy_residual_w < 5.0
    assert all(s.T_wall_inner_k > s.T_wall_outer_k for s in result.states)
    assert all(s.T_gas_k > 0 and s.T_bed_k > 0 for s in result.states)
    assert result.as_dict()["states"][0]["z_m"] == pytest.approx(1.0)


def test_solve_kiln_three_phase_requires_complete_boundary_data():
    with pytest.raises(ValueError, match="three-phase mode requires"):
        solve_kiln(
            LAYERS, KilnParams(), bed_inlet_temperature_k=350.0,
        )


def test_solve_kiln_three_phase_rejects_unknown_bed_flow_direction():
    with pytest.raises(ValueError, match="bed_flow_direction"):
        solve_kiln(
            LAYERS, KilnParams(), bed_inlet_temperature_k=350.0,
            bed_mass_flow_kg_s=2.0, cp_bed_j_kg_k=1000.0,
            gas_bed_h_w_m2_k=20.0, wall_bed_h_w_m2_k=50.0,
            gas_bed_area_per_length_m=1.0,
            wall_bed_contact_per_length_m=0.2,
            bed_flow_direction="cross-current",
        )
