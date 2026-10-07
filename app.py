# -*- coding: utf-8 -*-
"""水泥窑窑衬传热计算 —— Streamlit Web GUI（桌面 / 平板宽屏版）。

界面结构（v2 重构）：
- 主区三分区视图：衬层配置 / 计算结果 / 温度曲线。
  视图切换用 st.segmented_control 承载（Streamlit 的 st.tabs 无法在脚本中
  程序化切换选中项，而需求要求「计算完成后自动跳到计算结果」，
  因此用受 session_state 控制的 segmented_control 模拟 Tab 栏，
  外观经 CSS 调成标签页样式）。
- 侧边栏三个可折叠区块：工况参数 / 材料库 / 帮助（st.expander）。
- 衬层配置：默认「逐层编辑」紧凑多列布局（每层一行、操作按钮成组）；
  另提供可选的「表格编辑」模式（st.data_editor，支持批量增删改、
  从 Excel 粘贴），仅在安装了 pyarrow 时可用。
- 计算结果：彩色指标卡（外壁橙红 / 内壁橙 / 热损失蓝 / 发射率青）+
  分界面温度 + 详细工况 + 导出（CSV / 报告 / 复制）。
- 温度曲线：Plotly 交互曲线，悬停显示节点温度，各层分界面以竖线 +
  菱形节点标注，层间以交替底色带区分。

计算核心复用 kiln_ht/calc.py（与 APK、FastAPI 完全一致），本文件不包含
任何传热计算逻辑。

本地运行：
    pip install -r requirements.txt
    streamlit run app.py
Docker 运行：见 Dockerfile。
"""

from __future__ import annotations

import datetime
import io

import pandas as pd
import streamlit as st

from kiln_ht import (
    KilnParams,
    Layer,
    compute_temperature_curve,
    delete_user_material,
    get_material,
    load_user_materials,
    material_names,
    save_user_material,
    solve_wall,
)
from kiln_ht.export import build_report

# ============ 页面基础配置 ============
st.set_page_config(
    page_title="水泥窑窑衬传热计算",
    page_icon="🔥",
    layout="wide",
    initial_sidebar_state="expanded",
)

_ss = st.session_state

# ============ 主题色（深色工业风） ============
C_BG = "#121212"
C_CARD = "#1B1D20"
C_ELEV = "#25272A"
C_BORDER = "#3A3D42"
C_PRIMARY = "#1E88E5"
C_TEXT = "#ECEDEE"
C_DIM = "#9CA3AF"

# 指标卡配色：容器 key -> 强调色（同时用于左侧色条与数值文字）
METRIC_COLORS = {
    "mt_outer": "#FF7043",   # 外壁面温度 —— 橙红（安全关注点）
    "mt_inner": "#FFA726",   # 内壁面温度 —— 橙
    "mt_q": "#42A5F5",       # 总热损失 Q' —— 蓝
    "mt_eg": "#26C6DA",      # 烟气发射率 —— 青
}

# 常用典型水泥窑工况（仅工况参数，不含衬层材料——内置材料数据不可靠，
# 衬层结构由用户在「衬层配置」中自行维护）
PRESETS = {
    "预分解窑 · 烧成带（Φ4.8×74m）": dict(
        T_gas_C=1450.0, v_gas=3.5, L_char=4.8, L_kiln=74.0, P_total=1.01325,
        CO2=22.0, H2O=10.0, eps_wall=0.85,
        T_env_C=25.0, v_amb=2.0, eps_shell=0.85,
    ),
    "预分解窑 · 过渡带（Φ4.8×74m）": dict(
        T_gas_C=1150.0, v_gas=3.0, L_char=4.8, L_kiln=74.0, P_total=1.01325,
        CO2=20.0, H2O=9.0, eps_wall=0.85,
        T_env_C=25.0, v_amb=2.0, eps_shell=0.85,
    ),
    "中空窑 / 湿法窑（Φ3.2×60m）": dict(
        T_gas_C=1250.0, v_gas=2.5, L_char=3.2, L_kiln=60.0, P_total=1.01325,
        CO2=18.0, H2O=12.0, eps_wall=0.85,
        T_env_C=25.0, v_amb=2.0, eps_shell=0.85,
    ),
}

VIEWS = ["衬层配置", "计算结果", "温度曲线"]


