# -*- coding: utf-8 -*-
"""核心计算单元测试：python -m pytest tests/ -v"""
import math
import pytest

from kiln_ht import (
    KilnParams,
    Layer,
    compute_temperature_curve,
    solve_wall,
)
from kiln_ht.calc import gas_emissivity, outer_natural_h


def default_params(**kwargs):
    p = KilnParams()
    for key, val in kwargs.items():
        setattr(p, key, val)
    return p


LAYERS = [
    Layer(name="硅酸铝纤维", thickness=0.150, k=0.10),
    Layer(name="轻质砖", thickness=0.100, k=0.30),
    Layer(name="高铝砖", thickness=0.080, k=1.50),
    Layer(name="钢壳", thickness=0.012, k=45.0),
]


def test_solve_energy_balance():
    p = default_params()
    sol = solve_wall(LAYERS, p)
    assert math.isfinite(sol.Qprime) and sol.Qprime > 0
    # 能量守恒自检：Q' = (T_g - T_a) / R_tot
    assert abs(sol.Qprime - (p.T_gas - p.T_env) / sol.R_tot) < 1e-6
    # 温度界内且有序
    assert p.T_env <= sol.T_wN <= sol.T_w1 <= p.T_gas
    assert sol.T_iface[0] == sol.T_w1
    assert sol.T_iface[-1] == sol.T_wN


def test_gas_emissivity_pressure_dependence():
    beam = 0.95 * 4.0
    eg_low = gas_emissivity(1523.15, 0.20, 0.08, beam, P_total=0.5)
    eg_high = gas_emissivity(1523.15, 0.20, 0.08, beam, P_total=5.0)
    # 总压升高 -> 分压增大 -> 发射率增大
    assert eg_high > eg_low
    assert 0.0 <= eg_low <= 1.0


def test_outer_natural_h_negative_delta_t():
    D = 2 * (2.0 + 0.30)
    # 外壁比环境冷（ΔT<0）：应返回有限正实数，而非复数
    h = outer_natural_h(323.15, 373.15, D)
    assert isinstance(h, float) and h > 0
    # 极低温差：返回底噪（有限正值）
    assert outer_natural_h(323.15, 323.15, D) > 0


def test_temperature_curve_monotonic():
    p = default_params(N_total=200)
    sol = solve_wall(LAYERS, p)
    x_mm, T_c = compute_temperature_curve(LAYERS, sol, n_points=p.N_total)
    assert len(x_mm) == len(T_c) == p.N_total
    assert x_mm[0] == 0.0 and x_mm[-1] > 0.0
    # 温度沿径向向外应单调下降
    for i in range(1, len(T_c)):
        assert T_c[i] <= T_c[i - 1] + 1e-9, f"温度不单调下降 at idx {i}: {T_c[i-1]} -> {T_c[i]}"


def test_validate_params():
    with pytest.raises(ValueError):
        solve_wall(LAYERS, default_params(v_gas=0.0))
    with pytest.raises(ValueError):
        solve_wall([], default_params())
    with pytest.raises(ValueError):
        solve_wall([Layer(name="x", thickness=-0.1, k=1.0)], default_params())


def test_layer_k_compat_auto_convert():
    """只提供 k 时自动转 k_coef=(k,0,0)。"""
    l = Layer(name="砖", thickness=0.05, k=0.10)
    assert l.k_coef == (0.10, 0.0, 0.0)
    assert l.k_const == 0.10


def test_layer_k_coef_direct():
    """显式提供 k_coef 时直接使用。"""
    l = Layer(name="纤维", thickness=0.05, k_coef=(0.08, 1.2e-4, 0.0))
    assert l.k_coef == (0.08, 1.2e-4, 0.0)
    assert l.k_const == 0.08


def test_layer_k_at():
    """k_at 计算 k(T)=a+bT+cT²。"""
    l = Layer(name="浇注料", thickness=0.1, k_coef=(1.2, 4.5e-4, -1.2e-7))
    assert abs(l.k_at(500.0) - (1.2 + 4.5e-4 * 500 - 1.2e-7 * 500 ** 2)) < 1e-9


def test_layer_rc_default():
    """Rc 默认 0，可指定。"""
    assert Layer().Rc == 0.0
    assert Layer(name="x", thickness=0.05, Rc=0.005).Rc == 0.005


def test_layer_k_and_k_coef_precedence():
    """同时提供 k 与 k_coef 时以 k_coef 为准。"""
    l = Layer(name="x", thickness=0.05, k=2.0, k_coef=(0.08, 1.2e-4, 0.0))
    assert l.k_coef == (0.08, 1.2e-4, 0.0)
