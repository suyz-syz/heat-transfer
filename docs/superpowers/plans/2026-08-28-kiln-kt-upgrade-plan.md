# 水泥窑窑衬传热核心升级实施计划（k(T) + 接触热阻 + 材料库）

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将 calc.py 的核心从常数 k 升级为 k(T) 温度相关导热系数 + 层间接触热阻 Rc + 内置耐火材料库，同时保留向后兼容性。

**Architecture:** 渐进式演进（方案 A）：先改核心数据结构和算法（calc.py + materials.py），再适配三个 GUI 入口（FastAPI / Streamlit / Kivy），最后归档遗留脚本。全程 TDD，每个任务有独立可交付、可测试的成果。

**Tech Stack:** Python 标准库（零第三方依赖计算核心）、dataclass、pytest

**Spec:** `docs/superpowers/specs/2026-08-28-kiln-kt-upgrade-design.md`

## Global Constraints

- 计算核心 `kiln_ht/calc.py` 必须保持**零第三方依赖**（仅 Python 标准库 math），维持 Android 交叉编译的可行性。
- `Layer` 必须**保留 `k` 字段兼容输入**：若调用方只提供 `k`（`k_coef` 为默认值且被显式跳过），自动转为 `k_coef=(k, 0.0, 0.0)`。
- `k_coef` 为 `(a, b, c)` 三元组，`k(T) = a + b·T + c·T²`，**T 单位 ℃**。
- 层间接触热阻 `Rc` 单位 **m²·K/W**，默认 0（无接触热阻）。
- 材料库系数来自耐火材料手册/国标工程数据（见 spec 2.5 表）。
- 每个任务必须有对应测试（pytest），全部通过才提交。
- 目录结构：主项目 `cement-kiln-heat-transfer/`；工作目录约定 `cd cement-kiln-heat-transfer`。

---

### Task 1: Layer 数据类升级（k_coef + Rc + k 兼容）

**Files:**
- Modify: `kiln_ht/calc.py`（Layer dataclass）
- Test: `tests/test_calc.py`

**Interfaces:**
- Consumes: 无（这是第一项核心改动）
- Produces:
  - `Layer(name, thickness, k_coef, Rc)` —— 全部带默认值
  - `Layer.k_const` property → float（返回 `k_coef[0]`，兼容常数 k）
  - `Layer.k_at(T_c: float)` → float（返回 `a + b·T + c·T²`）
  - `Layer.k` 字段保留；`__post_init__` 实现兼容转换

- [ ] **Step 1: 写失败测试**（在 `tests/test_calc.py` 追加）

```python
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
```

- [ ] **Step 2: 运行测试确认失败**

Run: `python -m pytest tests/test_calc.py -k "layer_" -v`
Expected: FAIL —— `Layer` 还没有 `k_coef`/`Rc` 字段，TypeError/AttributeError。

- [ ] **Step 3: 实现 Layer 升级**

在 `kiln_ht/calc.py` 中，`Layer` 改为：

```python
from typing import Dict, List, Optional, Tuple

@dataclass(frozen=True)
class Layer:
    """单层衬里结构参数。

    thickness 单位为米 (m)；k 为导热系数 (W/m·K)，兼容旧字段；
    k_coef 为 (a, b, c) 三元组，k(T)=a+b·T+c·T²（T 单位 ℃）；
    Rc 为层间接触热阻 (m²·K/W)，0 表示无。
    """

    name: str = "层"
    thickness: float = 0.05
    k: float = 1.0          # 兼容字段：仅提供 k 时自动转 k_coef=(k,0,0)
    k_coef: Optional[Tuple[float, float, float]] = None
    Rc: float = 0.0         # 层间接触热阻 m²·K/W

    def __post_init__(self) -> None:
        if self.k_coef is None:
            object.__setattr__(self, "k_coef", (self.k, 0.0, 0.0))

    @property
    def thickness_mm(self) -> float:
        return self.thickness * 1000.0

    @property
    def k_const(self) -> float:
        """常数 k 兼容：返回 k_coef 的常数项 a。"""
        return self.k_coef[0]

    def k_at(self, T_c: float) -> float:
        """温度 T(℃) 下的导热系数 W/(m·K)。"""
        a, b, c = self.k_coef
        return a + b * T_c + c * T_c * T_c
```

> 注意：`Layer` 是 `frozen=True`，`__post_init__` 里必须用 `object.__setattr__` 才能给 `k_coef` 赋值。若同时提供 `k` 与 `k_coef`，`k_coef` 非 None 故兼容转换跳过（以 k_coef 为准）。

- [ ] **Step 4: 运行测试确认通过**

Run: `python -m pytest tests/test_calc.py -k "layer_" -v`
Expected: PASS（全部通过）

- [ ] **Step 5: 提交**

```bash
git add kiln_ht/calc.py tests/test_calc.py
git commit -m "feat(kiln_ht): Layer 升级 k_coef + Rc，保留 k 兼容"
```

---

### Task 2: 温度相关导热系数积分平均 + solve_wall 升级

**Files:**
- Modify: `kiln_ht/calc.py`（新增 `integral_mean_k`、改写 `solve_wall`、`WallSolution` 增 `k_avg` 字段）
- Modify: `kiln_ht/__init__.py`（导出 `integral_mean_k`）
- Test: `tests/test_calc.py`