# ============ 样式 ============
def _build_css() -> str:
    """生成全局 CSS：工业深色主题 + 指标卡配色 + 控件圆角与间距。"""
    metric_rules = "\n".join(
        f"""
.st-key-{k} div[data-testid="stMetricValue"] {{ color: {c} !important; }}
.st-key-{k} div[data-testid="stMetric"] {{
    background: {C_ELEV}; border: 1px solid {C_BORDER};
    border-left: 4px solid {c}; border-radius: 12px;
    padding: 14px 18px 10px 18px;
    box-shadow: 0 2px 10px rgba(0,0,0,.35);
}}
.st-key-{k} div[data-testid="stMetricLabel"] p {{ color: {C_DIM}; font-size: .85rem; }}
"""
        for k, c in METRIC_COLORS.items()
    )
    return f"""
<style>
:root {{ --kiln-border: {C_BORDER}; --kiln-primary: {C_PRIMARY}; }}

/* ---- 输入类控件：与背景形成清晰分割 ---- */
div[data-testid="stTextInput"] input,
div[data-testid="stNumberInput"] input,
div[data-testid="stSelectbox"] div[data-baseweb="select"] > div {{
    background-color: {C_ELEV} !important;
    border: 1px solid {C_BORDER} !important;
    border-radius: 8px !important;
    color: {C_TEXT} !important;
}}
div[data-testid="stTextInput"] input:focus,
div[data-testid="stNumberInput"] input:focus,
div[data-testid="stTextInput"]:focus-within,
div[data-testid="stNumberInput"]:focus-within {{
    border-color: {C_PRIMARY} !important;
    box-shadow: 0 0 0 1px {C_PRIMARY} !important;
}}

/* ---- 分区容器（st.container(border=True)）做成卡片 ---- */
div[data-testid="stVerticalBlockBorderWrapper"] {{
    background: {C_CARD};
    border: 1px solid {C_BORDER} !important;
    border-radius: 14px !important;
    box-shadow: 0 2px 12px rgba(0,0,0,.30);
}}

/* ---- 指标卡 ---- */
{metric_rules}

/* ---- 视图切换（模拟 Tab 栏）---- */
div[data-testid="stSegmentedControl"] button {{
    border-radius: 10px 10px 0 0 !important;
    padding: 10px 22px !important;
    font-size: 1rem !important;
}}
div[data-testid="stSegmentedControl"] button[aria-checked="true"] {{
    background: {C_ELEV} !important;
    border-bottom: 3px solid {C_PRIMARY} !important;
    font-weight: 600;
}}

/* ---- 衬层操作按钮紧凑化 ---- */
.st-key-layer_ops div[data-testid="stButton"] button {{
    padding: 2px 4px !important; min-height: 34px;
}}
div[data-testid="stButton"] button {{ border-radius: 9px !important; }}

/* ---- 侧边栏 ---- */
[data-testid="stSidebar"] {{ border-right: 1px solid {C_BORDER}; }}
[data-testid="stSidebar"] div[data-testid="stExpander"] {{
    border: 1px solid {C_BORDER}; border-radius: 12px;
    background: {C_CARD}; margin-bottom: 10px;
}}

/* ---- 下载 / 复制按钮排成一行 ---- */
.st-key-export_bar div[data-testid="stDownloadButton"] button,
.st-key-export_bar div[data-testid="stButton"] button {{
    width: 100%; height: 44px; font-weight: 600;
}}
</style>
"""


st.markdown(_build_css(), unsafe_allow_html=True)


# ============ 衬层状态 ============
def _init_state() -> None:
    """初始化 session_state（衬层列表、视图、自动计算开关等）。"""
    if "layers" not in _ss:
        _ss.layers = []
        _ss.layer_seq = 0
        for _ in range(4):
            _add_layer()
    _ss.setdefault("do_calc", False)          # 是否已经算过一次
    _ss.setdefault("auto_calc", False)        # 自动计算开关
    _ss.setdefault("layer_table_mode", False)  # 表格编辑模式
    _ss.setdefault("slim_mode", False)        # 精简模式（隐藏 b/c 列）
    _ss.setdefault("last_result", None)       # 最近一次计算结果


def _add_layer(name="", thickness_mm=50.0, material="自定义",
               k_coef=None, Rc=0.0) -> int:
    """新增一层，分配稳定 uid。

    uid 随衬层 dict 一起移动：上下移动只交换 list 中 dict 的顺序，
    而控件 key 使用 uid（layer_{uid}_name 等）而不是位置索引，
    保证 session_state 中的输入值始终跟着正确的衬层走，
    避免移动后各层输入值错乱。
    """
    _ss.layer_seq = _ss.get("layer_seq", 0) + 1
    _ss.layers.append({
        "uid": _ss.layer_seq,
        "name": name,
        "thickness_mm": float(thickness_mm),
        "material": material,
        "k_coef": list(k_coef) if k_coef else [1.0, 0.0, 0.0],
        "Rc": float(Rc),
    })
    return _ss.layer_seq


def _remove_layer(idx: int) -> None:
    if len(_ss.layers) > 1:
        _ss.layers.pop(idx)


def _move_layer(idx: int, direction: int) -> None:
    """direction: -1 上移（更靠内壁）, +1 下移。交换相邻两层顺序。"""
    j = idx + direction
    if 0 <= j < len(_ss.layers):
        _ss.layers[idx], _ss.layers[j] = _ss.layers[j], _ss.layers[idx]


def _apply_preset(name: str) -> None:
    """加载典型工况（仅写入工况参数，不动衬层结构）。"""
    p = PRESETS.get(name)
    if not p:
        return
    for key, val in p.items():
        _ss[key] = val          # 控件 key 与字典键一致，直接写 session_state


def _set_material(idx: int, mat_name: str) -> None:
    """把第 idx 层的材料切到 mat_name，并同步 k_coef 与陈旧控件 key。"""
    row = _ss.layers[idx]
    row["material"] = mat_name
    uid = row["uid"]
    if mat_name == "自定义":
        # 离开材料库材料时清掉陈旧 a/b/c session key，避免切回自定义被旧值覆盖
        for kk in (f"layer_{uid}_a", f"layer_{uid}_b", f"layer_{uid}_c"):
            _ss.pop(kk, None)
        return
    try:
        row["k_coef"] = list(get_material(mat_name)["k_coef"])
    except KeyError:
        pass


def _layers_signature() -> str:
    """衬层结构的短指纹，用作表格编辑器的 key，结构变化时强制重建编辑器。"""
    return "|".join(f"{r['uid']}" for r in _ss.layers)


