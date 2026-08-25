# -*- coding: utf-8 -*-
"""
Kivy 跨平台移动端界面入口（Android / Windows / macOS / Linux）。

本地运行（桌面调试）：
    python main.py

Android 打包（需先安装 buildozer，详见 buildozer.spec）：
    buildozer android debug            # 生成 bin/*.apk
    buildozer android release          # 签名发布包

说明：温度曲线使用纯 Kivy Canvas 绘制（不依赖 matplotlib），
保证在 Android 上构建与运行轻量稳定。
"""

from kiln_ht import Layer, KilnParams, solve_wall, compute_temperature_curve

import os

import kivy

kivy.require("2.1.0")

from kivy.app import App
from kivy.core.text import LabelBase
from kivy.graphics import Color, Line
from kivy.metrics import dp, sp
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.button import Button
from kivy.uix.gridlayout import GridLayout
from kivy.uix.label import Label
from kivy.uix.scrollview import ScrollView
from kivy.uix.spinner import Spinner
from kivy.uix.textinput import TextInput
from kivy.uix.widget import Widget
from kivy.utils import platform


def _setup_cjk_font():
    """在 Android 上启用系统自带的中文字体（Google Noto CJK），不打包字体文件。

    Android 默认的 Roboto 字体不含 CJK 字形，中文会显示为"方框+叉"。
    Android 系统自带 Google 的 Noto Sans CJK 字体，覆盖中/日/韩字符，
    将其注册为 Kivy 默认字体 'Roboto'，所有控件（Label/Button 等）即可正常显示中文。
    非 Android 平台（桌面调试）保持默认字体，不做修改。
    """
    if platform != "android":
        return
    # 常见 Android 系统 CJK 字体路径（按优先级尝试）
    candidates = [
        "/system/fonts/NotoSansCJK-Regular.ttc",   # Android 7.0+（API 24）
        "/system/fonts/NotoSansSC-Regular.otf",    # 部分设备提供 SC 单语言版
        "/system/fonts/DroidSansFallback.ttf",     # 旧设备兜底
    ]
    for path in candidates:
        if os.path.exists(path):
            LabelBase.register(name="Roboto", fn_regular=path)
            print(f"[字体] 已启用系统 CJK 字体: {path}")
            return
    print("[字体] 未找到系统 CJK 字体，中文可能无法显示")


_setup_cjk_font()


# ============ 输入控件 ============
class FloatInput(TextInput):
    """仅允许输入合法浮点数的文本框。

    使用 Kivy 内置 input_filter='float'：它允许 '.' / '-' / 'e' 等部分输入
    （例如先敲小数点 '.' 再补数字），避免自定义过滤器收到单字符 '.' 时
    因 float('.') 抛 ValueError 而把小数点丢弃的问题。
    """

    def __init__(self, **kwargs):
        kwargs.setdefault("multiline", False)
        kwargs.setdefault("halign", "center")
        super().__init__(**kwargs)
        self.input_filter = "float"


class IntInput(TextInput):
    """仅允许输入整数的文本框。"""

    def __init__(self, **kwargs):
        kwargs.setdefault("multiline", False)
        kwargs.setdefault("halign", "center")
        super().__init__(**kwargs)
        self.input_filter = "int"


# ============ 温度曲线控件（纯 Canvas 绘制） ============
class CurveWidget(Widget):
    """轻量温度曲线绘制组件，无需 matplotlib。"""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._x = []
        self._T = []
        self.bind(pos=self.redraw, size=self.redraw)

    def set_data(self, x_mm, T_c):
        self._x = list(x_mm)
        self._T = list(T_c)
        self.redraw()

    def redraw(self, *_args):
        self.canvas.clear()
        if len(self._x) < 2 or self.width <= dp(20) or self.height <= dp(20):
            return
        x0, x1 = self._x[0], self._x[-1]
        t0, t1 = min(self._T), max(self._T)
        span_x = (x1 - x0) or 1.0
        span_t = (t1 - t0) or 1.0
        pad = dp(12)
        with self.canvas:
            # 坐标轴
            Color(0.55, 0.55, 0.62, 1.0)
            Line(points=[pad, pad, self.width - pad, pad], width=dp(1))
            Line(points=[pad, pad, pad, self.height - pad], width=dp(1))
            # 温度曲线
            Color(0.83, 0.25, 0.23, 1.0)
            pts = []
            for xi, ti in zip(self._x, self._T):
                px = pad + (xi - x0) / span_x * (self.width - 2 * pad)
                py = pad + (ti - t0) / span_t * (self.height - 2 * pad)
                pts.extend((px, py))
            Line(points=pts, width=dp(2))