**Interfaces:**
- Consumes: Task 1 的 `Layer.k_coef` / `Layer.k_at` / `Layer.Rc`
- Produces:
  - `integral_mean_k(k_coef, T_h_c, T_c_c) -> float` —— 层内积分平均导热系数（T 单位 ℃）
  - `solve_wall(layers, params) -> WallSolution` 签名不变；结果新增 `k_avg: List[float]`（各层平均导热系数）
  - `WallSolution` 新增字段 `k_avg: List[float]`，加入 `as_dict()`

- [ ] **Step 1: 写失败测试**

```python
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
```

- [ ] **Step 2: 运行测试确认失败**

Run: `python -m pytest tests/test_calc.py -k "integral_mean_k" -v`
Expected: FAIL —— `import` 报错（函数不存在）。

- [ ] **Step 3: 实现 `integral_mean_k`**

在 `kiln_ht/calc.py` 中，放在 `air_properties` 之后：

```python
def integral_mean_k(k_coef: Tuple[float, float, float], T_h_c: float, T_c_c: float) -> float:
    """温度相关导热系数的层内积分平均（T 单位 ℃）。

    k(T) = a + b·T + c·T²；热面 T_h_c、冷面 T_c_c（℃）。
    积分平均：k_avg = ∫_{Tc}^{Th} k(T) dT / (Th - Tc)
    = a + b·(Th+Tc)/2 + c·(Th²+Th·Tc+Tc²)/3
    当 Th≈Tc 时退化为 k(T)。
    """
    a, b, c = k_coef
    dT = T_h_c - T_c_c
    if abs(dT) < 1e-9:
        Tm = (T_h_c + T_c_c) / 2.0
        return a + b * Tm + c * Tm * Tm
    return a + b * (T_h_c + T_c_c) / 2.0 + c * (T_h_c ** 2 + T_h_c * T_c_c + T_c_c ** 2) / 3.0
```

- [ ] **Step 4: 运行测试确认通过**

Run: `python -m pytest tests/test_calc.py -k "integral_mean_k" -v`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add kiln_ht/calc.py
git commit -m "feat(kiln_ht): 新增 integral_mean_k 温度相关导热系数积分平均"
```

- [ ] **Step 6: 写 solve_wall 升级的失败测试**

在 `tests/test_calc.py` 追加：

```python
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
```

- [ ] **Step 7: 运行测试确认失败**

Run: `python -m pytest tests/test_calc.py -k "solve_wall_k or solve_wall_rc or solve_wall_rc_default or solve_wall_k_avg or solve_wall_thick_fiber" -v`
Expected: FAIL —— `WallSolution` 无 `k_avg` 字段（AttributeError/TypeError）。

- [ ] **Step 8: 改写 `solve_wall` 支持 k(T) + Rc**

在 `kiln_ht/calc.py` 中：
1. `WallSolution` dataclass 增加字段 `k_avg: List[float]`（放在 `iterations` 之前，给默认值 `field(default_factory=list)` 或放在末尾给默认值）。为保持兼容，放在 `iterations: int = 0` 之后：

```python
    iterations: int = 0      # 实际迭代步数
    k_avg: List[float] = field(default_factory=list)   # 各层积分平均导热系数 (W/m·K)