# ============ 计算 ============
def _solve():
    """从界面状态组装参数并调用计算核心。

    返回 (layers, params, sol, x_mm, T_c)；参数非法时抛 ValueError。
    """
    layers = []
    for i, row in enumerate(_ss.layers):
        a, b, c = (list(row["k_coef"]) + [0.0, 0.0, 0.0])[:3]
        layers.append(Layer(
            name=str(row["name"]).strip() or f"层{i+1}",
            thickness=float(row["thickness_mm"]) / 1000.0,
            k_coef=(float(a), float(b), float(c)),
            Rc=float(row.get("Rc", 0.0) or 0.0),
        ))
    params = KilnParams(
        N_total=int(_ss.N_total),
        T_gas=float(_ss.T_gas_C) + 273.15,          # ℃ -> K
        v_gas=float(_ss.v_gas),
        L_char=float(_ss.L_char),
        L_kiln=float(_ss.L_kiln),
        P_total=float(_ss.P_total),
        CO2=float(_ss.CO2) / 100.0,                 # % -> 体积分数
        H2O=float(_ss.H2O) / 100.0,
        eps_wall=float(_ss.eps_wall),
        T_env=float(_ss.T_env_C) + 273.15,          # ℃ -> K
        v_amb=float(_ss.v_amb),
        eps_shell=float(_ss.eps_shell),
    )
    sol = solve_wall(layers, params)
    x_mm, T_c = compute_temperature_curve(layers, sol, n_points=params.N_total)
    return layers, params, sol, x_mm, T_c


def _interface_rows(layers, sol):
    """构造 [(分界面名称, 温度K)] 列表：内壁面 / 各层间 / 外壁面。"""
    rows = [("内壁面", sol.T_iface[0])]
    for i in range(1, len(sol.T_iface) - 1):
        rows.append((f"{layers[i-1].name} / {layers[i].name}", sol.T_iface[i]))
    rows.append(("外壁面", sol.T_iface[-1]))
    return rows


def _summary_text(layers, params, sol) -> str:
    """供「复制结果」使用的紧凑文本摘要。"""
    lines = [
        "水泥窑窑衬传热计算 — 结果摘要",
        f"时间：{datetime.datetime.now():%Y-%m-%d %H:%M}",
        "",
        f"烟气温度 {params.T_gas - 273.15:.1f} ℃ | 烟气流速 {params.v_gas:.2f} m/s | "
        f"窑内径 {params.L_char:.2f} m | 窑长 {params.L_kiln:.1f} m",
        f"环境温度 {params.T_env - 273.15:.1f} ℃ | 环境风速 {params.v_amb:.2f} m/s | "
        f"内壁发射率 {params.eps_wall:.2f}",
        "",
        "衬层结构（内壁 → 外壁）：",
    ]
    for l in layers:
        a, b, c = l.k_coef
        lines.append(f"  {l.name}：{l.thickness_mm:.1f} mm，"
                     f"k={a:g}+{b:g}T+{c:g}T²，Rc={l.Rc:g}")
    lines += [
        "",
        f"外壁面温度 {sol.T_wN - 273.15:.1f} ℃（温升 {sol.T_wN - params.T_env:.1f} ℃）",
        f"内壁面温度 {sol.T_w1 - 273.15:.1f} ℃",
        f"单位长度热损失 Q' {sol.Qprime:.1f} W/m",
        f"内壁总换热系数 h_in {sol.h_in:.1f} W/(m²·K)",
        f"外壁总换热系数 h_out {sol.h_out:.1f} W/(m²·K)",
        f"烟气发射率 eg {sol.eg:.3f}",
    ]
    return "\n".join(lines)


def _result_csv(layers, params, sol, x_mm, T_c) -> bytes:
    """把工况、衬层、结果与曲线整理成长表 CSV（UTF-8-SIG，Excel 可直接打开）。"""
    recs = []

    def add(cat, item, val, unit=""):
        recs.append({"类别": cat, "项目": item, "数值": val, "单位": unit})

    add("工况", "烟气温度", f"{params.T_gas - 273.15:.1f}", "℃")
    add("工况", "烟气流速", f"{params.v_gas:.3f}", "m/s")
    add("工况", "窑内径", f"{params.L_char:.3f}", "m")
    add("工况", "窑长", f"{params.L_kiln:.2f}", "m")
    add("工况", "窑内压力", f"{params.P_total:.5f}", "bar")
    add("工况", "CO2 含量", f"{params.CO2 * 100:.2f}", "%")
    add("工况", "H2O 含量", f"{params.H2O * 100:.2f}", "%")
    add("工况", "内壁发射率", f"{params.eps_wall:.3f}", "-")
    add("工况", "环境温度", f"{params.T_env - 273.15:.1f}", "℃")
    add("工况", "环境风速", f"{params.v_amb:.3f}", "m/s")
    add("工况", "外壳发射率", f"{params.eps_shell:.3f}", "-")

    for i, l in enumerate(layers):
        a, b, c = l.k_coef
        add("衬层", f"层{i + 1} 名称", l.name, "")
        add("衬层", f"层{i + 1} 厚度", f"{l.thickness_mm:.1f}", "mm")
        add("衬层", f"层{i + 1} a", f"{a:g}", "W/(m·K)")
        add("衬层", f"层{i + 1} b", f"{b:g}", "W/(m·K²)")
        add("衬层", f"层{i + 1} c", f"{c:g}", "W/(m·K³)")
        add("衬层", f"层{i + 1} 接触热阻 Rc", f"{l.Rc:g}", "m²·K/W")

    add("结果", "外壁面温度", f"{sol.T_wN - 273.15:.2f}", "℃")
    add("结果", "内壁面温度", f"{sol.T_w1 - 273.15:.2f}", "℃")
    add("结果", "单位长度热损失 Q'", f"{sol.Qprime:.2f}", "W/m")
    add("结果", "内壁热流密度 q_in", f"{sol.q_in:.2f}", "W/m²")
    add("结果", "外壁热流密度 q_out", f"{sol.q_out:.2f}", "W/m²")
    add("结果", "内壁总换热系数 h_in", f"{sol.h_in:.2f}", "W/(m²·K)")
    add("结果", "内壁对流 h_conv", f"{sol.h_conv_in:.2f}", "W/(m²·K)")
    add("结果", "内壁辐射 h_rad", f"{sol.h_rad_in:.2f}", "W/(m²·K)")
    add("结果", "外壁总换热系数 h_out", f"{sol.h_out:.2f}", "W/(m²·K)")
    add("结果", "外壁对流 h_conv", f"{sol.h_conv_out:.2f}", "W/(m²·K)")
    add("结果", "外壁辐射 h_rad", f"{sol.h_rad_out:.2f}", "W/(m²·K)")
    add("结果", "烟气发射率 eg", f"{sol.eg:.4f}", "-")
    add("结果", "耦合迭代步数", str(sol.iterations), "-")

    for name, tk in _interface_rows(layers, sol):
        add("分界面温度", name, f"{tk - 273.15:.2f}", "℃")

    for x, t in zip(x_mm, T_c):
        add("温度曲线", f"距内壁 {x:.2f} mm", f"{t:.2f}", "℃")

    return pd.DataFrame(recs).to_csv(index=False).encode("utf-8-sig")