# ============ 主界面 ============
class KilnApp(BoxLayout):
    """主界面：滚动输入区 + 温度曲线 + 结果展示。"""

    def __init__(self, **kwargs):
        super().__init__(orientation="vertical", spacing=dp(6), padding=dp(8), **kwargs)
        self._layer_rows = []      # 每项: (name_entry, thick_entry, k_entry)
        self._build_input_area()
        self._build_curve()
        self._build_result()

    # ---------- 输入区 ----------
    def _build_input_area(self):
        scroll = ScrollView(size_hint=(1, 0.52))
        panel = BoxLayout(orientation="vertical", spacing=dp(4), size_hint_y=None)
        panel.bind(minimum_height=panel.setter("height"))
        scroll.add_widget(panel)

        # 层数选择
        row = BoxLayout(size_hint_y=None, height=dp(42))
        row.add_widget(Label(text="衬里层数", bold=True))
        self.layer_spinner = Spinner(
            text="4",
            values=[str(i) for i in range(1, 11)],
            size_hint=(0.5, 1),
        )
        self.layer_spinner.bind(text=lambda *_args: self._rebuild_layers())
        row.add_widget(self.layer_spinner)
        panel.add_widget(row)

        # 层参数表格（名称 / 厚度 / 导热系数）
        self.layer_grid = GridLayout(cols=4, spacing=dp(4), size_hint_y=None)
        self.layer_grid.bind(minimum_height=self.layer_grid.setter("height"))
        panel.add_widget(self.layer_grid)

        # 工况参数
        self.param_fields = {}
        param_specs = [
            ("N_total",    "温度曲线取点数", "100",     IntInput),
            ("T_gas",      "烟气温度(℃)",   "1250",    FloatInput),
            ("v_gas",      "烟气流速(m/s)", "3",       FloatInput),
            ("L_char",     "窑内径(m)",     "4",       FloatInput),
            ("L_kiln",     "窑长(m)",       "60",      FloatInput),
            ("P_total",    "窑内压力(bar)", "1.01325", FloatInput),
            ("CO2",        "CO2含量(%)",    "20",      FloatInput),
            ("H2O",        "H2O含量(%)",    "8",       FloatInput),
            ("eps_wall",   "内壁发射率",    "0.85",    FloatInput),
            ("T_env",      "环境温度(℃)",   "25",      FloatInput),
            ("v_amb",      "环境风速(m/s)", "2",       FloatInput),
            ("eps_shell",  "外壳发射率",    "0.85",    FloatInput),
        ]
        for key, label, default, cls in param_specs:
            r = BoxLayout(size_hint_y=None, height=dp(40))
            r.add_widget(Label(text=label, size_hint=(0.5, 1)))
            inp = cls(text=default, size_hint=(0.5, 1))
            self.param_fields[key] = inp
            r.add_widget(inp)
            panel.add_widget(r)

        # 计算按钮
        btn = Button(
            text="计 算",
            size_hint_y=None,
            height=dp(52),
            font_size=sp(18),
            background_color=(0.17, 0.52, 0.87, 1),
        )
        btn.bind(on_press=lambda *_args: self._on_calc())
        panel.add_widget(btn)

        self._rebuild_layers()
        self.add_widget(scroll)

    def _rebuild_layers(self):
        self.layer_grid.clear_widgets()
        self._layer_rows.clear()
        n = int(self.layer_spinner.text)
        for t in ("层", "名称", "厚度mm", "λ W/m·K"):
            self.layer_grid.add_widget(
                Label(text=t, bold=True, size_hint_y=None, height=dp(28)))
        for i in range(n):
            idx = Label(text=str(i + 1), size_hint_y=None, height=dp(36))
            name = TextInput(text=f"层{i+1}", size_hint_y=None, height=dp(36))
            thick = FloatInput(text="50", size_hint_y=None, height=dp(36))
            k = FloatInput(text="1.0", size_hint_y=None, height=dp(36))
            self._layer_rows.append((name, thick, k))
            self.layer_grid.add_widget(idx)
            self.layer_grid.add_widget(name)
            self.layer_grid.add_widget(thick)
            self.layer_grid.add_widget(k)
        self.layer_grid.height = dp(28) + n * dp(40)

    # ---------- 温度曲线 ----------
    def _build_curve(self):
        box = BoxLayout(orientation="vertical", size_hint=(1, 0.28))
        box.add_widget(Label(
            text="温度分布（内壁 → 外壁）",
            size_hint_y=None, height=dp(22), font_size=sp(13)))
        self.curve = CurveWidget()
        box.add_widget(self.curve)
        self.add_widget(box)

    # ---------- 结果 ----------
    def _build_result(self):
        self.result = Label(
            text="输入参数后点击「计 算」",
            size_hint=(1, 0.2),
            halign="left", valign="top",
            font_size=sp(14),
            padding=(dp(10), dp(6)),
        )
        self.result.bind(
            size=lambda *_args: setattr(self.result, "text_size", self.result.size))
        self.add_widget(self.result)

    # ---------- 计算 ----------
    def _on_calc(self):
        try:
            layers = []
            for i, (name, thick, k) in enumerate(self._layer_rows):
                layers.append(Layer(
                    name=name.text.strip() or f"层{i+1}",
                    thickness=float(thick.text) / 1000.0,
                    k=float(k.text),
                ))
            p = self.param_fields
            params = KilnParams(
                N_total=int(p["N_total"].text),
                T_gas=float(p["T_gas"].text) + 273.15,
                v_gas=float(p["v_gas"].text),
                L_char=float(p["L_char"].text),
                L_kiln=float(p["L_kiln"].text),
                P_total=float(p["P_total"].text),
                CO2=float(p["CO2"].text) / 100.0,
                H2O=float(p["H2O"].text) / 100.0,
                eps_wall=float(p["eps_wall"].text),
                T_env=float(p["T_env"].text) + 273.15,
                v_amb=float(p["v_amb"].text),
                eps_shell=float(p["eps_shell"].text),
            )
            sol = solve_wall(layers, params)
            x_mm, T_c = compute_temperature_curve(layers, sol, n_points=params.N_total)
            self.curve.set_data(x_mm, T_c)
            self.result.text = self._format_result(layers, sol)
        except Exception as exc:  # noqa: BLE001 —— UI 层统一捕获并展示错误
            self.result.text = f"[错误] {exc}"

    @staticmethod
    def _format_result(layers, sol):
        lines = [
            f"烟气发射率: {sol.eg:.3f}",
            f"内壁面温度: {sol.T_w1 - 273.15:.1f} ℃",
            f"外壁面温度: {sol.T_wN - 273.15:.1f} ℃",
            "",
            "各层分界面温度(℃):",
        ]
        for i in range(1, len(layers) + 1):
            lines.append(f"  {layers[i-1].name}: {sol.T_iface[i] - 273.15:.1f}")
        lines += [
            "",
            f"单位长度热功率 Q': {sol.Qprime:.1f} W/m",
            f"内壁热流密度 q_in: {sol.q_in:.1f} W/m²",
            f"外壁热流密度 q_out: {sol.q_out:.1f} W/m²",
            "",
            f"内壁换热: 对流{sol.h_conv_in:.1f} + 辐射{sol.h_rad_in:.1f} = {sol.h_in:.1f} W/m²·K",
            f"外壁换热: 对流{sol.h_conv_out:.1f} + 辐射{sol.h_rad_out:.1f} = {sol.h_out:.1f} W/m²·K",
            f"迭代收敛于第 {sol.iterations} 步",
        ]
        return "\n".join(lines)


class HeatTransferApp(App):
    """应用入口。"""

    def build(self):
        self.title = "水泥窑窑衬传热计算"
        return KilnApp()


if __name__ == "__main__":
    HeatTransferApp().run()