```

  需在文件头导入 `field`：`from dataclasses import dataclass, field`。`as_dict()` 增加 `"k_avg": list(self.k_avg)`。

2. `solve_wall` 主循环改造。核心逻辑：每层 k 用积分平均（依赖当前界面温度估计），接触热阻加入热阻网络。

```python
    # 各层界面半径
    radii = [r_in]
    for l in layers:
        radii.append(radii[-1] + l.thickness)
    T_g, T_a = params.T_gas, params.T_env

    # 初值：内壁贴近烟气（辐射强），外壳假设比环境高 150 K
    T_w1 = T_g - 20
    T_wN = T_a + 150
    relax = 0.4
    prev_corr1 = None
    Qprime = 0.0
    h_conv_in = h_rad_in = h_conv_out = h_rad_out = 0.0
    eg = 0.3
    k_avg = [l.k_const for l in layers]      # 初始估计：取常数项
    R_wall = [0.0] * len(layers)
    R_contact = [0.0] * len(layers)
    for it in range(MAX_WALL_ITER):
        # 用当前 k_avg 估计各层界面温度（圆筒壁递推），用于更新 k(T)
        # 界面温度 [T0=内壁, T1, ..., Tn=外壁]
        T_iface_est = [T_w1]
        for i, R in enumerate(R_wall):
            T_iface_est.append(T_iface_est[-1] - Qprime * R)
        T_iface_est[-1] = T_wN

        # 更新各层积分平均导热系数（层内 T 取 ℃）
        k_avg = [
            integral_mean_k(l.k_coef, T_iface_est[i] - 273.15, T_iface_est[i + 1] - 273.15)
            for i, l in enumerate(layers)
        ]

        # 内侧：对流 + 烟气辐射
        T_f = (T_g + T_w1) / 2
        h_conv_in = inner_convection_h(params.v_gas, params.L_char, L, T_f)
        h_rad_in, eg = inner_radiation_h(
            T_g, T_w1, params.eps_wall, beam, params.CO2, params.H2O, params.P_total)
        h_in = h_conv_in + h_rad_in

        # 外侧：自然对流 + 强制对流组合
        D_out = 2.0 * r_out
        h_nat_out = outer_natural_h(T_wN, T_a, D_out)
        h_for_out = outer_forced_h(params.v_amb, T_wN, T_a, D_out)
        h_conv_out = (h_nat_out ** 3.5 + h_for_out ** 3.5) ** (1.0 / 3.5)
        h_rad_out = outer_radiation_h(T_wN, T_a, params.eps_shell)
        h_out = h_conv_out + h_rad_out

        # 单位长度热阻网络（含 k(T) 导热热阻 + 层间接触热阻）
        R_in = 1.0 / (h_in * 2.0 * math.pi * r_in)
        for i, l in enumerate(layers):
            R_wall[i] = math.log(radii[i + 1] / radii[i]) / (2.0 * math.pi * k_avg[i])
            R_contact[i] = l.Rc / (2.0 * math.pi * radii[i + 1])   # 界面在 radii[i+1]
        R_out = 1.0 / (h_out * 2.0 * math.pi * r_out)
        R_tot = R_in + sum(R_wall) + sum(R_contact) + R_out

        Qprime = (T_g - T_a) / R_tot
        T_w1_new = T_g - Qprime * R_in
        T_wN_new = T_a + Qprime * R_out

        # 松弛迭代（自适应阻尼）
        corr1 = T_w1_new - T_w1
        corrN = T_wN_new - T_wN
        if prev_corr1 is not None and corr1 * prev_corr1 < 0:
            relax = max(0.15, relax * 0.7)
        T_w1 = T_w1 + relax * corr1
        T_wN = T_wN + relax * corrN
        prev_corr1 = corr1
        if max(abs(corr1), abs(corrN)) < WALL_TOL:
            break

    # 各分界面温度（Kelvin）：[内壁, 层1右端, ..., 外壁]
    T_iface = [T_w1]
    for R in R_wall:
        T_iface.append(T_iface[-1] - Qprime * R)
    T_iface[-1] = T_wN

    q_in = Qprime / (2.0 * math.pi * r_in)
    q_out = Qprime / (2.0 * math.pi * r_out)

    return WallSolution(
        Qprime=Qprime, q_in=q_in, q_out=q_out,
        h_in=h_in, h_out=h_out,
        h_conv_in=h_conv_in, h_rad_in=h_rad_in,
        h_conv_out=h_conv_out, h_rad_out=h_rad_out,
        eg=eg, T_w1=T_w1, T_wN=T_wN,
        r_in=r_in, r_out=r_out, T_iface=T_iface,
        R_wall=R_wall, R_in=R_in, R_out=R_out, R_tot=R_tot,
        iterations=it + 1,
        k_avg=k_avg,
    )
```

> 注意：`solve_wall` 的层校验部分（现有代码）不变，但需改为校验 `k_coef`：调用 `Layer` 的 `k_at(500.0)` 或直接校验 `l.k_coef[0] > 0`。现有校验用 `layer.k <= 0`，改为 `layer.k_const <= 0`。

- [ ] **Step 9: 运行测试确认通过**

Run: `python -m pytest tests/test_calc.py -v`
Expected: PASS（新增的 k(T)/Rc 测试 + 原有回归测试全部通过）

- [ ] **Step 10: 提交**

```bash
git add kiln_ht/calc.py kiln_ht/__init__.py tests/test_calc.py
git commit -m "feat(kiln_ht): solve_wall 支持 k(T) 积分平均导热与层间接触热阻"
```

---

### Task 3: 材料库 materials.py

**Files:**
- Create: `kiln_ht/materials.py`
- Modify: `kiln_ht/__init__.py`
- Test: `tests/test_materials.py`（新增）

**Interfaces:**
- Consumes: 无
- Produces:
  - `MATERIALS: Dict[str, dict]` —— 材料名 → `{"k_coef": (a,b,c), "valid_range_c": (lo,hi)}`
  - `get_material(name: str) -> dict` —— 按名称返回；未知名抛 `KeyError`
  - `material_names() -> List[str]` —— 所有材料名（GUI 下拉用）

- [ ] **Step 1: 写失败测试**

创建 `tests/test_materials.py`：

```python
# -*- coding: utf-8 -*-
"""材料库单元测试。"""
import pytest

from kiln_ht.materials import MATERIALS, get_material, material_names


def test_materials_present():
    """应内置常用耐火材料。"""
    for name in ["硅酸铝纤维", "轻质砖", "高铝砖", "重质高铝浇注料", "钢壳"]:
        assert name in MATERIALS


def test_materials_k_coef_shape():
    """每个材料 k_coef 为 3 元组且数值有限。"""
    for name, m in MATERIALS.items():
        assert len(m["k_coef"]) == 3
        assert all(math.isfinite(v) for v in m["k_coef"])
        assert m["valid_range_c"][0] < m["valid_range_c"][1]


def test_materials_k_positive_in_range():
    """材料 k(T) 在有效温度范围内为正值。"""
    for name, m in MATERIALS.items():
        lo, hi = m["valid_range_c"]
        a, b, c = m["k_coef"]
        for T in [lo, (lo + hi) / 2, hi]:
            k = a + b * T + c * T * T
            assert k > 0, f"{name} 在 {T}℃ 时 k={k} <= 0"


