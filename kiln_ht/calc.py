# -*- coding: utf-8 -*-
"""
多层结构一维稳态传热计算核心（圆筒壁工程模型版，无 UI / 服务依赖）。

物理模型与公式依据：
- 回转窑窑衬多层圆筒壁稳态传热（以单位长度热功率 Q' 为守恒量）
- 内侧：管内强制对流（Gnielinski，含入口效应修正） + 烟气辐射（Hottel/Leckner 灰气体）
- 外侧：水平圆柱自然对流（Churchill-Chu）或外掠强制对流（Zhukauskas） + 外壳辐射
- 空气物性随温度变化（Sutherland 拟合）；内/外壁温双侧耦合迭代求解
- 温度曲线采用圆筒壁内对数分布精确解

工程依据：
- 气体辐射/回转窑对流：github.com/mptutvt/rotaryPyrolysis（Tscheng-Watkinson 模型）
- 外壳散热：github.com/mvoggu/heat_simulation（水泥窑壳散热）
- 传热学关联式：Gnielinski、Churchill-Chu、Zhukauskas、Hottel/Leckner

本模块零第三方依赖，仅使用 Python 标准库（math），可在任意平台直接运行；
也是为了避免 Android 交叉编译 numpy 带来的脆弱性，便于 Kivy 移动端打包。
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

# ============ 物理常数 ============
SIGMA = 5.670374419e-8      # Stefan-Boltzmann 常数 W/(m²·K⁴)
GRAVITY = 9.81              # 重力加速度 m/s²
MAX_WALL_ITER = 200         # 壁温耦合迭代上限
WALL_TOL = 0.05             # 壁温收敛容差 (K)
DEFAULT_P_TOTAL = 1.01325   # 系统默认总压 (bar，1 atm)


# ============ 数据模型 ============
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


@dataclass
class KilnParams:
    """回转窑工况参数（国际单位）。

    T_gas / T_env 为热力学温度 (K)；CO2 / H2O 为体积分数 (0~1)；
    P_total 为窑内总压 (bar)；L_char 为窑内径 (m)。
    """

    N_total: int = 100          # 温度曲线取点数
    T_gas: float = 1523.15      # 烟气温度 (K)，默认 1250 ℃
    v_gas: float = 3.0          # 烟气流速 (m/s)
    L_char: float = 4.0         # 窑内径 (m)
    L_kiln: float = 60.0        # 窑长 (m)
    P_total: float = 1.01325    # 窑内压力 (bar)
    CO2: float = 0.20           # CO2 体积分数
    H2O: float = 0.08           # H2O 体积分数
    eps_wall: float = 0.85      # 内壁发射率
    T_env: float = 298.15       # 环境温度 (K)，默认 25 ℃
    v_amb: float = 2.0          # 环境风速 (m/s)
    eps_shell: float = 0.85     # 外壳发射率


@dataclass
class WallSolution:
    """求解结果：单位长度热功率、热流密度、界面温度、热阻与换热系数分解。"""

    Qprime: float            # 单位长度热功率 (W/m)
    q_in: float              # 内壁面热流密度 (W/m²)
    q_out: float             # 外壁面热流密度 (W/m²)
    h_in: float              # 内壁总换热系数 (W/m²·K)
    h_out: float             # 外壁总换热系数 (W/m²·K)
    h_conv_in: float
    h_rad_in: float
    h_conv_out: float
    h_rad_out: float
    eg: float                # 烟气发射率
    T_w1: float              # 内壁面温度 (K)
    T_wN: float              # 外壁面温度 (K)
    r_in: float              # 内半径 (m)
    r_out: float             # 外半径 (m)
    T_iface: List[float]     # 各分界面温度 (K)：[内壁, 层1右端, ..., 外壁]
    R_wall: List[float]      # 各层圆筒壁热阻 (m·K/W)
    R_in: float              # 内壁对流热阻 (m·K/W)
    R_out: float             # 外壁对流热阻 (m·K/W)
    R_tot: float             # 总热阻 (m·K/W)
    iterations: int = 0      # 实际迭代步数
    k_avg: List[float] = field(default_factory=list)   # 各层积分平均导热系数 (W/m·K)

    def as_dict(self) -> Dict:
        """转为纯 dict，便于 JSON 序列化。"""
        return {
            "Qprime": self.Qprime,
            "q_in": self.q_in,
            "q_out": self.q_out,
            "h_in": self.h_in,
            "h_out": self.h_out,
            "h_conv_in": self.h_conv_in,
            "h_rad_in": self.h_rad_in,
            "h_conv_out": self.h_conv_out,
            "h_rad_out": self.h_rad_out,
            "eg": self.eg,
            "T_w1": self.T_w1,
            "T_wN": self.T_wN,
            "r_in": self.r_in,
            "r_out": self.r_out,
            "T_iface": self.T_iface,
            "R_wall": self.R_wall,
            "R_in": self.R_in,
            "R_out": self.R_out,
            "R_tot": self.R_tot,
            "iterations": self.iterations,
            "k_avg": list(self.k_avg),
        }


# ============ 空气物性 ============
def air_properties(T_k: float) -> Tuple[float, float, float]:
    """温度依赖的空气物性（Sutherland 拟合）。

    返回 (导热系数 lam W/m·K, Prandtl 数 Pr, 运动黏度 nu m²/s)。
    """
    mu = 1.458e-6 * T_k ** 1.5 / (T_k + 110.4)   # 动力黏度 (Pa·s)
    rho = 101325 / (287 * T_k)                   # 密度 (kg/m³)，理想气体
    nu = mu / rho
    lam = 2.495e-3 * T_k ** 1.5 / (T_k + 194)    # 导热系数 (W/m·K)
    return lam, 0.71, nu


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


# ============ 内侧换热 ============
def inner_convection_h(v: float, D: float, L: float, T_f: float) -> float:
    """管内强制对流换热系数 (W/m²·K)（Gnielinski + 入口效应修正）。

    - Re >= 10000：Gnielinski（充分发展湍流）
    - Re <  2300：层流充分发展恒定 Nu=3.66
    - 2300~10000：线性平滑过渡
    - 平均 Nu 乘以入口效应修正因子 (1+(D/L)^(2/3))
    """
    lam, Pr, nu = air_properties(T_f)
    Re = v * D / nu
    if Re >= 10000:
        f = (0.79 * math.log(Re) - 1.64) ** -2        # Petukhov 摩擦因子
        Nu_fd = (f / 8.0) * (Re - 1000) * Pr / (
            1 + 12.7 * math.sqrt(f / 8.0) * (Pr ** (2.0 / 3.0) - 1))
    elif Re <= 2300:
        Nu_fd = 3.66
    else:
        # 过渡区（2300~10000）线性插值，避免层流/湍流突变
        f = (0.79 * math.log(Re) - 1.64) ** -2
        Nu_turb = (f / 8.0) * (Re - 1000) * Pr / (
            1 + 12.7 * math.sqrt(f / 8.0) * (Pr ** (2.0 / 3.0) - 1))
        x = (Re - 2300) / (10000 - 2300)
        Nu_fd = 3.66 + x * (Nu_turb - 3.66)
    # 入口效应修正（有限长管内平均 Nu）
    Nu = Nu_fd * (1.0 + (D / L) ** (2.0 / 3.0))
    return Nu * lam / D


def gas_emissivity(
    T_g: float,
    pCO2: float,
    pH2O: float,
    beam: float,
    P_total: float = DEFAULT_P_TOTAL,
) -> float:
    """水泥窑烟气辐射发射率（Hottel/Leckner 灰气体拟合）。

    pCO2/pH2O 为体积分数 (0~1)；beam 为气体平均射线程长 (m)，圆柱空腔取 0.95*D；
    P_total 为系统总压 (bar)，默认 1.01325 bar（1 atm）。

    Leckner 相关式采用分压×射线长度 p·L (bar·m)，故先由体积分数×总压求得各组元分压。
    说明：相关式可靠范围 T_g > ~500 K 且 pL < 5 bar·m；
         低温烟气辐射贡献微弱，500~600K 线性过渡避免发射率非物理跳变。
    """
    pCO2 = max(pCO2, 1e-4)
    pH2O = max(pH2O, 1e-4)
    P_CO2 = pCO2 * P_total          # 分压 (bar)
    P_H2O = pH2O * P_total          # 分压 (bar)
    pL_CO2 = P_CO2 * beam           # bar·m
    pL_H2O = P_H2O * beam           # bar·m
    # pL 超出相关式范围时保守截断
    if pL_CO2 + pL_H2O > 5.0:
        pL_CO2 = min(pL_CO2, 4.0)
        pL_H2O = min(pL_H2O, 1.0)

    def _leckner(T: float) -> float:
        Td = T / 1000.0
        e_CO2 = 0.2257 * Td ** -1.5 * pL_CO2 ** 0.4 / (
            1 + 0.2757 * Td ** -0.5 * pL_CO2 ** 0.5)
        e_H2O = 0.569 * Td ** -0.5 * pL_H2O ** 0.3 / (
            1 + 0.569 * Td ** -0.5 * pL_H2O ** 0.5)
        de = 0.0089 * Td ** -1.5 * (pL_CO2 + pL_H2O) ** 0.5 / (
            1 + 0.0089 * Td ** -1.5 * (pL_CO2 + pL_H2O) ** 0.5)
        return min(1.0, max(0.0, e_CO2 + e_H2O - de))

    if T_g < 600.0:
        # 相关式低温段拟合发散且辐射贡献微弱：500K 以下取近似值，500~600K 线性过渡
        if T_g <= 500.0:
            return 0.02
        eg_600 = _leckner(600.0)
        frac = (T_g - 500.0) / 100.0
        return 0.02 + frac * (eg_600 - 0.02)
    return _leckner(T_g)


def inner_radiation_h(
    T_g: float,
    T_w: float,
    eps_wall: float,
    beam: float,
    pCO2: float,
    pH2O: float,
    P_total: float = DEFAULT_P_TOTAL,
) -> Tuple[float, float]:
    """烟气-内壁辐射等效换热系数 (W/m²·K)（灰气体-灰壁面空腔模型）。

    返回 (h_rad, eg)：h_rad 等效辐射换热系数，eg 烟气发射率。
    """
    eg = gas_emissivity(T_g, pCO2, pH2O, beam, P_total)
    h_rad = SIGMA * (T_g ** 2 + T_w ** 2) * (T_g + T_w) / (
        1.0 / eg + 1.0 / eps_wall - 1.0)
    return h_rad, eg


# ============ 外侧换热 ============
def outer_natural_h(T_s: float, T_a: float, D: float) -> float:
    """水平圆柱自然对流换热系数 (W/m²·K)，Churchill-Chu 关联式。"""
    dT = T_s - T_a
    if abs(dT) < 1e-3:
        # 极低温差下 Ra→0，Nu→0.6（底噪），避免数值不稳定
        T_f = (T_s + T_a) / 2
        lam, _, _ = air_properties(T_f)
        return 0.6 * lam / D
    T_f = (T_s + T_a) / 2
    lam, Pr, nu = air_properties(T_f)
    beta = 1.0 / T_f                                  # 理想气体体膨胀系数
    # 换热系数仅取决于温差大小 |ΔT|（方向由 (T_g-T_a) 决定），
    # 取绝对值避免负 Ra 导致 Ra**(1/6) 产生复数
    Ra = GRAVITY * beta * abs(dT) * D ** 3 / nu ** 2 * Pr
    expr = 0.60 + 0.387 * Ra ** (1.0 / 6.0) / (
        1 + (0.559 / Pr) ** (9.0 / 16.0)) ** (8.0 / 27.0)
    Nu = expr ** 2
    return Nu * lam / D


def outer_forced_h(v: float, T_s: float, T_a: float, D: float) -> float:
    """外掠水平圆柱强制对流换热系数 (W/m²·K)，Zhukauskas 关联式。"""
    T_f = (T_s + T_a) / 2
    lam, Pr, nu = air_properties(T_f)
    Re = v * D / nu
    if Re < 40:
        C, n = 0.75, 0.4
    elif Re < 1000:
        C, n = 0.51, 0.5
    elif Re < 2e5:
        C, n = 0.26, 0.6
    else:
        C, n = 0.076, 0.7
    Nu = C * Re ** n * Pr ** (1.0 / 3.0)
    return Nu * lam / D


def outer_radiation_h(T_s: float, T_a: float, eps: float) -> float:
    """外壳表面辐射等效换热系数 (W/m²·K)。"""
    return eps * SIGMA * (T_s ** 2 + T_a ** 2) * (T_s + T_a)


# ============ 参数校验 ============
def validate_params(params: KilnParams) -> None:
    """校验工况参数，非法时抛出 ValueError。"""
    if params.N_total < 10:
        raise ValueError("N_total 不能低于 10")
    if params.v_gas <= 0:
        raise ValueError("烟气流速需为正值")
    if params.L_char <= 0:
        raise ValueError("窑内径需为正值")
    if params.L_kiln <= 0:
        raise ValueError("窑长需为正值")
    if params.P_total <= 0:
        raise ValueError("窑内压力需为正值")
    if not (0 < params.CO2 < 1):
        raise ValueError("CO2 体积分数需在 0~1 之间")
    if not (0 < params.H2O < 1):
        raise ValueError("H2O 体积分数需在 0~1 之间")
    if not (0 < params.eps_wall <= 1):
        raise ValueError("内壁发射率需在 0~1 之间")
    if params.v_amb < 0:
        raise ValueError("环境风速不能为负")
    if not (0 < params.eps_shell <= 1):
        raise ValueError("外壳发射率需在 0~1 之间")


# ============ 主求解 ============
def solve_wall(layers: List[Layer], params: KilnParams) -> WallSolution:
    """圆筒壁多层传热求解：以单位长度热功率 Q'(W/m) 为守恒量。

    热阻网络（单位长度，m·K/W）：
        R_in'  = 1/(h_in · 2πr_in)            内壁对流+辐射
        R_i'   = ln(r_{i+1}/r_i) / (2πk_i)    第 i 层圆筒导热
        R_out' = 1/(h_out · 2πr_out)          外壁对流+辐射
    """
    validate_params(params)
    if not layers:
        raise ValueError("至少需要 1 层衬里结构")
    for i, layer in enumerate(layers):
        if layer.thickness <= 0:
            raise ValueError(f"第 {i + 1} 层厚度需为正值")
        if layer.k_const <= 0:
            raise ValueError(f"第 {i + 1} 层导热系数需为正值")

    r_in = params.L_char / 2.0
    r_out = r_in + sum(l.thickness for l in layers)
    beam = 0.95 * params.L_char              # 气体平均射线程长
    L = params.L_kiln
    # 各层界面半径
    radii = [r_in]
    for l in layers:
        radii.append(radii[-1] + l.thickness)
    T_g, T_a = params.T_gas, params.T_env

    # 初值：内壁贴近烟气（辐射强），外壳假设比环境高 150 K
    T_w1 = T_g - 20
    T_wN = T_a + 150
    relax = 0.4                # 松弛因子（自适应阻尼，极端工况自动减小）
    prev_corr1 = None          # 上一轮内壁温修正量（用于振荡检测）
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

        # 外侧：自然对流 + 强制对流 采用 Churchill-Usagi 组合相关式（指数 3.5）
        # 注意：不能在 v_amb≈0.5 处硬切换自然/强制对流——大直径窑筒体自然对流系数
        # （约 4.5 W/m²K）远高于低速强制对流（0.5 m/s 时约 1.6 W/m²K），硬切换会在
        # 临界点造成外壁温度约 13℃ 的非物理阶跃。组合相关式保证 h 随风速单调递增、
        # 外壁温度随风速单调递减，符合物理规律。
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

        # 松弛迭代（自适应阻尼：检测振荡时减小，避免极端导热/保温结构发散）
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
    # 最外层界面温度与已收敛的外壁迭代值严格一致（消除收敛残差造成的不一致）
    T_iface[-1] = T_wN

    q_in = Qprime / (2.0 * math.pi * r_in)     # 内壁面热流密度 W/m²
    q_out = Qprime / (2.0 * math.pi * r_out)   # 外壁面热流密度 W/m²

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


def compute_temperature_curve(
    layers: List[Layer],
    sol: WallSolution,
    n_points: Optional[int] = None,
) -> Tuple[List[float], List[float]]:
    """计算沿壁厚方向的温度分布。

    返回 (x_mm, T_c)：
        x_mm — 距内壁距离 (mm)
        T_c  — 温度 (℃)
    各层内采用圆筒壁对数分布精确解，导热系数使用 solve_wall 的积分平均 k_avg。
    纯标准库实现，不依赖 numpy。
    """
    n_points = max(n_points or 500, 2)
    # 各层界面位置 (m)
    positions = [0.0]
    for l in layers:
        positions.append(positions[-1] + l.thickness)
    total = positions[-1]
    x_all = [total * i / (n_points - 1) for i in range(n_points)]
    T_all = [0.0] * n_points
    for j, x in enumerate(x_all):
        for i, l in enumerate(layers):
            if positions[i] <= x <= positions[i + 1]:
                r_i = sol.r_in + positions[i]
                k_avg = sol.k_avg[i] if i < len(sol.k_avg) else l.k_const
                T_all[j] = sol.T_iface[i] - (sol.Qprime / (2.0 * math.pi * k_avg)) * math.log(
                    (sol.r_in + x) / r_i)
                break
    return [x * 1000.0 for x in x_all], [t - 273.15 for t in T_all]
