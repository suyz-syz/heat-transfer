# -*- coding: utf-8 -*-
"""
水泥窑窑衬传热计算 —— Streamlit Web GUI（桌面 / 平板宽屏版）。

功能：
- 侧边栏（Sidebar）：窑体与热工参数、环境参数。温度统一以 ℃ 输入，
  后台自动换算为 K 后调用计算核心。
- 主区上部（Main Area Top）：动态衬层配置，支持增删、上移/下移、
  常用预设工况一键加载。
- 主区下部（Main Area Bottom）：核心指标 Dashboard（外壁/内壁温度、
  总热损失 Q'、烟气发射率）+ Plotly 交互式温度分布曲线，标注各分界面节点温度。

计算核心复用 kiln_ht/calc.py（与 APK、FastAPI 完全一致）。

本地运行：
    pip install -r requirements.txt
    streamlit run app.py
Docker 运行：见 Dockerfile。
"""

from __future__ import annotations

import streamlit as st
import pandas as pd

from kiln_ht import (
    KilnParams,
    Layer,
    compute_temperature_curve,
    solve_wall,
)

# ============ 页面基础配置 ============
st.set_page_config(
    page_title="水泥窑窑衬传热计算",
    page_icon="🔥",
    layout="wide",
    initial_sidebar_state="expanded",
)

# 保留输入状态（Streamlit 每次脚本重跑，靠 session_state 保存）
_ss = st.session_state

# 预设工况：名称 -> (衬层列表, 工况参数覆盖)
PRESETS = {
    "典型4层水泥窑烧成带衬体": {
        "layers": [
            {"name": "硅酸铝纤维", "thickness_mm": 150.0, "k": 0.10},
            {"name": "轻质砖", "thickness_mm": 100.0, "k": 0.30},
            {"name": "高铝砖", "thickness_mm": 80.0, "k": 1.50},
            {"name": "钢壳", "thickness_mm": 12.0, "k": 45.0},
        ],
        "overrides": {"T_gas_C": 1250.0, "L_char": 4.0, "L_kiln": 60.0,
                      "CO2": 20.0, "H2O": 8.0},
    },
    "典型2层轻质保温衬体": {
        "layers": [
            {"name": "硅酸铝纤维", "thickness_mm": 150.0, "k": 0.10},
            {"name": "钢壳", "thickness_mm": 12.0, "k": 45.0},
        ],
        "overrides": {"T_gas_C": 1100.0, "L_char": 3.2, "L_kiln": 48.0,
                      "CO2": 18.0, "H2O": 6.0},
    },
    "典型5层特种窑衬": {
        "layers": [
            {"name": "浇注料", "thickness_mm": 120.0, "k": 0.60},
            {"name": "硅酸铝纤维", "thickness_mm": 80.0, "k": 0.10},
            {"name": "轻质砖", "thickness_mm": 100.0, "k": 0.30},
            {"name": "高铝砖", "thickness_mm": 80.0, "k": 1.50},
            {"name": "钢壳", "thickness_mm": 12.0, "k": 45.0},
        ],
        "overrides": {"T_gas_C": 1350.0, "L_char": 4.4, "L_kiln": 70.0,
                      "CO2": 22.0, "H2O": 9.0},
    },
}

# ============ 工具函数 ============
def _init_layer_state():
    """初始化衬层列表（存到 session_state，键为 layer_{idx}）。"""
    if "layer_count" not in _ss:
        _ss.layer_count = 0
    if "layers" not in _ss:
        _ss.layers = []
        _add_layer()
        _add_layer()
        _add_layer()
        _add_layer()


def _add_layer(name="", thickness_mm=50.0, k=1.0):
    _ss.layers.append({
        "name": name,
        "thickness_mm": float(thickness_mm),
        "k": float(k),
    })


def _remove_layer(idx: int):
    if len(_ss.layers) > 1:
        _ss.layers.pop(idx)


def _move_layer(idx: int, direction: int):
    """direction: -1 上移, +1 下移。"""
    j = idx + direction
    if 0 <= j < len(_ss.layers):
        _ss.layers[idx], _ss.layers[j] = _ss.layers[j], _ss.layers[idx]