def test_get_material():
    """get_material 返回与 MATERIALS 一致。"""
    assert get_material("硅酸铝纤维") == MATERIALS["硅酸铝纤维"]


def test_get_material_unknown():
    """未知材料抛 KeyError。"""
    with pytest.raises(KeyError):
        get_material("不存在的材料")


def test_material_names():
    """material_names 返回全部材料名。"""
    assert set(material_names()) == set(MATERIALS.keys())
```

- [ ] **Step 2: 运行测试确认失败**

Run: `python -m pytest tests/test_materials.py -v`
Expected: FAIL —— `ModuleNotFoundError: No module named 'kiln_ht.materials'`

- [ ] **Step 3: 创建 `kiln_ht/materials.py`**

```python
# -*- coding: utf-8 -*-
"""耐火材料 k(T) 导热系数库（工程数据，来自耐火材料手册/国标）。

k(T) = a + b·T + c·T²（T 单位 ℃）。valid_range_c 为有效温度范围 (℃)。
数据来源：耐火材料手册、GB/T 标准及主流产品技术参数。
"""

from typing import Dict, List, Tuple

MATERIALS: Dict[str, dict] = {
    "硅酸铝纤维":      {"k_coef": (0.08, 1.2e-4, 0.0),     "valid_range_c": (0, 1200)},
    "轻质砖":          {"k_coef": (0.32, 1.8e-4, 0.0),     "valid_range_c": (0, 1200)},
    "高铝砖":          {"k_coef": (1.05, 1.5e-4, 0.0),     "valid_range_c": (0, 1400)},
    "重质高铝浇注料":   {"k_coef": (1.2, 4.5e-4, -1.2e-7),   "valid_range_c": (0, 1400)},
    "钢壳":            {"k_coef": (45.0, 0.0, 0.0),        "valid_range_c": (0, 500)},
}


def get_material(name: str) -> dict:
    """按名称获取材料，未知名称抛 KeyError。"""
    if name not in MATERIALS:
        raise KeyError(f"未知材料: {name}（可选：{', '.join(MATERIALS)}）")
    return MATERIALS[name]


def material_names() -> List[str]:
    """返回全部材料名。"""
    return list(MATERIALS.keys())
```

- [ ] **Step 4: 更新 `kiln_ht/__init__.py` 导出**

在 `kiln_ht/__init__.py` 中增加导入与导出：

```python
from .calc import (
    DEFAULT_P_TOTAL,
    GRAVITY,
    MAX_WALL_ITER,
    SIGMA,
    WALL_TOL,
    KilnParams,
    Layer,
    WallSolution,
    air_properties,
    compute_temperature_curve,
    gas_emissivity,
    inner_convection_h,
    inner_radiation_h,
    integral_mean_k,
    outer_forced_h,
    outer_natural_h,
    outer_radiation_h,
    solve_wall,
    validate_params,
)
from .materials import MATERIALS, get_material, material_names
```

- [ ] **Step 5: 运行测试确认通过**

Run: `python -m pytest tests/test_materials.py tests/test_calc.py -v`
Expected: PASS（材料库测试 + 核心回归）

- [ ] **Step 6: 提交**

```bash
git add kiln_ht/materials.py kiln_ht/__init__.py tests/test_materials.py
git commit -m "feat(kiln_ht): 新增耐火材料 k(T) 材料库"
```

---

### Task 4: FastAPI server.py 适配 k_coef / Rc

**Files:**
- Modify: `server.py`
- Test: `tests/test_web_ui.py`（追加 API 模型测试）

**Interfaces:**
- Consumes: Task 1/2 的 `Layer(k_coef, Rc)`、Task 3 的 `get_material`
- Produces: `LayerIn` Pydantic 模型支持 `k_coef`、`Rc`，兼容 `k`

- [ ] **Step 1: 写失败测试**

在 `tests/test_web_ui.py` 追加：

```python
def test_api_layer_k_compat(app_imports):
    """API LayerIn 只传 k 时兼容为 k_coef=(k,0,0)。"""
    from server import LayerIn
    layer = LayerIn(name="砖", thickness=0.05, k=0.10)
    assert layer.k_coef == (0.10, 0.0, 0.0)
    assert layer.Rc == 0.0


def test_api_layer_k_coef_direct(app_imports):
    """API LayerIn 支持直接传 k_coef 与 Rc。"""
    from server import LayerIn
    layer = LayerIn(name="纤维", thickness=0.05, k_coef=(0.08, 1.2e-4, 0.0), Rc=0.005)
    assert layer.k_coef == (0.08, 1.2e-4, 0.0)
    assert layer.Rc == 0.005


def test_api_solve_with_k_coef(app_imports):
    """/solve 端点接受 k_coef，返回 k_avg。"""
    from server import app as fastapi_app
    from fastapi.testclient import TestClient
    client = TestClient(fastapi_app)
    resp = client.post("/solve", json={
        "layers": [{"name": "纤维", "thickness": 0.15, "k_coef": [0.08, 1.2e-4, 0.0]}],
        "params": {},
    })
    assert resp.status_code == 200
    data = resp.json()
    assert "k_avg" in data
    assert len(data["k_avg"]) == 1
