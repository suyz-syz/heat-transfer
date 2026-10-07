#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""水泥窑传热计算 - Streamlit 增强版

新增功能：
- Material Design 3 暗色主题
- 三档参数分组（必填/常用/高级）
- 工况模板系统
- 智能验证系统
- 历史对比功能（最多5条）
"""

import datetime
import json
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Tuple, List, Dict, Any

import streamlit as st
import plotly.graph_objects as go
import numpy as np

# 假设 kiln_ht 包已存在
from kiln_ht import (
    Layer,
    KilnParams,
    solve_wall,
    WallSolution,
    MATERIALS,
)

# ============ 配置 ============
st.set_page_config(
    page_title="水泥窑传热计算",
    page_icon="🔥",
    layout="wide",
    initial_sidebar_state="collapsed",
)

# ============ Material Design 3 暗色主题 CSS ============
MD3_DARK_CSS = """
<style>
:root {
    --md-sys-color-primary: #A8C7FA;
    --md-sys-color-on-primary: #062E6F;
    --md-sys-color-secondary: #BCC7DB;
    --md-sys-color-surface: #1A1C1E;
    --md-sys-color-surface-variant: #42474E;
    --md-sys-color-on-surface: #E2E2E5;
    --md-sys-color-error: #FFB4AB;
    --md-sys-color-warning: #FFD700;
}

/* 全局背景 */
.stApp {
    background-color: var(--md-sys-color-surface);
    color: var(--md-sys-color-on-surface);
}

/* 卡片样式 */
.metric-card {
    background: var(--md-sys-color-surface-variant);
    border-radius: 16px;
    padding: 20px;
    margin: 10px 0;
}

/* 主按钮 */
.stButton > button {
    background: var(--md-sys-color-primary) !important;
    color: var(--md-sys-color-on-primary) !important;
    border-radius: 20px;
    font-weight: 500;
    padding: 12px 24px;
}

/* 折叠面板 */
.stExpander {
    border: 1px solid var(--md-sys-color-surface-variant);
    border-radius: 12px;
    background: var(--md-sys-color-surface);
}

