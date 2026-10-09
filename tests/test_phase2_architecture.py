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
