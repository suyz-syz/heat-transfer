"""Pure data adapters for axial kiln and provisional WSGG visualizations.

These functions expose arrays already computed by the solver. They do not add
physics or infer material temperatures when the three-phase model is disabled.
"""
from __future__ import annotations

import math
from typing import Dict, List


def axial_plot_data(solution) -> Dict[str, List[float]]:
    """Convert a KilnAxialSolution into aligned axial plot arrays.

    Temperature arrays are returned in kelvin and radiative heat flux in W/m².
    The flux is reconstructed from the local wall solution's linearized h_rad
    and gas-to-inner-wall temperature difference, matching the wall model.
    """
    faces = list(solution.z_faces_m)
    gas = list(solution.gas_temperature_mean_k)
    walls = list(solution.wall_solutions)
    n = len(walls)
    if n < 1 or len(faces) != n + 1 or len(gas) != n:
        raise ValueError("轴向求解结果数组长度不一致")
    x = [(faces[i] + faces[i + 1]) / 2.0 for i in range(n)]
    inner = [float(w.T_w1) for w in walls]
    outer = [float(w.T_wN) for w in walls]
    q_rad = [float(w.h_rad_in) * (gas[i] - inner[i]) for i, w in enumerate(walls)]
    if not all(math.isfinite(v) for arr in (x, gas, inner, outer, q_rad) for v in arr):
        raise ValueError("轴向图表数据包含非有限数值")
    data = {
        "z_m": x,
        "gas_temperature_k": gas,
        "wall_inner_temperature_k": inner,
        "wall_outer_temperature_k": outer,
        "radiative_heat_flux_w_m2": q_rad,
    }
    states = list(getattr(solution, "states", []) or [])
    if states:
        if len(states) != n:
            raise ValueError("三相状态数组长度与轴向控制体数不一致")
        data["material_temperature_k"] = [float(s.T_bed_k) for s in states]
    return data


def provisional_wsgg_weight_curves(temperatures_k=None):
    """Return the current model's fixed provisional weights for plotting.

    The current WSGG implementation uses constant placeholder weights, not
    temperature-dependent HITEMP-fitted coefficients. Returning horizontal
    curves makes that limitation explicit rather than fabricating a_j(T).
    """
    from .models.radiation.wsgg import DEFAULT_WEIGHTS

    temps = list(temperatures_k or range(300, 2401, 50))
    if not temps or any(not math.isfinite(float(t)) or float(t) <= 0 for t in temps):
        raise ValueError("温度网格必须是非空的正有限 K 数组")
    return {
        "temperature_k": [float(t) for t in temps],
        "weights": {
            f"a_{i}": [float(weight)] * len(temps)
            for i, weight in enumerate(DEFAULT_WEIGHTS, start=1)
        },
    }