# ============ 界面小组件 ============
def _tabbar() -> str:
    """主区视图切换栏，返回当前视图名。

    st.tabs 无法程序化切换选中项，故用受 session_state 控制的
    segmented_control 模拟，外观由 CSS 调成标签页样式。
    """
    if "main_view" not in _ss:
        _ss.main_view = VIEWS[0]
    seg = getattr(st, "segmented_control", None)
    if seg is None:                                   # 老版本 Streamlit 兜底
        view = st.radio("视图", VIEWS, horizontal=True,
                        key="main_view", label_visibility="collapsed")
        return view or VIEWS[0]
    view = seg("视图", VIEWS, key="main_view", label_visibility="collapsed")
    return view or VIEWS[0]


def _metric(label, value, container_key, delta=None, help_text=None):
    """彩色指标卡：靠 container(key=...) 生成的 .st-key-* 类名上色。"""
    with st.container(key=container_key):
        st.metric(label, value, delta=delta, help=help_text)


# ============ 侧边栏 ============
def _sidebar() -> bool:
    """渲染侧边栏三个可折叠区块，返回「本次是否要求计算」。"""
    with st.sidebar:
        st.markdown("### 🔥 水泥窑窑衬传热计算")
        clicked = st.button("🚀 开始计算", type="primary", width="stretch")
        st.toggle(
            "自动计算", key="auto_calc",
            help="开启后，任一参数变化即自动重新计算（Streamlit 在交互结束后"
                 "才触发重跑，天然带防抖，无需额外延迟处理）")
        st.caption("温度统一以 ℃ 输入，后台自动换算为 K。")
        st.divider()

        with st.expander("⚙️ 工况参数", expanded=True):
            st.selectbox(
                "常用工况一键加载", ["（不加载）"] + list(PRESETS),
                key="preset_choice",
                help="仅写入工况参数（温度 / 流速 / 几何 / 烟气成分），"
                     "不含衬层材料——衬层结构请自行维护。")
            if st.button("载入所选工况", width="stretch"):
                if _ss.preset_choice != "（不加载）":
                    _apply_preset(_ss.preset_choice)
                    st.toast(f"已载入：{_ss.preset_choice}", icon="✅")
                    st.rerun()

            st.markdown("**窑体与热工**")
            st.number_input("烟气温度 (°C)", value=1250.0, step=10.0, key="T_gas_C")
            st.number_input("烟气流速 (m/s)", value=3.0, min_value=0.01, step=0.1,
                            key="v_gas")
            st.number_input("窑内径 (m)", value=4.0, step=0.1, key="L_char")
            st.number_input("窑长 (m)", value=60.0, step=1.0, key="L_kiln")
            st.number_input("窑内压力 (bar)", value=1.01325, step=0.1, key="P_total")
            st.number_input("CO₂ 含量 (%)", value=20.0, min_value=0.0, max_value=100.0,
                            step=0.5, key="CO2")
            st.number_input("H₂O 含量 (%)", value=8.0, min_value=0.0, max_value=100.0,
                            step=0.5, key="H2O")
            st.number_input("内壁发射率", value=0.85, min_value=0.05, max_value=1.0,
                            step=0.01, key="eps_wall")

            st.markdown("**环境条件**")
            st.number_input("环境温度 (°C)", value=25.0, step=1.0, key="T_env_C")
            st.number_input("环境风速 (m/s)", value=2.0, min_value=0.0, step=0.1,
                            key="v_amb")
            st.number_input("外壳发射率", value=0.85, min_value=0.05, max_value=1.0,
                            step=0.01, key="eps_shell")

            st.slider("温度曲线取点数", min_value=50, max_value=1000, value=100,
                      step=50, key="N_total")

        with st.expander("📚 材料库", expanded=True):
            _material_library()

        with st.expander("❓ 帮助", expanded=False):
            st.markdown(
                """
**计算模型**：多层圆筒壁一维稳态传热，以单位长度热功率 Q′(W/m) 守恒求解。

- 内侧：管内强制对流（Gnielinski，含入口效应）+ 烟气辐射（Hottel/Leckner 灰气体）
- 外侧：水平圆柱自然对流（Churchill-Chu）与外掠强制对流（Zhukauskas）
  按组合相关式合成 + 外壳辐射
- 导热系数支持 k(T)=a+b·T+c·T²（T 为 ℃），层内取积分平均
- 内外壁温双侧耦合迭代求解，温度曲线用圆筒壁对数分布精确解

**输入约定**：温度 ℃、厚度 mm、压力 bar、CO₂/H₂O 为体积百分数。

**材料库**：内置材料数据不可靠已全部移除，请把常用耐火材料的
a/b/c 系数保存到材料库后复用。

**三种使用方式**（同一计算核心）：本 Web GUI（桌面/平板）、
Android APK、FastAPI（程序调用）。
                """)

        st.divider()
        st.caption(f"kiln_ht core · {datetime.date.today():%Y-%m-%d}")
    return clicked