def _load_preset(name: str):
    preset = PRESETS[name]
    _ss.layers = []
    for layer in preset["layers"]:
        _add_layer(layer["name"], layer["thickness_mm"], layer["k"])
    for key, val in preset["overrides"].items():
        _ss[f"preset_{key}"] = val


# ============ 计算 ============
def _solve():
    """从界面状态组装参数并调用计算核心，返回 (layers, sol, x_mm, T_c) 或抛出 ValueError。"""
    layers = [
        Layer(
            name=row["name"].strip() or f"层{i+1}",
            thickness=float(row["thickness_mm"]) / 1000.0,
            k=float(row["k"]),
        )
        for i, row in enumerate(_ss.layers)
    ]
    params = KilnParams(
        N_total=_ss.N_total,
        T_gas=float(_ss.T_gas_C) + 273.15,          # ℃ -> K
        v_gas=_ss.v_gas,
        L_char=_ss.L_char,
        L_kiln=_ss.L_kiln,
        P_total=_ss.P_total,
        CO2=_ss.CO2 / 100.0,                        # % -> 体积分数
        H2O=_ss.H2O / 100.0,
        eps_wall=_ss.eps_wall,
        T_env=float(_ss.T_env_C) + 273.15,          # ℃ -> K
        v_amb=_ss.v_amb,
        eps_shell=_ss.eps_shell,
    )
    sol = solve_wall(layers, params)
    x_mm, T_c = compute_temperature_curve(layers, sol, n_points=params.N_total)
    return layers, sol, x_mm, T_c


# ============ 界面 ============
_init_layer_state()

# ---------- 侧边栏：工况参数 ----------
with st.sidebar:
    st.header("🔥 工况参数")
    st.caption("温度以 ℃ 输入，后台自动换算为 K")

    # 常用预设一键加载
    preset_choice = st.selectbox("预设工况（一键加载）", ["（手动配置）"] + list(PRESETS),
                                 key="preset_choice")
    if preset_choice != "（手动配置）" and not _ss.get("_preset_loaded", False):
        _load_preset(preset_choice)
        _ss._preset_loaded = True
        st.success(f"已加载预设：{preset_choice}")
        st.rerun()
    if preset_choice == "（手动配置）":
        _ss._preset_loaded = False

    st.subheader("窑体与热工参数")
    T_gas_C = st.number_input("烟气温度 (°C)", value=1250.0, step=10.0, key="T_gas_C")
    v_gas = st.number_input("烟气流速 (m/s)", value=3.0, min_value=0.01, step=0.1,
                            key="v_gas")
    L_char = st.number_input("窑内径 (m)", value=4.0, step=0.1, key="L_char")
    L_kiln = st.number_input("窑长 (m)", value=60.0, step=1.0, key="L_kiln")
    P_total = st.number_input("窑内压力 (bar)", value=1.01325, step=0.1, key="P_total")
    CO2 = st.number_input("CO₂ 含量 (%)", value=20.0, min_value=0.0, max_value=100.0,
                          step=0.5, key="CO2")
    H2O = st.number_input("H₂O 含量 (%)", value=8.0, min_value=0.0, max_value=100.0,
                          step=0.5, key="H2O")
    eps_wall = st.number_input("内壁发射率", value=0.85, min_value=0.05, max_value=1.0,
                               step=0.01, key="eps_wall")

    st.subheader("环境参数")
    T_env_C = st.number_input("环境温度 (°C)", value=25.0, step=1.0, key="T_env_C")
    v_amb = st.number_input("环境风速 (m/s)", value=2.0, min_value=0.0, step=0.1,
                            key="v_amb")
    eps_shell = st.number_input("外壳发射率", value=0.85, min_value=0.05, max_value=1.0,
                                step=0.01, key="eps_shell")

    st.divider()
    N_total = st.slider("温度曲线取点数", min_value=50, max_value=1000, value=100,
                        step=50, key="N_total")

    st.divider()
    if st.button("🚀 开始计算", type="primary", width="stretch"):
        _ss.calc_trigger = True
    else:
        _ss.calc_trigger = False

# ---------- 主区上部：衬层配置 ----------
st.title("水泥窑窑衬传热计算")
st.caption("多层圆筒壁一维稳态传热 · 计算核心与 APK / FastAPI 完全一致")

