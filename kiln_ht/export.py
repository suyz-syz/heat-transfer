# -*- coding: utf-8 -*-
"""计算结果导出 / 分享（零第三方依赖，可在 Kivy / Android / 桌面运行）。

导出结果为纯文本 UTF-8 报告（.txt），内容包含：
- 工况参数
- 各层结构（名称 / 厚度 / k(T) 系数 / 接触热阻）
- 关键结果（Q'、q、h、界面温度）
- 温度分布曲线（x_mm 与 T_c）

Android 上优先用 plyer.share 分享（可选择保存 / 发送到其他应用）；
失败或非 Android 平台则直接写本地文件。
"""

import os
from typing import List, Optional, Tuple


def build_report(
    layers: List,
    params,
    sol,
    x_mm: Optional[List[float]] = None,
    T_c: Optional[List[float]] = None,
) -> str:
    """生成完整结果的纯文本报告。"""
    lines = []
    lines.append("=" * 56)
    lines.append("水泥窑窑衬传热计算 — 结果报告")
    lines.append("=" * 56)

    lines.append("")
    lines.append("【工况参数】")
    lines.append(f"  烟气温度      : {params.T_gas - 273.15:.1f} ℃")
    lines.append(f"  烟气流速      : {params.v_gas:.2f} m/s")
    lines.append(f"  窑内径        : {params.L_char:.2f} m")
    lines.append(f"  窑长          : {params.L_kiln:.1f} m")
    lines.append(f"  窑内压力      : {params.P_total:.4f} bar")
    lines.append(f"  CO2 含量      : {params.CO2 * 100:.1f} %")
    lines.append(f"  H2O 含量      : {params.H2O * 100:.1f} %")
    lines.append(f"  内壁发射率    : {params.eps_wall:.2f}")
    lines.append(f"  环境温度      : {params.T_env - 273.15:.1f} ℃")
    lines.append(f"  环境风速      : {params.v_amb:.2f} m/s")
    lines.append(f"  外壳发射率    : {params.eps_shell:.2f}")

    lines.append("")
    lines.append("【衬层结构】")
    lines.append(f"  {'名称':<10}{'厚度(mm)':>10}{'a':>10}{'b':>12}{'c':>12}{'Rc(m²K/W)':>12}")
    for l in layers:
        a, b, c = l.k_coef
        lines.append(
            f"  {l.name:<10}{l.thickness_mm:>10.1f}{a:>10.4g}{b:>12.4g}{c:>12.4g}{l.Rc:>12.4g}"
        )

    lines.append("")
    lines.append("【关键结果】")
    lines.append(f"  单位长度热功率 Q' : {sol.Qprime:.1f} W/m")
    lines.append(f"  内壁热流密度 q_in : {sol.q_in:.1f} W/m²")
    lines.append(f"  外壁热流密度 q_out: {sol.q_out:.1f} W/m²")
    lines.append(f"  内壁总换热 h_in   : {sol.h_in:.1f} W/m²·K")
    lines.append(f"    内壁对流 h_conv : {sol.h_conv_in:.1f} W/m²·K")
    lines.append(f"    内壁辐射 h_rad  : {sol.h_rad_in:.1f} W/m²·K")
    lines.append(f"  外壁总换热 h_out  : {sol.h_out:.1f} W/m²·K")
    lines.append(f"    外壁对流 h_conv : {sol.h_conv_out:.1f} W/m²·K")
    lines.append(f"    外壁辐射 h_rad  : {sol.h_rad_out:.1f} W/m²·K")
    lines.append(f"  烟气发射率 eg     : {sol.eg:.3f}")
    lines.append(f"  内壁面温度        : {sol.T_w1 - 273.15:.1f} ℃")
    lines.append(f"  外壁面温度        : {sol.T_wN - 273.15:.1f} ℃")
    lines.append(f"  耦合迭代步数      : {sol.iterations}")

    lines.append("")
    lines.append("【各分界面温度】")
    rows = [("内壁面", sol.T_iface[0])]
    for i in range(1, len(sol.T_iface) - 1):
        rows.append((f"{layers[i-1].name} / {layers[i].name}", sol.T_iface[i]))
    rows.append(("外壁面", sol.T_iface[-1]))
    for name, tk in rows:
        lines.append(f"  {name:<24}{tk - 273.15:>8.1f} ℃")

    if x_mm and T_c:
        lines.append("")
        lines.append("【温度分布曲线】")
        lines.append(f"  {'距内壁(mm)':>12}{'温度(℃)':>12}")
        for x, t in zip(x_mm, T_c):
            lines.append(f"  {x:>12.2f}{t:>12.2f}")
        lines.append(f"  （共 {len(x_mm)} 个点）")

    lines.append("")
    lines.append("=" * 56)
    return "\n".join(lines)


def export_result(
    layers: List,
    params,
    sol,
    x_mm: Optional[List[float]] = None,
    T_c: Optional[List[float]] = None,
    filename: str = "kiln_heat_result.txt",
) -> Tuple[bool, str]:
    """导出结果。

    - Android：优先尝试 plyer.share 分享；失败则写入应用用户目录。
    - 其他平台：写入当前目录（或指定路径）。

    返回 (是否成功, 说明/路径)。
    """
    report = build_report(layers, params, sol, x_mm, T_c)

    # Android：尝试 plyer 分享
    try:
        from kivy.utils import platform
        if platform == "android":
            try:
                from plyer import share
                share.share(text=report, title="水泥窑窑衬传热计算结果")
                return True, "已调起系统分享"
            except Exception:  # noqa: BLE001 —— plyer 分享失败时回退文件写入
                pass
    except Exception:  # noqa: BLE001
        pass

    # 写入本地文件
    try:
        from kivy.app import App
        app = App.get_running_app()
        if app is not None:
            out_dir = app.user_data_dir
        else:
            out_dir = os.path.dirname(os.path.abspath(filename)) or "."
        os.makedirs(out_dir, exist_ok=True)
        path = os.path.join(out_dir, os.path.basename(filename))
    except Exception:  # noqa: BLE001
        path = os.path.abspath(filename)
        os.makedirs(os.path.dirname(path), exist_ok=True)

    with open(path, "w", encoding="utf-8") as f:
        f.write(report)
    return True, f"已保存到 {path}"
