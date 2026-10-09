# Phase 2 architecture preview: convection and axial kiln model

Status: **architecture scaffold / unit-tested prototype**, not yet a validated industrial kiln solver.

## 1. Convection correlation strategy

The existing `inner_convection_h` and `solve_wall` path are deliberately unchanged. The new `kiln_ht.models.convection` module defines a small `ConvectionModel` protocol and a `ConvectionEvaluation` result with units, source, applicability, and warnings.

- `GnielinskiPipeModel` wraps the current internal-flow implementation and explicitly warns that pipe-flow correlations are not rotary-kiln-specific.
- `RotaryKilnCorrelationAdapter` accepts a caller-supplied, tested implementation. It does not fabricate a formula or claim that a paper's gas-to-bed, gas-to-wall, and bed-to-wall coefficients are interchangeable.
- Candidate references for later implementation include Tscheng & Watkinson (1979), DOI [10.1002/cjce.5450570405](https://doi.org/10.1002/cjce.5450570405), and Li et al. (2005), DOI [10.1002/ceat.200500241](https://doi.org/10.1002/ceat.200500241). Extract the exact equation, dimensionless groups, coefficient definition, and experimental range from the original paper before coding; store those details with the implementation and build regression tests from published example points.

Why not use Gnielinski blindly? It is a pipe/internal-flow correlation. A rotary kiln has rotation, possible solids holdup/bed coverage, gas-to-wall and gas-to-solid transfer paths, and potentially different local vs average coefficients. Tscheng & Watkinson measured axial gas, wall and solids temperatures in a specific non-fired pilot kiln and reported distinct gas-to-wall and gas-to-solids behavior. Their correlation must therefore be applied only to the matching transfer path and tested domain.

## 2. Axial data model and `solve_kiln`

`solve_kiln(layers, params, *, n_cells, mass_flow_kg_s, cp_gas_j_kg_k, inlet_gas_temperature_k=None)` partitions `params.L_kiln` into Z equal control volumes. It calls the existing `solve_wall` at each cell's gas inlet temperature and updates the plug-flow gas temperature using:

`Q_cell = Qprime_wall * dz`

`T_gas,out = T_gas,in - Q_cell / (mass_flow * cp_gas)`

The result `KilnAxialSolution` exposes axial face coordinates, gas inlet/outlet/mean temperatures, per-cell `WallSolution` objects, per-cell heat transfer, total heat transfer, and JSON-compatible `as_dict()`.

### Current assumptions and limits

1. Steady state; one-dimensional plug-flow gas; constant user-supplied `cp_gas) and mass flow.
2. The wall in each axial cell is solved radially with `solve_wall`; `Qprime` is treated as the gas enthalpy loss per unit length. This is an engineering prototype coupling, not a simultaneous nonlinear finite-volume solution of gas convection plus wall radiation.
3. No axial solid conduction, gas pressure drop, species/reaction/evaporation enthalpy, gas/bed exchange, bed coverage, or counter-current solids energy balance.
4. The current `solve_wall` uses a one-way outward-loss boundary and therefore rejects cases where the predicted gas temperature reaches/breaches ambient. Such cases require a more general signed heat-flux formulation.
5. The current local wall solve retains the original overall kiln length in its convection entrance correction; it does not treat each cell as a separate short pipe.

### Proposed next evolution

- Introduce typed per-cell boundary conditions and a `KilnState(z, T_gas, T_bed, T_wall_inner, T_wall_outer, composition, pressure)`.
- Add independently selected transfer paths: gas-wall convection, gas-wall radiation, gas-bed convection/radiation, bed-wall contact/penetration, wall radial conduction, and optional wall axial conduction.
- Form a conservative finite-volume residual for each gas, bed, inner-wall, outer-wall, and shell node; solve the coupled nonlinear system with bounded Newton/Picard iteration and energy-residual checks.
- Add mesh-refinement checks (Z, 2Z, 4Z), published benchmark cases, and uncertainty/range checks before promoting any correlation to production.

## 3. Compatibility contract

- `solve_wall(layers, params)` keeps its original signature and return type.
- The new API is additive: `solve_kiln` and `KilnAxialSolution`.
- Convection extensions are opt-in and do not silently replace the Phase 1A/1B correlation path.
- All new code uses the Python standard library only.

## 4. Tests

`tests/test_phase2_architecture.py` checks axial discretization and gas-energy monotonicity, first-cell agreement with `solve_wall`, input validation, the Gnielinski scope warning, and injected rotary-correlation callback validation. These tests establish software/API behavior, not experimental physical validation.
