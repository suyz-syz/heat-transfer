# Phase 2 architecture preview: convection and axial kiln model

Status: **architecture scaffold / unit-tested prototype**, not yet a validated industrial kiln solver.

## 1. Convection correlation strategy

The existing `inner_convection_h` and `solve_wall` path are deliberately unchanged. The new `kiln_ht.models.convection` module defines a small `ConvectionModel` protocol and a `ConvectionEvaluation` result with units, source, applicability, and warnings.

- `GnielinskiPipeModel` wraps the current internal-flow implementation and explicitly warns that pipe-flow correlations are not rotary-kiln-specific.
- `RotaryKilnCorrelationAdapter` accepts a caller-supplied, tested implementation. It does not fabricate a formula or claim that a paper's gas-to-bed, gas-to-wall, and bed-to-wall coefficients are interchangeable.
- Implemented first candidate: `TschengWatkinsonGasWall` and `TschengWatkinsonGasBed` in `kiln_ht/models/convection/tscheng_watkinson.py`. The published dimensionless regressions are `Nu_GW = 1.54 Re_F^0.575 Re_R^-0.292` and `Nu_GS = 0.46 Re_R^0.535 Re_F^0.104 f^-0.341`; `h = Nu k_g / D`. The gas-wall and gas-bed paths are separate. The implementation requires gas conductivity, kinematic viscosity, filling degree, and rotation rate explicitly. It enforces `Re_F=1600..7800`, `Re_R=20..800`, gas temperature 350..590 K, rotation 0..6 rpm, filling up to 0.17, and diameter within 25% of the reported 0.19 m pilot kiln. These bounds intentionally block extrapolation; they are not evidence that the correlation is validated outside the original experiment. The source is Tscheng & Watkinson (1979), DOI [10.1002/cjce.5450570405](https://doi.org/10.1002/cjce.5450570405). Li et al. (2005), DOI [10.1002/ceat.200500241](https://doi.org/10.1002/ceat.200500241), remains a candidate for wall-bed transfer; the public abstract does not expose enough of its complete equation and parameter definitions to implement it without the full paper.

Why not use Gnielinski blindly? It is a pipe/internal-flow correlation. A rotary kiln has rotation, possible solids holdup/bed coverage, gas-to-wall and gas-to-solid transfer paths, and potentially different local vs average coefficients. Tscheng & Watkinson measured axial gas, wall and solids temperatures in a specific non-fired pilot kiln and reported distinct gas-to-wall and gas-to-solids behavior. Their correlation must therefore be applied only to the matching transfer path and tested domain.

## 2. Axial data model and `solve_kiln`

`solve_kiln(layers, params, *, n_cells, mass_flow_kg_s, cp_gas_j_kg_k, inlet_gas_temperature_k=None)` partitions `params.L_kiln` into Z equal control volumes. In legacy two-phase mode it calls `solve_wall` at each cell's gas inlet temperature and updates the plug-flow gas temperature using:

`Q_cell = Qprime_wall * dz`

`T_gas,out = T_gas,in - Q_cell / (mass_flow * cp_gas)`

The result `KilnAxialSolution` exposes axial face coordinates, gas inlet/outlet/mean temperatures, per-cell `WallSolution` objects, per-cell heat transfer, total heat transfer, and JSON-compatible `as_dict()`.

### Three-phase state / coupling mode

Passing `bed_inlet_temperature_k` activates the additive three-phase path. It also requires bed mass flow and heat capacity, explicit gas-bed and wall-bed heat-transfer coefficients, and effective exchange areas per axial length. `bed_flow_direction` accepts `co-current` or `counter-current`. The returned `KilnState` records cell-centre z, gas/bed temperatures and inner/outer wall temperatures.

The implementation uses a conservative per-cell energy network: gas exchanges heat with bed and inner wall; the wall conducts radially and loses heat to ambient; the bed receives gas-bed and wall-bed heat. Each cell is solved using conductances linearized from the existing `solve_wall` result, and the counter-current boundary is iterated globally. The reported `max_energy_residual_w` checks gas and bed enthalpy balances. This is a coupled prototype, not yet a fully nonlinear radiation/solid-contact model. In three-phase mode, `states` are the authoritative coupled wall temperatures; `wall_solutions` retain the local baseline wall calculations used to derive conductances.

The gas-bed and wall-bed coefficients/areas are explicit inputs rather than guessed correlations. Do not use a single gas-wall correlation as a substitute for gas-bed transfer. Mesh convergence (Z, 2Z, 4Z) and comparison with published temperature-profile data remain required before industrial use.

### Current assumptions and limits

1. Steady state; one-dimensional plug-flow gas; constant user-supplied `cp_gas) and mass flow.
2. The wall in each axial cell is solved radially with `solve_wall`; `Qprime` is treated as the gas enthalpy loss per unit length. This is an engineering prototype coupling, not a simultaneous nonlinear finite-volume solution of gas convection plus wall radiation.
3. No axial solid conduction, gas pressure drop, species/reaction/evaporation enthalpy, gas/bed exchange, bed coverage, or counter-current solids energy balance.
4. The legacy two-phase `solve_wall` uses a one-way outward-loss boundary and therefore rejects cases where the predicted gas temperature reaches/breaches ambient. The coupled prototype also currently uses this baseline wall conductance and does not support a signed ambient-to-kiln heat flux.
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

`tests/test_phase2_architecture.py` checks axial discretization and gas-energy monotonicity, first-cell agreement with `solve_wall`, input validation, the Gnielinski scope warning, adapter validation, Tscheng-Watkinson formula fixtures and trends, domain guardrails, and three-phase energy balance in co-/counter-current modes. Formula fixtures validate implementation of the published equations; they are not independent experimental validation.
