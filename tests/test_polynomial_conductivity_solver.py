"""Regression coverage for temperature-dependent conductivity in the radial solver."""
import math

import pytest

from kiln_ht import (
    ConductivityModel,
    KilnParams,
    Layer,
    compute_temperature_curve,
    solve_wall,
)


def test_polynomial_conductivity_changes_outer_wall_temperature_and_gradient():
    """The UI's polynomial model must affect both solve_wall and its radial curve."""
    coefficients = (1.8, 0.0000016, -0.00000017)
    params = KilnParams(N_total=201)
    constant_layer = Layer(name="constant", thickness=0.10, k=coefficients[0])
    polynomial_layer = Layer(
        name="polynomial",
        thickness=0.10,
        k=coefficients[0],
        k_coef=coefficients,
        conductivity_model=ConductivityModel.polynomial(coefficients, "degC"),
    )

    constant_solution = solve_wall([constant_layer], params)
    polynomial_solution = solve_wall([polynomial_layer], params)

    assert polynomial_solution.k_avg[0] != pytest.approx(
        constant_solution.k_avg[0], rel=1e-6
    )
    assert abs(polynomial_solution.T_wN - constant_solution.T_wN) > 1e-4

    x_const, t_const = compute_temperature_curve(
        [constant_layer], constant_solution, n_points=params.N_total
    )
    x_poly, t_poly = compute_temperature_curve(
        [polynomial_layer], polynomial_solution, n_points=params.N_total
    )
    assert x_poly == pytest.approx(x_const)

    # Compare the local radial gradient around the middle of the lining.
    mid = params.N_total // 2
    dx_mm = x_const[mid + 1] - x_const[mid]
    gradient_const = (t_const[mid + 1] - t_const[mid]) / dx_mm
    gradient_poly = (t_poly[mid + 1] - t_poly[mid]) / dx_mm
    assert math.isfinite(gradient_poly)
    assert abs(gradient_poly - gradient_const) > 1e-6