def _material_library() -> None:
    """材料库区块：列出现有材料、保存新材料、删除。"""
    mats = load_user_materials()
    if mats:
        st.caption(f"已保存 {len(mats)} 种材料")
        for name, item in mats.items():
            a, b, c = item["k_coef"]
            c1, c2 = st.columns([4, 1])
            c1.markdown(f"**{name}**  \n<small>λ={a:g}+{b:g}T+{c:g}T²</small>",
                        unsafe_allow_html=True)
            if c2.button("🗑", key=f"mat_del_{name}", help=f"删除材料「{name}」"):
                delete_user_material(name)
                st.rerun()
    else:
        st.caption("材料库为空。可在衬层配置中填写 a/b/c 后保存。")

    with st.form("mat_add", clear_on_submit=True):
        st.markdown("**新增材料**")
        mname = st.text_input("材料名称", key="new_mat_name")
        mc1, mc2, mc3 = st.columns(3)
        ma = mc1.number_input("a", value=1.0, format="%.6g", key="new_mat_a")
        mb = mc2.number_input("b", value=0.0, format="%.6g", key="new_mat_b")
        mcc = mc3.number_input("c", value=0.0, format="%.6g", key="new_mat_c")
        if st.form_submit_button("保存到材料库", width="stretch"):
            try:
                save_user_material(mname, (ma, mb, mcc))
                st.success(f"已保存：{mname}")
            except ValueError as exc:
                st.error(f"保存失败：{exc}")


# ============ 视图 1：衬层配置 ============
def _layer_row_header(slim: bool) -> None:
    """衬层表头（与 _layer_row 的列宽保持一致）。"""
    widths = _column_widths(slim)
    labels = (["**层名称**", "**厚度 (mm)**", "**材料**", "**a**", "**b**", "**c**",
               "**Rc**", "**操作**"] if not slim else
              ["**层名称**", "**厚度 (mm)**", "**材料**", "**a**", "**Rc**", "**操作**"])
    cols = st.columns(widths)
    for col, text in zip(cols, labels):
        col.markdown(text)


def _column_widths(slim: bool) -> list:
    """衬层行的列宽比例（紧凑优先：名称与材料给足，数值列等宽）。"""
    if slim:
        return [1.9, 1.1, 2.2, 1.1, 1.0, 1.5]
    return [1.6, 1.0, 1.9, 0.95, 0.95, 0.95, 0.95, 1.5]


def _layer_row(idx: int, slim: bool) -> None:
    """渲染第 idx 层（每层一行），编辑结果直接写回 _ss.layers[idx]。"""
    row = _ss.layers[idx]
    uid = row["uid"]
    cols = st.columns(_column_widths(slim))
    is_custom = row.get("material", "自定义") == "自定义"

    row["name"] = cols[0].text_input(
        "层名称", value=row["name"], key=f"layer_{uid}_name",
        placeholder=f"层{idx + 1}", label_visibility="collapsed")
    row["thickness_mm"] = cols[1].number_input(
        "厚度", value=float(row["thickness_mm"]), min_value=0.1, step=1.0,
        key=f"layer_{uid}_thick", label_visibility="collapsed")

    sel = cols[2].selectbox(
        "材料", ["自定义"] + material_names(), index=0,
        key=f"layer_{uid}_material", label_visibility="collapsed")
    if sel != row.get("material", "自定义"):
        _set_material(idx, sel)
        st.rerun()

    if is_custom:
        row["k_coef"] = [
            cols[3].number_input("a", value=float(row["k_coef"][0]),
                                 key=f"layer_{uid}_a", format="%.6g",
                                 label_visibility="collapsed"),
            cols[4].number_input("b", value=float(row["k_coef"][1]),
                                 key=f"layer_{uid}_b", format="%.6g",
                                 label_visibility="collapsed"),
            cols[5].number_input("c", value=float(row["k_coef"][2]),
                                 key=f"layer_{uid}_c", format="%.6g",
                                 label_visibility="collapsed"),
        ]
        rc_col = cols[6]
    else:
        # 材料库材料：系数由材料库决定，此处只读展示
        a, b, c = row["k_coef"]
        cols[3].markdown(f"`{a:g}`")
        cols[4].markdown(f"`{b:g}`")
        cols[5].markdown(f"`{c:g}`")
        rc_col = cols[6]

    row["Rc"] = rc_col.number_input(
        "Rc", value=float(row.get("Rc", 0.0)), min_value=0.0, step=0.001,
        key=f"layer_{uid}_rc", label_visibility="collapsed")

    ops = cols[-1]
    with ops:
        if slim:
            _layer_ops(idx, uid)
        else:
            b1, b2, b3, b4 = st.columns([1, 1, 1, 1.4])
            with b1:
                _btn_up(idx, uid)
            with b2:
                _btn_down(idx, uid)
            with b3:
                _btn_del(idx, uid)
            with b4:
                save_name = str(row["name"]).strip() or f"层{idx + 1}"
                if st.button("💾", key=f"layer_{uid}_save",
                             disabled=not is_custom,
                             help=f"把当前 a/b/c 保存为材料「{save_name}」"):
                    try:
                        save_user_material(save_name, row["k_coef"])
                        st.toast(f"已保存到材料库：{save_name}", icon="✅")
                    except ValueError as exc:
                        st.error(f"保存失败：{exc}")


