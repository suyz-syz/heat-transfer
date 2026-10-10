import pytest

from kiln_ht import KilnParams, Layer, solve_kiln
from kiln_ht.visualization import axial_plot_data, provisional_wsgg_weight_curves


LAYERS = [
    Layer(name="fiber", thickness=0.15, k=0.10),
    Layer(name="brick", thickness=0.08, k=1.2),
    Layer(name="steel", thickness=0.012, k=45.0),
]


def test_axial_plot_data_uses_solver_arrays_and_radiative_flux():
    result = solve_kiln(
        LAYERS, KilnParams(L_kiln=20.0, T_gas=1200.0),
        n_cells=4, mass_flow_kg_s=20.0, cp_gas_j_kg_k=1150.0,
    )
    data = axial_plot_data(result)
    assert len(data["z_m"]) == 4
    assert data["z_m"] == pytest.approx([2.5, 7.5, 12.5, 17.5])
    assert data["gas_temperature_k"] == pytest.approx(result.gas_temperature_mean_k)
    assert data["wall_inner_temperature_k"] == pytest.approx(
        [w.T_w1 for w in result.wall_solutions]
    )
    assert data["radiative_heat_flux_w_m2"] == pytest.approx([
        w.h_rad_in * (result.gas_temperature_mean_k[i] - w.T_w1)
        for i, w in enumerate(result.wall_solutions)
    ])
    assert "material_temperature_k" not in data


def test_axial_plot_data_includes_material_only_for_three_phase_solution():
    result = solve_kiln(
        LAYERS, KilnParams(L_kiln=6.0, T_gas=800.0),
        n_cells=3, mass_flow_kg_s=10.0, cp_gas_j_kg_k=1150.0,
        bed_inlet_temperature_k=350.0, bed_mass_flow_kg_s=2.0,
        cp_bed_j_kg_k=1000.0, gas_bed_h_w_m2_k=20.0,
        wall_bed_h_w_m2_k=50.0, gas_bed_area_per_length_m=1.0,
        wall_bed_contact_per_length_m=0.2,
    )
    data = axial_plot_data(result)
    assert len(data["material_temperature_k"]) == 3
    assert data["material_temperature_k"] == pytest.approx(
        [state.T_bed_k for state in result.states]
    )


def test_wsgg_plot_labels_current_fixed_weights_without_fabricating_temperature_dependence():
    data = provisional_wsgg_weight_curves([500, 1000, 1500])
    assert data["temperature_k"] == [500.0, 1000.0, 1500.0]
    assert list(data["weights"]) == ["a_1", "a_2", "a_3", "a_4"]
    assert all(len(values) == 3 for values in data["weights"].values())
    assert all(values[0] == values[1] == values[2] for values in data["weights"].values())