st.subheader("🧱 衬层配置")
st.caption("可添加、删除、上下移动耐火衬层；厚度单位为 mm，导热系数单位为 W/(m·K)")

col_hint = st.columns([0.25, 0.3, 0.3, 0.15])
col_hint[0].markdown("**层名称**")
col_hint[1].markdown("**厚度 (mm)**")
col_hint[2].markdown("**导热系数 λ (W/(m·K))**")
col_hint[3].markdown("**操作**")

for idx, row in enumerate(_ss.layers):
    c1, c2, c3, c4 = st.columns([0.25, 0.3, 0.3, 0.15])
    row["name"] = c1.text_input("层名称", value=row["name"], key=f"layer_{idx}_name",
                                label_visibility="collapsed")
    row["thickness_mm"] = c2.number_input(
        "厚度", value=float(row["thickness_mm"]), min_value=0.1, step=1.0,
        key=f"layer_{idx}_thick", label_visibility="collapsed")
    row["k"] = c3.number_input(
        "导热系数", value=float(row["k"]), min_value=0.001, step=0.05,
        key=f"layer_{idx}_k", label_visibility="collapsed")

    # 操作按钮列
    btn_container = c4.container()
    bcols = btn_container.columns(4)
    with bcols[0]:
        if st.button("⬆", key=f"layer_{idx}_up", disabled=(idx == 0)):
            _move_layer(idx, -1)
            st.rerun()
    with bcols[1]:
        if st.button("⬇", key=f"layer_{idx}_down", disabled=(idx == len(_ss.layers) - 1)):
            _move_layer(idx, +1)
            st.rerun()
    with bcols[2]:
        if st.button("🗑", key=f"layer_{idx}_del", disabled=(len(_ss.layers) <= 1)):
            _remove_layer(idx)
            st.rerun()
    with bcols[3]:
        st.write("")

if st.button("➕ 添加衬层", width="stretch"):
    _add_layer()
    st.rerun()

st.divider()

# ---------- 主区下部：结果 ----------
st.subheader("📊 计算结果")