```

- [ ] **Step 2: 运行测试确认失败**

Run: `python -m pytest tests/test_web_ui.py -k "api_" -v`
Expected: FAIL —— `LayerIn` 无 `k_coef` 属性（pydantic 会忽略未知字段或报错），`k_avg` 不存在。

- [ ] **Step 3: 更新 `server.py` 的 `LayerIn`**

```python
class LayerIn(BaseModel):
    name: str = Field("层", description="层名称")
    thickness: float = Field(..., gt=0, description="厚度 (m)")
    k: Optional[float] = Field(None, gt=0, description="导热系数 (W/m·K)，兼容旧客户端")
    k_coef: Optional[Tuple[float, float, float]] = Field(
        None, description="k(T)=a+bT+cT² 系数 (T 单位 ℃)")
    Rc: float = Field(0.0, ge=0, description="层间接触热阻 (m²·K/W)")
```

  更新导入：`from typing import List, Optional, Tuple`。
  更新 `_to_domain`：

```python
def _to_domain(req: SolveRequest):
    layers = []
    for l in req.layers:
        if l.k_coef is None:
            # 兼容旧客户端：用 k（若提供）或默认 1.0
            k = l.k if l.k is not None else 1.0
            k_coef = (k, 0.0, 0.0)
        else:
            k_coef = tuple(l.k_coef)
        layers.append(Layer(name=l.name, thickness=l.thickness,
                            k_coef=k_coef, Rc=l.Rc))
    params = KilnParams(**req.params.model_dump()) if req.params else KilnParams()
    return layers, params
```

> 注意：pydantic 对 `Tuple[float, float, float]` 支持从 list/JSON 解析。若担心兼容，可用 `List[float]` 加 `min_length=3, max_length=3`，转换时 `tuple(...)`。此处用 `Optional[List[float]]` 更稳妥，改为：

```python
    k_coef: Optional[List[float]] = Field(
        None, min_length=3, max_length=3, description="k(T)=a+bT+cT² 系数 (T 单位 ℃)")
```

  转换处加长度校验：

```python
        if l.k_coef is None:
            k = l.k if l.k is not None else 1.0
            k_coef = (k, 0.0, 0.0)
        else:
            k_coef = (l.k_coef[0], l.k_coef[1], l.k_coef[2])
```

- [ ] **Step 4: 运行测试确认通过**

Run: `python -m pytest tests/test_web_ui.py -k "api_" -v`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add server.py tests/test_web_ui.py
git commit -m "feat(api): FastAPI 支持 k_coef / Rc，兼容 k 输入"
```

---

### Task 5: Streamlit app.py 适配 k_coef + 材料下拉

**Files:**
- Modify: `app.py`
- Test: `tests/test_web_ui.py`

**Interfaces:**
- Consumes: Task 3 `material_names()` / `get_material()`、Task 2 `solve_wall`
- Produces: 界面支持材料下拉 + k_coef 编辑 + Rc 输入；`_solve()` 构建 `Layer(k_coef=..., Rc=...)`

- [ ] **Step 1: 写失败测试**

在 `tests/test_web_ui.py` 追加：

```python
def test_web_ui_material_select(app):
    """衬层应有材料下拉框，选中后填充 k_coef。"""
    # 每层应有一个材料选择框（selectbox），加上侧边栏的预设选择
    assert len(app.selectbox) >= 5   # 1 个预设 + 4 层材料
    # 选择某层为硅酸铝纤维后计算应成功
    _click_calc(app)
    assert not app.exception


def test_web_ui_rc_input(app):
    """衬层应有接触热阻输入框（默认 0）。"""
    rc_inputs = [n for n in app.number_input if (n.key or "").endswith("_rc")]
    assert len(rc_inputs) == 4
    assert all(n.value == 0.0 for n in rc_inputs)
```

- [ ] **Step 2: 运行测试确认失败**

Run: `python -m pytest tests/test_web_ui.py -k "material or rc_input" -v`
Expected: FAIL —— 界面还没有材料下拉/接触热阻输入。

- [ ] **Step 3: 更新 `app.py`**

1. 导入材料库：
```python
from kiln_ht import (
    KilnParams,
    Layer,
    MATERIALS,
    get_material,
    material_names,
    compute_temperature_curve,
    solve_wall,
)
```

2. `_add_layer` 增加 `k_coef` 与 `Rc` 参数（默认常数 k）：

```python
def _add_layer(name="", thickness_mm=50.0, k=1.0, k_coef=None, Rc=0.0):
    _ss.layer_count = _ss.get("layer_count", 0) + 1
    _ss.layers.append({
        "uid": _ss.layer_count,
        "name": name,
        "thickness_mm": float(thickness_mm),
        "k": float(k),
        "k_coef": list(k_coef) if k_coef else None,
        "Rc": float(Rc),
    })
```

3. `_solve()` 构建 Layer：

```python
    layers = []
    for i, row in enumerate(_ss.layers):
        k_coef = row.get("k_coef")
        if k_coef is None:
            k_coef = (float(row["k"]), 0.0, 0.0)
        layers.append(Layer(
            name=row["name"].strip() or f"层{i+1}",
            thickness=float(row["thickness_mm"]) / 1000.0,
            k_coef=tuple(k_coef),
            Rc=float(row.get("Rc", 0.0)),
        ))
```