def _layer_ops(idx: int, uid: int) -> None:
    """精简模式下把 ⬆⬇🗑 收进一个弹出面板，行内只留一个按钮。"""
    b1, b2 = st.columns([1, 1])
    with b1:
        with st.popover("⋯", help="排序 / 删除"):
            if st.button("⬆ 上移", key=f"layer_{uid}_up", disabled=(idx == 0),
                         width="stretch"):
                _move_layer(idx, -1)
                st.rerun()
            if st.button("⬇ 下移", key=f"layer_{uid}_down",
                         disabled=(idx == len(_ss.layers) - 1), width="stretch"):
                _move_layer(idx, +1)
                st.rerun()
            if st.button("🗑 删除", key=f"layer_{uid}_del",
                         disabled=(len(_ss.layers) <= 1), width="stretch"):
                _remove_layer(idx)
                st.rerun()
    with b2:
        save_name = str(_ss.layers[idx]["name"]).strip() or f"层{idx + 1}"
        if st.button("💾", key=f"layer_{uid}_save",
                     disabled=_ss.layers[idx].get("material", "自定义") != "自定义",
                     help=f"把当前 a/b/c 保存为材料「{save_name}」"):
            try:
                save_user_material(save_name, _ss.layers[idx]["k_coef"])
                st.toast(f"已保存到材料库：{save_name}", icon="✅")
            except ValueError as exc:
                st.error(f"保存失败：{exc}")


def _btn_up(idx: int, uid: int) -> None:
    if st.button("⬆", key=f"layer_{uid}_up", disabled=(idx == 0), help="上移（更靠内壁）"):
        _move_layer(idx, -1)
        st.rerun()


def _btn_down(idx: int, uid: int) -> None:
    if st.button("⬇", key=f"layer_{uid}_down", disabled=(idx == len(_ss.layers) - 1),
                 help="下移（更靠外壁）"):
        _move_layer(idx, +1)
        st.rerun()


def _btn_del(idx: int, uid: int) -> None:
    if st.button("🗑", key=f"layer_{uid}_del", disabled=(len(_ss.layers) <= 1),
                 help="删除该层"):
        _remove_layer(idx)
        st.rerun()


def _layer_table_editor() -> None:
    """表格编辑模式：st.data_editor 批量增删改（需要 pyarrow）。"""
    try:
        import pyarrow  # noqa: F401 —— st.data_editor 的硬依赖
    except ImportError:
        st.info("当前环境未安装 pyarrow，表格编辑不可用，已使用逐层编辑模式。"
                "（执行 `pip install pyarrow` 后可用）")
        return

    df = pd.DataFrame([{
        "层序": i + 1,
        "层名称": r["name"],
        "厚度(mm)": float(r["thickness_mm"]),
        "材料": r.get("material", "自定义"),
        "a": float(r["k_coef"][0]),
        "b": float(r["k_coef"][1]),
        "c": float(r["k_coef"][2]),
        "Rc": float(r.get("Rc", 0.0)),
    } for i, r in enumerate(_ss.layers)])

    st.caption("可直接在表格中增删改；**层序 1 = 最内层**，改层序数字即可调整内外顺序。"
               "选择材料库材料时，a/b/c 以材料库为准。")
    edited = st.data_editor(
        df,
        num_rows="dynamic",
        width="stretch",
        hide_index=True,
        key=f"layer_editor_{_layers_signature()}",
        column_config={
            "层序": st.column_config.NumberColumn("层序", min_value=1, step=1, width="small"),
            "层名称": st.column_config.TextColumn("层名称", width="medium"),
            "厚度(mm)": st.column_config.NumberColumn("厚度(mm)", min_value=0.1,
                                                      step=1.0, format="%.1f"),
            "材料": st.column_config.SelectboxColumn(
                "材料", options=["自定义"] + material_names(), width="medium"),
            "a": st.column_config.NumberColumn("a", format="%.6g"),
            "b": st.column_config.NumberColumn("b", format="%.6g"),
            "c": st.column_config.NumberColumn("c", format="%.6g"),
            "Rc": st.column_config.NumberColumn("Rc", min_value=0.0, format="%.4g",
                                                help="层间接触热阻 m²·K/W"),
        },
    )

    if edited is None or edited.empty:
        return
    new_layers = [dict(r) for r in _ss.layers]
    rebuilt = []
    for pos, (_, r) in enumerate(edited.sort_values("层序").iterrows()):
        mat = r["材料"] if isinstance(r["材料"], str) and r["材料"] else "自定义"
        if mat != "自定义":
            try:
                k_coef = list(get_material(mat)["k_coef"])
            except KeyError:
                k_coef, mat = [float(r["a"]), float(r["b"]), float(r["c"])], "自定义"
        else:
            k_coef = [float(r["a"]), float(r["b"]), float(r["c"])]
        old = new_layers[pos] if pos < len(new_layers) else {}
        rebuilt.append({
            "uid": old.get("uid", _ss.layer_seq + pos + 1),
            "name": str(r["层名称"] or ""),
            "thickness_mm": float(r["厚度(mm)"]),
            "material": mat,
            "k_coef": k_coef,
            "Rc": float(r["Rc"] or 0.0),
        })
    _ss.layer_seq = max(_ss.layer_seq, max(x["uid"] for x in rebuilt))
    _ss.layers = rebuilt
    _ss.do_calc = _ss.do_calc or _ss.auto_calc


