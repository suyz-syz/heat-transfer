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


# ============ integral_mean_k ============
def test_integral_mean_k_constant():
    """常数 k 时积分平均 = k。"""
    from kiln_ht.calc import integral_mean_k
    assert integral_mean_k((1.0, 0.0, 0.0), 100.0, 900.0) == pytest.approx(1.0)


def test_integral_mean_k_linear_matches_analytic():
    """k=a+bT 时积分平均 = a + b*(Th+Tc)/2。"""
    from kiln_ht.calc import integral_mean_k
    a, b = 1.2, 4.5e-4
    Th, Tc = 900.0, 500.0
    k_avg = integral_mean_k((a, b, 0.0), Th, Tc)
    assert k_avg == pytest.approx(a + b * (Th + Tc) / 2.0, rel=1e-9)


def test_integral_mean_k_quadratic():
    """k=a+bT+cT² 积分平均 = a + b*Tmid + c*(Th²+Th*Tc+Tc²)/3。"""
    from kiln_ht.calc import integral_mean_k
    a, b, c = 1.2, 4.5e-4, -1.2e-7
    Th, Tc = 900.0, 500.0
    k_avg = integral_mean_k((a, b, c), Th, Tc)
    expect = a + b * (Th + Tc) / 2 + c * (Th**2 + Th * Tc + Tc**2) / 3.0
    assert k_avg == pytest.approx(expect, rel=1e-9)


def test_integral_mean_k_equal_temps():
    """Th≈Tc 时退化为 k(T)。"""
    from kiln_ht.calc import integral_mean_k
    k_avg = integral_mean_k((1.2, 4.5e-4, -1.2e-7), 700.0, 700.0)
    assert k_avg == pytest.approx(1.2 + 4.5e-4 * 700 - 1.2e-7 * 700**2, rel=1e-9)


# ============ solve_wall k(T) / Rc 升级 ============
def test_solve_wall_k_coef_constant_equals_k():
    """k_coef=(k,0,0) 与旧 k 行为等价（能量守恒、温度界内）。"""
    layers_old = [Layer(name="硅酸铝纤维", thickness=0.150, k=0.10),
                  Layer(name="轻质砖", thickness=0.100, k=0.30),
                  Layer(name="高铝砖", thickness=0.080, k=1.50),
                  Layer(name="钢壳", thickness=0.012, k=45.0)]
    layers_new = [Layer(name="硅酸铝纤维", thickness=0.150, k_coef=(0.10, 0.0, 0.0)),
                  Layer(name="轻质砖", thickness=0.100, k_coef=(0.30, 0.0, 0.0)),
                  Layer(name="高铝砖", thickness=0.080, k_coef=(1.50, 0.0, 0.0)),
                  Layer(name="钢壳", thickness=0.012, k_coef=(45.0, 0.0, 0.0))]
    p = default_params()
    sol_old = solve_wall(layers_old, p)
    sol_new = solve_wall(layers_new, p)
    assert sol_old.Qprime == pytest.approx(sol_new.Qprime, rel=1e-9)
    assert sol_old.T_w1 == pytest.approx(sol_new.T_w1, rel=1e-9)
    assert sol_old.T_wN == pytest.approx(sol_new.T_wN, rel=1e-9)


def test_solve_wall_k_coef_changes_result():
    """k(T) 与常数 k（取常温值）应产生不同结果（温度相关更接近物理）。"""
    # 单层纤维：k=0.08 vs k(T)=0.08+1.2e-4T，高温下 k 更大 -> 热阻更小 -> Q' 更大
    layers_const = [Layer(name="纤维", thickness=0.15, k=0.08)]
    layers_temp = [Layer(name="纤维", thickness=0.15, k_coef=(0.08, 1.2e-4, 0.0))]
    p = default_params()
    sol_c = solve_wall(layers_const, p)
    sol_t = solve_wall(layers_temp, p)
    assert sol_t.Qprime != pytest.approx(sol_c.Qprime, rel=1e-9)
    # 高温段 k(T)>k_const，热阻更小，热流更大（或至少物理上有限且内壁更贴近烟气）
    assert math.isfinite(sol_t.Qprime) and sol_t.Qprime > 0
    assert p.T_env <= sol_t.T_wN <= sol_t.T_w1 <= p.T_gas


def test_solve_wall_rc_reduces_heat():
    """接触热阻 Rc>0 增大总热阻，Q' 减小，界面温差增大。"""
    layers_plain = [Layer(name="纤维", thickness=0.150, k=0.10),
                    Layer(name="钢壳", thickness=0.012, k=45.0)]
    layers_rc = [Layer(name="纤维", thickness=0.150, k=0.10, Rc=0.01),
                 Layer(name="钢壳", thickness=0.012, k=45.0)]
    p = default_params()
    sol_plain = solve_wall(layers_plain, p)
    sol_rc = solve_wall(layers_rc, p)
    assert sol_rc.Qprime < sol_plain.Qprime
    assert sol_rc.R_tot > sol_plain.R_tot


def test_solve_wall_rc_default_no_change():
    """Rc=0（默认）结果与无 Rc 字段完全一致。"""
    l1 = [Layer(name="纤维", thickness=0.150, k=0.10),
          Layer(name="钢壳", thickness=0.012, k=45.0)]
    l2 = [Layer(name="纤维", thickness=0.150, k=0.10, Rc=0.0),
          Layer(name="钢壳", thickness=0.012, k=45.0)]
    p = default_params()
    assert solve_wall(l1, p).Qprime == pytest.approx(solve_wall(l2, p).Qprime, rel=1e-9)


def test_solve_wall_k_avg_reported():
    """结果含各层平均导热系数 k_avg。"""
    layers = [Layer(name="硅酸铝纤维", thickness=0.150, k_coef=(0.08, 1.2e-4, 0.0)),
              Layer(name="钢壳", thickness=0.012, k_coef=(45.0, 0.0, 0.0))]
    p = default_params()
    sol = solve_wall(layers, p)
    assert len(sol.k_avg) == 2
    assert all(math.isfinite(v) and v > 0 for v in sol.k_avg)


def test_solve_wall_thick_fiber_converges_with_kt():
    """k(T) 下厚纤维单层仍收敛且内壁贴近烟气。"""
    layers = [Layer(name="厚硅酸铝纤维", thickness=0.50, k_coef=(0.08, 1.2e-4, 0.0))]
    p = default_params()
    sol = solve_wall(layers, p)
    assert math.isfinite(sol.Qprime) and sol.Qprime > 0
    assert abs(sol.T_w1 - p.T_gas) < 60


# ============ compute_temperature_curve k_avg 一致性 ============
def test_temperature_curve_uses_k_avg():
    """温度曲线应使用 k_avg（k(T) 积分平均），与 solve_wall 一致。"""
    from kiln_ht import compute_temperature_curve
    layers = [Layer(name="纤维", thickness=0.150, k_coef=(0.08, 1.2e-4, 0.0)),
              Layer(name="钢壳", thickness=0.012, k_coef=(45.0, 0.0, 0.0))]
    p = default_params(N_total=200)
    sol = solve_wall(layers, p)
    x_mm, T_c = compute_temperature_curve(layers, sol, n_points=p.N_total)
    assert len(x_mm) == len(T_c) == p.N_total
    # 首点=内壁、末点=外壁
    assert abs(T_c[0] - (sol.T_w1 - 273.15)) < 1.0
    assert abs(T_c[-1] - (sol.T_wN - 273.15)) < 1.0
    # 单调下降
    for i in range(1, len(T_c)):
        assert T_c[i] <= T_c[i - 1] + 1e-9