4. 衬层配置区域（主区上部）：每行加材料下拉。在列布局中把"导热系数"改为"材料"下拉 + 展开 k_coef 编辑：

```python
col_hint = st.columns([0.22, 0.22, 0.24, 0.12, 0.2])
col_hint[0].markdown("**层名称**")
col_hint[1].markdown("**厚度 (mm)**")
col_hint[2].markdown("**材料**")
col_hint[3].markdown("**操作**")
col_hint[4].markdown("**接触热阻 Rc (m²·K/W)**")

for idx, row in enumerate(_ss.layers):
    uid = row.get("uid", idx + 1)
    c1, c2, c3, c4, c5 = st.columns([0.22, 0.22, 0.24, 0.12, 0.2])
    row["name"] = c1.text_input("层名称", value=row["name"], key=f"layer_{uid}_name",
                                label_visibility="collapsed")
    row["thickness_mm"] = c2.number_input(
        "厚度", value=float(row["thickness_mm"]), min_value=0.1, step=1.0,
        key=f"layer_{uid}_thick", label_visibility="collapsed")

    # 材料下拉：默认「自定义」，选择后自动填充 k_coef 并 rerun
    cur_material = row.get("material_name", "自定义")
    sel = c3.selectbox(
        "材料", ["自定义"] + material_names(), index=0,
        key=f"layer_{uid}_material", label_visibility="collapsed")
    if sel != cur_material:
        row["material_name"] = sel
        if sel != "自定义":
            m = get_material(sel)
            row["k_coef"] = list(m["k_coef"])
        st.rerun()

    # 若为自定义材料，显示 a/b/c 编辑；否则只读显示当前系数（可展开编辑）
    with c3.expander("系数 a/b/c", expanded=(row.get("k_coef") is None or sel == "自定义")):
        if row.get("k_coef") is None:
            row["k_coef"] = [float(row["k"]), 0.0, 0.0]
        row["k_coef"] = [
            c3.number_input("a", value=float(row["k_coef"][0]), key=f"layer_{uid}_a"),
            c3.number_input("b", value=float(row["k_coef"][1]), key=f"layer_{uid}_b"),
            c3.number_input("c", value=float(row["k_coef"][2]), key=f"layer_{uid}_c"),
        ]

    row["Rc"] = c5.number_input(
        "Rc", value=float(row.get("Rc", 0.0)), min_value=0.0, step=0.001,
        key=f"layer_{uid}_rc", label_visibility="collapsed")

    # 操作按钮列（原逻辑）
    btn_container = c4.container()
    bcols = btn_container.columns(4)
    with bcols[0]:
        if st.button("⬆", key=f"layer_{uid}_up", disabled=(idx == 0)):
            _move_layer(idx, -1)
            st.rerun()
    with bcols[1]:
        if st.button("⬇", key=f"layer_{uid}_down",
                     disabled=(idx == len(_ss.layers) - 1)):
            _move_layer(idx, +1)
            st.rerun()
    with bcols[2]:
        if st.button("🗑", key=f"layer_{uid}_del", disabled=(len(_ss.layers) <= 1)):
            _remove_layer(idx)
            st.rerun()
    with bcols[3]:
        st.write("")
```

> 注意：Streamlit `st.rerun()` 在列内调用会重建 UI。上面材料选择的联动逻辑用 `row["material_name"]` 记录当前选择状态，避免每次 rerun 都重置。原 `k` 字段保留（`_load_preset` 用它），`k_coef` 由 `k` 初始化。

5. 详细工况结果 expander 中增加各层 k_avg 显示（可选，有 `sol.k_avg` 时显示）。

- [ ] **Step 4: 运行测试确认通过**

Run: `python -m pytest tests/test_web_ui.py -v`
Expected: PASS（新增 + 原有 web 测试）

- [ ] **Step 5: 提交**

```bash
git add app.py tests/test_web_ui.py
git commit -m "feat(web): Streamlit 支持材料下拉 / k_coef / 接触热阻"
```

---

### Task 6: Kivy main.py 适配 k_coef + Rc

**Files:**
- Modify: `main.py`
- Test: `tests/test_ui.py`

**Interfaces:**
- Consumes: Task 3 材料库、Task 2 `solve_wall`
- Produces: Kivy 输入页层参数支持 k_coef / Rc；`collect_params()` 构建 `Layer(k_coef=..., Rc=...)`

- [ ] **Step 1: 写失败测试**

在 `tests/test_ui.py` 追加：

```python
class TestUILayerKT:
    """Kivy 输入页 k_coef / 接触热阻采集测试。"""

    def test_layer_rows_have_kt_fields(self, app):
        _, root = app
        ins = root.input_screen
        # 每个层行应包含 (name, thick, k 相关字段)：现在为元组扩展
        # 兼容旧断言：旧 _layer_rows 为 3 元组，新增字段后为 5 元组
        first = ins._layer_rows[0]
        assert len(first) >= 5

    def test_collect_params_with_rc(self, app):
        _, root = app
        ins = root.input_screen
        layers, _ = ins.collect_params()
        assert layers[0].Rc == 0.0

    def test_collect_params_k_coef_from_material(self, app):
        _, root = app
        ins = root.input_screen
        # 默认第 0 层材料选「自定义」系数 (1,0,0)
        layers, _ = ins.collect_params()
        assert layers[0].k_coef == (1.0, 0.0, 0.0)
```