def _view_layers() -> None:
    """视图 1：衬层配置。"""
    with st.container(border=True):
        head, right = st.columns([3, 1])
        head.markdown("#### 🧱 衬层配置")
        head.caption("按 **内壁 → 外壁** 顺序排列。导热系数 k=a+b·T+c·T²（T 单位 ℃），"
                     "Rc 为层间接触热阻。")
        with right:
            st.toggle("精简模式", key="slim_mode",
                      help="隐藏 b/c 列，只保留常数导热系数 a")
            st.toggle("表格编辑", key="layer_table_mode",
                      help="用表格批量编辑衬层（支持从 Excel 粘贴），需要 pyarrow")

        if _ss.layer_table_mode:
            _layer_table_editor()
        else:
            _layer_row_header(_ss.slim_mode)
            for idx in range(len(_ss.layers)):
                _layer_row(idx, _ss.slim_mode)

            c1, c2 = st.columns([1, 4])
            with c1:
                if st.button("➕ 添加衬层", width="stretch"):
                    _add_layer()
                    st.rerun()
            with c2:
                total = sum(r["thickness_mm"] for r in _ss.layers)
                st.caption(f"共 {len(_ss.layers)} 层，总厚度 **{total:.1f} mm**"
                           f"（内径 {_ss.L_char:.3f} m → 外径 "
                           f"{_ss.L_char + total / 1000:.3f} m）")


# ============ 视图 2：计算结果 ============
def _view_results(res) -> None:
    """视图 2：指标卡 + 分界面温度 + 详细工况 + 导出。"""
    if res is None:
        st.info("请在左侧「工况参数」中配置参数，点击 **🚀 开始计算** 查看结果。"
                "（打开侧边栏的「自动计算」开关可在参数变化后自动重算）")
        return
    layers, params, sol, x_mm, T_c = res

    m1, m2, m3, m4 = st.columns(4)
    with m1:
        _metric("🌡 外壁面温度", f"{sol.T_wN - 273.15:.1f} °C", "mt_outer",
                delta=f"高于环境 {sol.T_wN - params.T_env:.1f} °C",
                help_text="窑壳外表面温度，是散热损失与安全防护的关键指标")
    with m2:
        _metric("🔥 内壁面温度", f"{sol.T_w1 - 273.15:.1f} °C", "mt_inner",
                help_text="衬里热面温度，用于校核耐火材料使用温度")
    with m3:
        _metric("💧 总热损失 Q'", f"{sol.Qprime:.1f} W/m", "mt_q",
                help_text="单位窑长散热功率")
    with m4:
        _metric("☁ 烟气发射率", f"{sol.eg:.3f}", "mt_eg",
                help_text="Hottel/Leckner 灰气体模型计算的烟气发射率")

    st.write("")
    left, right = st.columns([1, 1])

    with left:
        with st.container(border=True):
            st.markdown("#### 🌡 各分界面温度")
            rows = _interface_rows(layers, sol)
            md = ["| 分界面 | 温度 (℃) | 温度 (K) |", "|---|---:|---:|"]
            for name, tk in rows:
                md.append(f"| {name} | **{tk - 273.15:.1f}** | {tk:.1f} |")
            st.markdown("\n".join(md))

    with right:
        with st.container(border=True):
            st.markdown("#### 📋 详细工况结果")
            md = ["| 指标 | 数值 |", "|---|---:|"]
            for label, value in [
                ("单位长度热功率 Q'", f"{sol.Qprime:.1f} W/m"),
                ("内壁热流密度 q_in", f"{sol.q_in:.1f} W/m²"),
                ("外壁热流密度 q_out", f"{sol.q_out:.1f} W/m²"),
                ("内壁总换热系数 h_in", f"{sol.h_in:.1f} W/m²·K"),
                ("　内壁对流 h_conv", f"{sol.h_conv_in:.1f} W/m²·K"),
                ("　内壁辐射 h_rad", f"{sol.h_rad_in:.1f} W/m²·K"),
                ("外壁总换热系数 h_out", f"{sol.h_out:.1f} W/m²·K"),
                ("　外壁对流 h_conv", f"{sol.h_conv_out:.1f} W/m²·K"),
                ("　外壁辐射 h_rad", f"{sol.h_rad_out:.1f} W/m²·K"),
                ("各层积分平均导热系数", " / ".join(f"{k:.3g}" for k in sol.k_avg)),
                ("耦合迭代步数", str(sol.iterations)),
            ]:
                md.append(f"| {label} | {value} |")
            st.markdown("\n".join(md))

    with st.container(border=True, key="export_bar"):
        st.markdown("#### 📤 导出与分享")
        stamp = datetime.datetime.now().strftime("%Y%m%d_%H%M")
        e1, e2, e3 = st.columns(3)
        with e1:
            st.download_button(
                "⬇ 导出 CSV",
                data=_result_csv(layers, params, sol, x_mm, T_c),
                file_name=f"kiln_result_{stamp}.csv", mime="text/csv",
                width="stretch")
        with e2:
            st.download_button(
                "⬇ 导出报告 (.txt)",
                data=build_report(layers, params, sol, x_mm, T_c).encode("utf-8"),
                file_name=f"kiln_report_{stamp}.txt", mime="text/plain",
                width="stretch")
        with e3:
            with st.popover("📋 复制结果", width="stretch"):
                st.caption("点右上角图标复制以下文本")
                st.code(_summary_text(layers, params, sol), language=None)