/* 警告/错误样式 */
.stAlert[data-baseweb="notification"] {
    border-radius: 12px;
}
</style>
"""

st.markdown(MD3_DARK_CSS, unsafe_allow_html=True)

# ============ 数据结构 ============
@dataclass
class CalculationRecord:
    """单次计算历史记录"""
    timestamp: str
    label: str  # 简短描述，如 "T_gas=1250°C · 3层"
    params_summary: str  # 参数摘要
    solution: dict  # WallSolution 转为字典
    curve_data: Tuple[list, list]  # (x_mm, T_c)
    layers_info: list  # 衬层结构快照

# ============ 工况模板 ============
PRESETS = {
    "回转窑-高温区": {
        "params": {
            "T_gas": 1250 + 273.15,
            "T_env": 25 + 273.15,
            "v_gas": 2.5,
            "L_char": 4.0,
            "emiss_gas": 0.7,
            "emiss_wall": 0.85,
            "h_out": 15.0,
        },
        "layers": [
            {"name": "工作层", "thickness_mm": 150, "k_coef": (0.5, 0.0003, 0)},
            {"name": "保温层", "thickness_mm": 80, "k_coef": (0.12, 0.0001, 0)},
            {"name": "钢壳", "thickness_mm": 20, "k_coef": (45, 0, 0)},
        ],
    },
    "篦冷机-快冷区": {
        "params": {
            "T_gas": 850 + 273.15,
            "T_env": 30 + 273.15,
            "v_gas": 5.0,
            "L_char": 3.5,
            "emiss_gas": 0.6,
            "emiss_wall": 0.8,
            "h_out": 20.0,
        },
        "layers": [
            {"name": "耐磨砖", "thickness_mm": 100, "k_coef": (1.2, 0.0002, 0)},
            {"name": "保温层", "thickness_mm": 60, "k_coef": (0.15, 0.0001, 0)},
            {"name": "钢板", "thickness_mm": 15, "k_coef": (50, 0, 0)},
        ],
    },
}

# ============ 智能验证系统 ============
def validate_config(layers: List[dict], params_dict: dict) -> Tuple[bool, dict]:
    """智能验证衬层配置和参数

    Returns:
        (是否通过, {"errors": [...], "warnings": [...], "infos": [...]})
    """
    errors = []
    warnings = []
    infos = []

    # 检查1: 衬层厚度合理性
    total_thickness = sum(l["thickness_mm"] for l in layers)
    if total_thickness > 500:
        warnings.append(f"⚠️ 总厚度 {total_thickness:.0f} mm 较厚，请确认是否合理")
    elif total_thickness < 50:
        errors.append(f"🔴 总厚度 {total_thickness:.0f} mm 过小，至少需要 50 mm")

    for i, layer in enumerate(layers):
        t = layer["thickness_mm"]
        if t < 5:
            errors.append(f"🔴 层{i+1}「{layer['name']}」厚度 {t:.1f} mm < 5 mm")
        elif t > 200:
            warnings.append(f"⚠️ 层{i+1}「{layer['name']}」厚度 {t:.0f} mm 较大")

    # 检查2: 温度梯度估算
    if "T_gas_C" in params_dict and "T_env_C" in params_dict:
        delta_T = params_dict["T_gas_C"] - params_dict["T_env_C"]
        gradient = delta_T / (total_thickness / 1000.0) if total_thickness > 0 else 0
        if gradient > 5000:
            infos.append(f"ℹ️ 温度梯度约 {gradient:.0f} K/m，属高温工况")

    # 检查3: 导热系数合理性
    for i, layer in enumerate(layers):
        a, b, c = layer["k_coef"]
        if a <= 0:
            errors.append(f"🔴 层{i+1}「{layer['name']}」导热系数 a={a} ≤ 0")
        elif a > 50 and layer["name"] not in ["钢壳", "钢板", "金属"]:
            warnings.append(f"⚠️ 层{i+1}「{layer['name']}」导热系数 a={a:.1f} 疑似过大（非金属？)")

    # 检查4: Fourier 数（瞬态特性）
    if "v_gas" in params_dict and params_dict["v_gas"] > 10:
        warnings.append(f"⚠️ 烟气流速 {params_dict['v_gas']:.1f} m/s 较高，对流换热占主导")

    return len(errors) == 0, {"errors": errors, "warnings": warnings, "infos": infos}

# ============ 历史记录管理 ============
def _add_to_history(layers, params, sol, x_mm, T_c) -> None:
    """添加到历史记录（最多保留5条）"""
    if "calc_history" not in st.session_state:
        st.session_state.calc_history = []

    # WallSolution 转字典
    sol_dict = {
        "T_w1": sol.T_w1,
        "T_wN": sol.T_wN,
        "Qprime": sol.Qprime,
        "q_in": sol.q_in,
        "q_out": sol.q_out,
        "h_in": sol.h_in,
        "h_out": sol.h_out,
        "iterations": sol.iterations,
    }

    record = CalculationRecord(
        timestamp=datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        label=f"T_gas={params.T_gas - 273.15:.0f}°C · {len(layers)}层",
        params_summary=f"窑内径{params.L_char:.1f}m · 烟气{params.v_gas:.1f}m/s",
        solution=sol_dict,
        curve_data=(list(x_mm), list(T_c)),
        layers_info=[{k: v for k, v in l.items() if k != "uid"} for l in st.session_state.layers],
    )

    st.session_state.calc_history.insert(0, record)
    if len(st.session_state.calc_history) > 5:
        st.session_state.calc_history = st.session_state.calc_history[:5]

# ============ 状态初始化 ============
def _init_state():
    """初始化 session_state"""
    _ss = st.session_state

    _ss.setdefault("layers", [
        {"name": "工作层", "thickness_mm": 150.0, "k_coef": (0.5, 0.0003, 0), "uid": 1},
        {"name": "保温层", "thickness_mm": 80.0, "k_coef": (0.12, 0.0001, 0), "uid": 2},
        {"name": "钢壳", "thickness_mm": 20.0, "k_coef": (45.0, 0, 0), "uid": 3},
    ])
    _ss.setdefault("last_result", None)
    _ss.setdefault("calc_history", [])

    # 三档参数
    _ss.setdefault("T_gas_C", 1250.0)
    _ss.setdefault("T_env_C", 25.0)
    _ss.setdefault("v_gas", 2.5)
    _ss.setdefault("L_char", 4.0)
    _ss.setdefault("emiss_gas", 0.7)
    _ss.setdefault("emiss_wall", 0.85)
    _ss.setdefault("h_out", 15.0)

_init_state()
_ss = st.session_state

# ============ 视图：参数输入（三档分组）============
def _view_params():
    st.header("🎛️ 工况参数")

    # 工况模板加载
    col_preset, col_save = st.columns([3, 1])
    with col_preset:
        preset = st.selectbox("工况模板", ["自定义"] + list(PRESETS.keys()))
        if preset != "自定义" and st.button("📥 加载模板"):
            data = PRESETS[preset]
            # 加载参数
            for k, v in data["params"].items():
                if k == "T_gas":
                    _ss.T_gas_C = v - 273.15
                elif k == "T_env":
                    _ss.T_env_C = v - 273.15
                else:
                    _ss[k] = v
            # 加载衬层
            _ss.layers = [{**l, "uid": i+1} for i, l in enumerate(data["layers"])]
            st.success(f"✅ 已加载模板：{preset}")
            st.rerun()

    # 必填参数（默认展开）
    with st.expander("🔥 必填参数", expanded=True):
        col1, col2 = st.columns(2)
        with col1:
            _ss.T_gas_C = st.number_input(
                "烟气温度 (°C)", 500.0, 2000.0, _ss.T_gas_C, 10.0
            )
        with col2:
            _ss.T_env_C = st.number_input(
                "环境温度 (°C)", -20.0, 60.0, _ss.T_env_C, 1.0
            )

    # 常用参数（默认展开）
    with st.expander("⚙️ 常用参数", expanded=True):
        col1, col2 = st.columns(2)
        with col1:
            _ss.v_gas = st.number_input(
                "烟气流速 (m/s)", 0.1, 20.0, _ss.v_gas, 0.1
            )
        with col2:
            _ss.L_char = st.number_input(
                "窑内径 (m)", 1.0, 10.0, _ss.L_char, 0.1
            )

    # 高级参数（默认收起）
    with st.expander("🔬 高级参数", expanded=False):
        col1, col2, col3 = st.columns(3)
        with col1:
            _ss.emiss_gas = st.number_input(
                "烟气发射率", 0.1, 1.0, _ss.emiss_gas, 0.01
            )
        with col2:
            _ss.emiss_wall = st.number_input(
                "内壁发射率", 0.1, 1.0, _ss.emiss_wall, 0.01
            )
        with col3:
            _ss.h_out = st.number_input(
                "外表面对流系数 (W/m²K)", 1.0, 50.0, _ss.h_out, 1.0
            )

    # 智能验证
    st.markdown("#### 🔍 配置检查")
    params_dict = {"T_gas_C": _ss.T_gas_C, "T_env_C": _ss.T_env_C, "v_gas": _ss.v_gas}
    passed, msgs = validate_config(_ss.layers, params_dict)

    if passed and not msgs["warnings"] and not msgs["infos"]:
        st.success("✓ 配置正常")
    else:
        for err in msgs["errors"]:
            st.error(err)
        for warn in msgs["warnings"]:
            st.warning(warn)
        for info in msgs["infos"]:
            st.info(info)

# ============ 视图：衬层配置 ============
def _view_layers():
    st.header("🧱 衬层配置")

    # 编辑模式切换
    mode = st.radio("编辑模式", ["表格", "逐层"], horizontal=True)

    if mode == "表格":
        # 表格编辑（复用原 app.py 逻辑）
        st.info("💡 提示：此处需从原 app.py 复制表格编辑代码（st.data_editor）")
        # ponytail: 占位符，实际需从 app.py 迁移完整 data_editor 逻辑
    else:
        # 逐层编辑
        for i, layer in enumerate(_ss.layers):
            with st.expander(f"层 {i+1}: {layer['name']}", expanded=(i == 0)):
                col1, col2 = st.columns([2, 1])
                with col1:
                    layer["name"] = st.text_input(f"名称_{i}", layer["name"], key=f"name_{i}")
                with col2:
                    layer["thickness_mm"] = st.number_input(
                        f"厚度 (mm)_{i}", 5.0, 500.0, layer["thickness_mm"], 1.0, key=f"thick_{i}"
                    )

                st.markdown("**导热系数 k(T) = a + b·T + c·T²**")
                col_a, col_b, col_c = st.columns(3)
                a, b, c = layer["k_coef"]
                with col_a:
                    a = st.number_input(f"a_{i}", 0.01, 100.0, float(a), 0.01, key=f"a_{i}")
                with col_b:
                    b = st.number_input(f"b_{i}", 0.0, 0.01, float(b), 0.0001, key=f"b_{i}", format="%.5f")
                with col_c:
                    c = st.number_input(f"c_{i}", 0.0, 0.0001, float(c), 0.00001, key=f"c_{i}", format="%.7f")
                layer["k_coef"] = (a, b, c)

                if st.button(f"🗑️ 删除层 {i+1}", key=f"del_{i}"):
                    _ss.layers.pop(i)
                    st.rerun()

        if st.button("➕ 添加新层"):
            _ss.layers.append({
                "name": f"新层{len(_ss.layers)+1}",
                "thickness_mm": 50.0,
                "k_coef": (0.5, 0, 0),
                "uid": max(l["uid"] for l in _ss.layers) + 1 if _ss.layers else 1,
            })
            st.rerun()

# ============ 计算核心 ============
def _solve():
    """执行计算"""
    layers = [Layer(**{k: v for k, v in l.items() if k != "uid"}) for l in _ss.layers]
    params = KilnParams(
        T_gas=_ss.T_gas_C + 273.15,
        T_env=_ss.T_env_C + 273.15,
        v_gas=_ss.v_gas,
        L_char=_ss.L_char,
        emiss_gas=_ss.emiss_gas,
        emiss_wall=_ss.emiss_wall,
        h_out=_ss.h_out,
    )
    sol, x_mm, T_c = solve_wall(layers, params)
    return layers, params, sol, x_mm, T_c

# ============ 视图：计算与结果 ============
def _view_results():
    st.header("📊 计算结果")

    if st.button("🚀 开始计算", type="primary"):
        with st.spinner("计算中..."):
            try:
                result = _solve()
                _ss.last_result = result
                layers, params, sol, x_mm, T_c = result
                _add_to_history(layers, params, sol, x_mm, T_c)
                st.success("✅ 计算完成！")
            except Exception as e:
                st.error(f"❌ 计算失败：{e}")
                return

    if _ss.last_result is None:
        st.info("👈 请先点击「开始计算」")
        return

    layers, params, sol, x_mm, T_c = _ss.last_result

    # 关键指标卡片
    col1, col2, col3, col4 = st.columns(4)
    with col1:
        st.metric("内壁温度", f"{sol.T_w1 - 273.15:.1f} °C")
    with col2:
        color = "🟢" if sol.T_wN - 273.15 < 80 else "🟠" if sol.T_wN - 273.15 < 120 else "🔴"
        st.metric("外壁温度", f"{sol.T_wN - 273.15:.1f} °C", delta=color)
    with col3:
        st.metric("热损失", f"{sol.Qprime:.0f} W/m")
    with col4:
        st.metric("迭代次数", f"{sol.iterations}")

    # 温度曲线（复用原 app.py 的 Plotly 绘图）
    st.markdown("### 📈 温度分布曲线")
    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=x_mm, y=[t - 273.15 for t in T_c],
        mode="lines",
        line=dict(color="#A8C7FA", width=2),
        name="温度"
    ))
    fig.update_layout(
        xaxis_title="距离内壁 (mm)",
        yaxis_title="温度 (°C)",
        template="plotly_dark",
        height=400,
    )
    st.plotly_chart(fig, use_container_width=True)

    # ponytail: 收敛过程可视化待补充（从原 app.py 迁移）

# ============ 视图：历史对比 ============
def _view_history_compare():
    st.header("📜 历史对比")

    if not _ss.calc_history:
        st.info("暂无历史记录")
        return

    st.markdown(f"**共 {len(_ss.calc_history)} 条记录**")

    # 多选框
    selected_indices = []
    for i, rec in enumerate(_ss.calc_history):
        if st.checkbox(
            f"{rec.timestamp} | {rec.label}",
            key=f"hist_{i}"
        ):
            selected_indices.append(i)

    if len(selected_indices) < 2:
        st.warning("请至少选择 2 条记录进行对比")
        return

    # 温度曲线叠加
    st.markdown("### 📊 温度曲线对比")
    fig = go.Figure()
    for idx in selected_indices:
        rec = _ss.calc_history[idx]
        x_mm, T_c = rec.curve_data
        fig.add_trace(go.Scatter(
            x=x_mm, y=[t - 273.15 for t in T_c],
            mode="lines",
            name=rec.label
        ))
    fig.update_layout(
        xaxis_title="距离内壁 (mm)",
        yaxis_title="温度 (°C)",
        template="plotly_dark",
        height=500,
    )
    st.plotly_chart(fig, use_container_width=True)

    # 指标对比表
    st.markdown("### 📋 关键指标对比")
    compare_data = []
    for idx in selected_indices:
        rec = _ss.calc_history[idx]
        sol = rec.solution
        compare_data.append({
            "时间": rec.timestamp,
            "工况": rec.label,
            "内壁温度 (°C)": f"{sol['T_w1'] - 273.15:.1f}",
            "外壁温度 (°C)": f"{sol['T_wN'] - 273.15:.1f}",
            "热损失 (W/m)": f"{sol['Qprime']:.0f}",
        })
    st.table(compare_data)

# ============ 主程序 ============
def main():
    st.title("🔥 水泥窑传热计算（增强版）")

    # 顶部导航（使用 tabs 代替 segmented_control 以兼容旧版 Streamlit）
    tab1, tab2, tab3, tab4 = st.tabs(["参数", "衬层", "计算", "历史"])

    with tab1:
        _view_params()

    with tab2:
        _view_layers()

    with tab3:
        _view_results()

    with tab4:
        _view_history_compare()

    # 侧边栏：快捷信息
    with st.sidebar:
        st.markdown("### 当前配置")
        st.write(f"衬层数：{len(_ss.layers)}")
        st.write(f"总厚度：{sum(l['thickness_mm'] for l in _ss.layers):.0f} mm")
        st.write(f"历史记录：{len(_ss.calc_history)}/5")

        if st.button("🗑️ 清空历史"):
            _ss.calc_history = []
            st.rerun()

if __name__ == "__main__":
    main()