- [ ] **Step 2: 运行测试确认失败**

Run: `python -m pytest tests/test_ui.py -k "kt or rc or k_coef" -v`
Expected: FAIL —— `_layer_rows` 仍为 3 元组。

- [ ] **Step 3: 更新 `main.py`**

1. 导入材料库：
```python
from kiln_ht import (
    Layer,
    KilnParams,
    MATERIALS,
    get_material,
    material_names,
    solve_wall,
    compute_temperature_curve,
)
```

2. `_rebuild_layers()`：每行增加"材料"列（下拉）与"接触热阻"列。Kivy 无原生下拉，用 `Spinner`（kivy.uix.spinner）：

```python
from kivy.uix.spinner import Spinner
```

  表头与数据行改造：

```python
        head = BoxLayout(spacing=dp(8), size_hint_y=None, height=dp(28))
        head.add_widget(MdLabel(text="名称", color=TEXT_DIM, font_size=sp(12),
                                size_hint_x=None, width=dp(84)))
        head.add_widget(MdLabel(text="厚度(mm)", color=TEXT_DIM, font_size=sp(12),
                                size_hint_x=0.7))
        head.add_widget(MdLabel(text="材料", color=TEXT_DIM, font_size=sp(12),
                                size_hint_x=1))
        head.add_widget(MdLabel(text="Rc(m²K/W)", color=TEXT_DIM, font_size=sp(12),
                                size_hint_x=None, width=dp(70)))
        self.layer_grid.add_widget(head)
        for i in range(n):
            row = BoxLayout(spacing=dp(8), size_hint_y=None, height=dp(46))
            name = UnitInput(input_cls=TextInput, unit="", default=f"层{i+1}", halign="left")
            name.textinput.multiline = False
            name.size_hint_x = None
            name.width = dp(84)
            thick = UnitInput(unit="", default="50")
            thick.size_hint_x = 0.7
            mat = Spinner(text="自定义", values=["自定义"] + material_names(),
                          size_hint_x=1, font_size=sp(12),
                          background_color=CARD)
            rc = UnitInput(unit="", default="0.0")
            rc.size_hint_x = None
            rc.width = dp(70)
            row.add_widget(name)
            row.add_widget(thick)
            row.add_widget(mat)
            row.add_widget(rc)
            self._layer_rows.append((name, thick, mat, rc))
            self.layer_grid.add_widget(row)
```

  `_layer_rows` 变为 4 元组 `(name, thick, mat, rc)`。

3. `collect_params()` 构建 Layer：

```python
    def collect_params(self):
        layers = []
        for i, (name, thick, mat, rc) in enumerate(self._layer_rows):
            if mat.text == "自定义":
                k_coef = (1.0, 0.0, 0.0)   # 自定义默认常数 k=1
            else:
                k_coef = get_material(mat.text)["k_coef"]
            layers.append(Layer(
                name=name.text.strip() or f"层{i+1}",
                thickness=float(thick.text) / 1000.0,
                k_coef=k_coef,
                Rc=float(rc.text),
            ))
        # ... 其余 params 解析不变
```

> 注意：`test_ui.py` 中 `test_layer_name_accepts_custom_text` 使用 `ins._layer_rows[0]` 解包为 `(name, thick, k)`，需改为 4 元组解包。Kivy 中 `mat.text` 与 `rc` 均可直接访问。若需自定义 k_coef 的 a/b/c 编辑，可在选"自定义"时展开三个输入框（本计划最小实现为自定义=常数 k=1，材料=从库选）。后续可扩展。

- [ ] **Step 4: 同步更新 `tests/test_ui.py` 旧断言**

- `test_default_layers`：`layers[0].k == 1.0` 仍成立（`Layer.k` 兼容字段保留），但断言可改为 `layers[0].k_coef == (1.0, 0.0, 0.0)` 更明确。
- `test_layer_name_accepts_custom_text`：`name, thick, k = ins._layer_rows[0]` 改为 `name, thick, mat, rc = ins._layer_rows[0]`。
- `test_calc_with_custom_layers`：直接构造 `Layer(..., k=...)` 仍兼容（`k` 字段保留）。

- [ ] **Step 5: 运行测试确认通过**

Run: `python -m pytest tests/test_ui.py -v`
Expected: PASS（Kivy mock 窗口下全部通过）

- [ ] **Step 6: 提交**

```bash
git add main.py tests/test_ui.py
git commit -m "feat(kivy): 输入页支持材料下拉 / k_coef / 接触热阻"
```

---

### Task 7: 归档遗留脚本 + 清理打包产物

**Files:**
- Create: `../Archive/`（在仓库根目录 `python/` 下）
- Modify: 无（仅移动文件）

**Interfaces:**
- Consumes: 无
- Produces: 根目录整洁；遗留脚本进入 `Archive/` 保留可查

- [ ] **Step 1: 先提交当前根目录状态（若根目录无 git）**

```bash
cd "F:/工作文件/水泥窑小组/python"
git rev-parse --is-inside-work-tree 2>/dev/null || git init
git add -A
git commit -m "chore: 归档前基线快照" -q
```

- [ ] **Step 2: 建立归档目录结构并移动文件**