# ============ 视图 3：温度曲线 ============
def _build_figure(layers, sol, x_mm, T_c):
    """构造温度分布 Plotly 图：层带 + 分界面标注 + 悬停节点温度。"""
    import plotly.graph_objects as go

    positions = [0.0]
    for l in layers:
        positions.append(positions[-1] + l.thickness_mm)

    fig = go.Figure()
    # 各层底色带（交替）+ 层名标注
    for i, l in enumerate(layers):
        fig.add_vrect(
            x0=positions[i], x1=positions[i + 1],
            fillcolor=C_PRIMARY if i % 2 == 0 else "#26C6DA",
            opacity=0.07, line_width=0, layer="below")
        fig.add_annotation(
            x=(positions[i] + positions[i + 1]) / 2, y=1.0, yref="paper",
            text=f"{l.name}<br><span style='font-size:10px'>{l.thickness_mm:.0f}mm</span>",
            showarrow=False, font=dict(size=11, color=C_DIM), yanchor="bottom")

    fig.add_trace(go.Scatter(
        x=x_mm, y=T_c, mode="lines+markers",
        line=dict(color=C_PRIMARY, width=3),
        marker=dict(size=5, color="#FF9800"),
        name="温度分布",
        hovertemplate="距内壁 %{x:.1f} mm<br>温度 %{y:.1f} ℃<extra></extra>",
    ))

    # 各分界面：竖线 + 菱形节点 + 温度标签
    for p, (name, tk) in zip(positions, _interface_rows(layers, sol)):
        fig.add_vline(x=p, line_dash="dot", line_color=C_DIM, opacity=0.55)
        fig.add_trace(go.Scatter(
            x=[p], y=[tk - 273.15], mode="markers+text",
            marker=dict(size=10, color="#EF5350", symbol="diamond",
                        line=dict(width=1, color="#fff")),
            text=[f"{tk - 273.15:.0f}℃"], textposition="top center",
            textfont=dict(color=C_TEXT, size=11),
            showlegend=False, name=name,
            hovertemplate=f"{name}<br>%{{y:.1f}} ℃<extra></extra>",
        ))

    fig.update_layout(
        title=dict(text="壁厚方向温度分布（℃）", font=dict(size=16)),
        xaxis=dict(title="距内壁距离 (mm)", gridcolor="#3A3D42", zeroline=False),
        yaxis=dict(title="温度 (℃)", gridcolor="#3A3D42", zeroline=False),
        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
        font=dict(color=C_TEXT),
        hovermode="x unified",
        margin=dict(l=10, r=10, t=70, b=10),
        height=540,
        legend=dict(orientation="h", yanchor="bottom", y=1.02, x=0),
    )
    return fig


def _view_curve(res) -> None:
    """视图 3：温度曲线 + 曲线数据。"""
    if res is None:
        st.info("尚无计算结果。请先点击 **🚀 开始计算**。")
        return
    layers, params, sol, x_mm, T_c = res

    with st.container(border=True):
        try:
            st.plotly_chart(_build_figure(layers, sol, x_mm, T_c), width="stretch")
        except ImportError:
            st.warning("未安装 plotly，无法绘制曲线（pip install plotly）")
        st.caption("悬停可查看任意位置温度；虚线与菱形为各层分界面，"
                   "上方底色带对应各衬层。")

    with st.expander("查看曲线数据表"):
        st.dataframe(
            pd.DataFrame({"距内壁 (mm)": x_mm, "温度 (℃)": T_c}),
            width="stretch", height=320, hide_index=True)


# ============ 主流程 ============
_init_state()

clicked = _sidebar()

if clicked:
    _ss.do_calc = True
    _ss.main_view = "计算结果"        # 首次计算后自动切到结果视图

st.title("水泥窑窑衬传热计算")
st.caption("多层圆筒壁一维稳态传热 · 计算核心与 Android APK / FastAPI 完全一致")

view = _tabbar()

result = None
need_calc = _ss.do_calc or _ss.auto_calc
if need_calc:
    if _ss.auto_calc and not _ss.do_calc:
        _ss.main_view = "计算结果"   # 自动计算也切到结果视图
    try:
        with st.spinner("正在求解壁温耦合迭代…"):
            result = _solve()
        _ss.last_result = result
    except Exception as exc:  # noqa: BLE001 —— UI 层统一捕获展示
        st.error(f"计算失败：{exc}")
        st.stop()
elif _ss.last_result is not None:
    result = _ss.last_result

st.write("")

if view == "衬层配置":
    _view_layers()
elif view == "计算结果":
    _view_results(result)
else:
    _view_curve(result)