if _ss.get("calc_trigger"):
    try:
        layers, sol, x_mm, T_c = _solve()
    except (ValueError, Exception) as exc:  # noqa: BLE001 —— UI 层统一捕获展示
        st.error(f"计算失败：{exc}")
        st.stop()

    # ---- 核心指标 Dashboard ----
    m1, m2, m3, m4 = st.columns(4)
    m1.metric("外壁面温度", f"{sol.T_wN - 273.15:.1f} °C",
              delta=f"外壁温升 {(sol.T_wN - 273.15) - float(_ss.T_env_C):.1f} °C")
    m2.metric("内壁面温度", f"{sol.T_w1 - 273.15:.1f} °C")
    m3.metric("总热损失 Q'", f"{sol.Qprime:.1f} W/m")
    m4.metric("烟气发射率", f"{sol.eg:.3f}")

    # ---- 分界面温度表 ----
    rows = [("内壁面", sol.T_iface[0])]
    for i in range(1, len(sol.T_iface) - 1):
        rows.append((f"{layers[i-1].name} / {layers[i].name}", sol.T_iface[i]))
    rows.append(("外壁面", sol.T_iface[-1]))

    st.subheader("各分界面温度")
    st.dataframe(
        pd.DataFrame(
            [{"分界面": name, "温度 (°C)": tk - 273.15, "温度 (K)": tk}
             for name, tk in rows],
            columns=["分界面", "温度 (°C)", "温度 (K)"],
        ),
        width="stretch",
        hide_index=True,
    )

    # ---- 交互式温度分布曲线 ----
    st.subheader("温度分布曲线（内壁 → 外壁）")
    try:
        import plotly.graph_objects as go
        fig = go.Figure()
        fig.add_trace(go.Scatter(
            x=x_mm, y=T_c, mode="lines+markers",
            line=dict(color="#1E88E5", width=3),
            marker=dict(size=5, color="#FF9800"),
            name="温度分布",
            hovertemplate="距内壁 %{x:.1f} mm · %{y:.1f} °C<extra></extra>",
        ))
        # 标注各分界面节点温度（灰色竖线 + 节点）
        # 各层界面位置 (mm)
        positions = [0.0]
        for l in layers:
            positions.append(positions[-1] + l.thickness_mm)
        for p, (name, tk) in zip(positions, rows):
            fig.add_vline(x=p, line_dash="dot", line_color="#9CA3AF", opacity=0.5)
            fig.add_trace(go.Scatter(
                x=[p], y=[tk - 273.15], mode="markers+text",
                marker=dict(size=9, color="#EF5350", symbol="diamond"),
                text=[f"{name} {tk - 273.15:.0f}°C"],
                textposition="top center", textfont=dict(color="#ECEDEE", size=11),
                showlegend=False, hovertemplate=f"{name} · %{{y:.1f}} °C<extra></extra>",
            ))
        fig.update_layout(
            title=dict(text="壁厚方向温度分布（℃）", font=dict(size=16)),
            xaxis=dict(title="距内壁距离 (mm)", gridcolor="#3A3D42"),
            yaxis=dict(title="温度 (°C)", gridcolor="#3A3D42"),
            paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
            font=dict(color="#ECEDEE"),
            hovermode="x unified",
            margin=dict(l=10, r=10, t=40, b=10),
            height=520,
            legend=dict(orientation="h", yanchor="bottom", y=1.02, x=0),
        )
        st.plotly_chart(fig, width="stretch")
    except ImportError:
        # 未安装 plotly 时回退到纯 matplotlib 曲线
        try:
            import matplotlib
            matplotlib.use("Agg")
            import matplotlib.pyplot as plt
            figm, ax = plt.subplots(figsize=(10, 5), facecolor="#121212")
            ax.plot(x_mm, T_c, color="#1E88E5", lw=2.5, marker="o", ms=4)
            for p, (name, tk) in zip(positions, rows):
                ax.axvline(p, color="#9CA3AF", ls=":", lw=1)
                ax.plot(p, tk - 273.15, "D", color="#EF5350")
                ax.annotate(f"{name}\n{tk - 273.15:.0f}°C", (p, tk - 273.15),
                            textcoords="offset points", xytext=(0, 8), ha="center",
                            color="#ECEDEE", fontsize=9)
            ax.set_xlabel("距内壁距离 (mm)", color="#ECEDEE")
            ax.set_ylabel("温度 (°C)", color="#ECEDEE")
            ax.set_title("壁厚方向温度分布", color="#ECEDEE")
            ax.grid(color="#3A3D42", alpha=0.6)
            for spine in ax.spines.values():
                spine.set_color("#3A3D42")
            ax.tick_params(colors="#ECEDEE")
            st.pyplot(figm)
        except ImportError:
            st.warning("未安装 plotly 或 matplotlib，无法绘制曲线")

    # ---- 详细工况结果 ----
    with st.expander("查看详细工况结果"):
        st.dataframe(
            pd.DataFrame(
                [
                    {"指标": "单位长度热功率 Q'", "数值": f"{sol.Qprime:.1f} W/m"},
                    {"指标": "内壁热流密度 q_in", "数值": f"{sol.q_in:.1f} W/m²"},
                    {"指标": "外壁热流密度 q_out", "数值": f"{sol.q_out:.1f} W/m²"},
                    {"指标": "内壁总换热系数 h_in", "数值": f"{sol.h_in:.1f} W/m²·K"},
                    {"指标": "　内壁对流 h_conv", "数值": f"{sol.h_conv_in:.1f} W/m²·K"},
                    {"指标": "　内壁辐射 h_rad", "数值": f"{sol.h_rad_in:.1f} W/m²·K"},
                    {"指标": "外壁总换热系数 h_out", "数值": f"{sol.h_out:.1f} W/m²·K"},
                    {"指标": "　外壁对流 h_conv", "数值": f"{sol.h_conv_out:.1f} W/m²·K"},
                    {"指标": "　外壁辐射 h_rad", "数值": f"{sol.h_rad_out:.1f} W/m²·K"},
                    {"指标": "耦合迭代步数", "数值": str(sol.iterations)},
                ],
                columns=["指标", "数值"],
            ),
            width="stretch",
            hide_index=True,
        )

    st.success("计算完成 ✅")
else:
    st.info("请在左侧「工况参数」配置参数，点击「🚀 开始计算」查看结果。")