```bash
cd "F:/工作文件/水泥窑小组/python"
mkdir -p Archive/old_scripts Archive/ansys Archive/particle

# 传热脚本变体（非主项目）
mv "传热.py" "传热gui.py" "传热copilot.py" "传热copilot2.py" "传热copilot2 - 副本.py" \
   "传热google.py" "传热计算插值（缩放）.py" "Heat_tr.py" "Heat_tr - 副本.py" \
   "test_Heat_tr_review.py" "优化版温度分布.txt" "HC.py" Archive/old_scripts/

# ANSYS 相关
mv apdl.py "apdl传热.py" "apdl传热 - 副本.py" "AnsysGen.cs" "AnsysGen - 副本.cs" \
   "AnsysGen - 副本 (2).cs" "HeatCalc.cs" "PipeHeatCalc.cs" "PipeHeatCalc(未考虑热辐射).cs" \
   "PipeHeatCalcRefine.cs" "AnsysGen.exe" "HeatCalc.exe" "HeatCalc1.exe" \
   "PipeHeatCalc_换热系数经验值15.exe" "PipeHeatCalc.exe" "PipeHeatCalcRE.exe" \
   *.inp Archive/ansys/

# 颗粒堆积类
mv "紧密堆积.py" "最紧密堆积.py" "Modified Andreasen.py" Archive/particle/

# 打包产物
rm -rf Heat_tr.build Heat_tr.dist
```

- [ ] **Step 3: 确认移动结果**

```bash
cd "F:/工作文件/水泥窑小组/python"
echo "=== 根目录剩余 .py/.cs ==="
ls *.py *.cs 2>/dev/null || echo "（仅剩 cement-kiln-heat-transfer/ 与 Archive/）"
echo "=== Archive 结构 ==="
find Archive -type f | sort
```

Expected: 根目录只剩 `cement-kiln-heat-transfer/`、`Archive/`、`.claude/`（及可能的 `传热计算/` 若保留）。

- [ ] **Step 4: 提交归档**

```bash
cd "F:/工作文件/水泥窑小组/python"
git add -A
git commit -m "chore: 归档遗留脚本与 ANSYS/颗粒堆积相关文件"
```

---

### Task 8: 全量回归测试 + README 更新

**Files:**
- Modify: `cement-kiln-heat-transfer/README.md`
- Test: 全量 pytest

**Interfaces:**
- Consumes: 所有前序任务
- Produces: 全绿测试 + 更新后的 README（含 k_coef / Rc / 材料库用法）

- [ ] **Step 1: 运行全量测试**

```bash
cd "F:/工作文件/水泥窑小组/python/cement-kiln-heat-transfer"
python -m pytest tests/ -v
```

Expected: 全部 PASS（test_calc.py / test_ui.py / test_web_ui.py / test_materials.py）

- [ ] **Step 2: 更新 README**

在 README.md 的"功能特性"与"计算核心"部分补充：
- k(T) 温度相关导热系数（`Layer(k_coef=(a,b,c))`，常数 k 用 `k_coef=(k,0,0)`）
- 层间接触热阻 `Layer(Rc=...)`
- 材料库 `from kiln_ht import MATERIALS, get_material`，列出内置材料

示例调用更新：

```python
from kiln_ht import Layer, KilnParams, solve_wall
layers = [
    Layer('硅酸铝纤维', 0.150, k_coef=(0.08, 1.2e-4, 0.0)),
    Layer('轻质砖',     0.100, k_coef=(0.32, 1.8e-4, 0.0)),
    Layer('高铝砖',     0.080, k_coef=(1.05, 1.5e-4, 0.0)),
    Layer('钢壳',       0.012, k_coef=(45.0, 0.0, 0.0)),
]
sol = solve_wall(layers, KilnParams())
print(sol.as_dict())   # 含 k_avg
```

- [ ] **Step 3: 运行测试确认通过**

Run: `python -m pytest tests/ -v`
Expected: 全部 PASS

- [ ] **Step 4: 提交**

```bash
git add README.md
git commit -m "docs: README 更新 k(T) / 接触热阻 / 材料库用法"
```

---

## Self-Review（实施前执行者自查）

### 1. Spec 覆盖
- k(T) 二项式（T 单位 ℃）→ Task 1/2 ✅
- 常数 k 兼容 → Task 1（`__post_init__`）✅
- 层间接触热阻 Rc → Task 2（`R_contact = Rc/(2πr)`）✅
- 材料库（手册工程数据）→ Task 3 ✅
- FastAPI 适配 → Task 4 ✅
- Streamlit 适配 → Task 5 ✅
- Kivy 适配 → Task 6 ✅
- 归档遗留脚本 → Task 7 ✅
- 全量测试 + README → Task 8 ✅

### 2. 占位符扫描
- 无 TBD/TODO；所有代码步骤含完整实现。

### 3. 类型一致性
- `k_coef` 三元组 `(a,b,c)`：Task 1 定义，Task 2 `integral_mean_k` 使用，Task 3 材料库，Task 4-6 各入口一致。
- `Rc` 字段名：Task 1 定义，Task 2 使用，Task 4-6 一致。
- `solve_wall` 返回 `WallSolution.k_avg`：Task 2 定义，Task 4 测试断言，Task 5 可选展示，一致。
- Kivy `_layer_rows` 从 3 元组 → 4 元组：Task 6 明确标注需同步更新旧测试解包。
