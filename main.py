# -*- coding: utf-8 -*-
"""
Kivy 跨平台移动端界面入口（Android / Windows / macOS / Linux）。

Material Design 风格：
- 底部导航栏双 Tab：参数设置（Inputs）/ 计算结果（Results）
- 深色主题：#121212 背景、#25272A 卡片、#1E88E5 主色、#FF9800 强调色
- 输入页三张卡片分组（窑体几何 / 热工与烟气 / 环境条件），圆角聚焦高亮输入框
  （单位后缀内置于输入框右侧），底部固定高亮「开始计算」按钮，计算成功后平滑切换至结果页
- 结果页：顶部大字号指标高亮卡（外壁面温度 / 内壁面温度 / 烟气发射率）、
  各层界面温度表、详细工况结果、填满剩余空间的大图温度曲线
  （深色主题网格 + 圆点节点标记，纯 Kivy Canvas 绘制，不依赖 matplotlib）

布局要点（适配移动端高 DPI 与动态屏幕尺寸）：
- 所有 width / height / padding / spacing 均使用 dp()，font_size 使用 sp()
- 滚动容器内的卡片必须 size_hint_y=None 并绑定 minimum_height，
  否则会被 Kivy 压扁成均分高度导致控件重叠

本地运行（桌面调试）：
    python main.py

Android 打包（需先安装 buildozer，详见 buildozer.spec）：
    buildozer android debug            # 生成 bin/*.apk
    buildozer android release          # 签名发布包
"""

from kiln_ht import (
    Layer,
    KilnParams,
    load_user_materials,
    material_names,
    save_user_material,
    solve_wall,
    compute_temperature_curve,
)
from kiln_ht.export import build_report, export_result

import os

import kivy

kivy.require("2.3.0")

from kivy.app import App
from kivy.clock import Clock
from kivy.core.text import Label as CoreLabel
from kivy.core.text import LabelBase
from kivy.graphics import Color, Ellipse, Line, Rectangle, RoundedRectangle
from kivy.metrics import dp, sp
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.button import Button
from kivy.uix.checkbox import CheckBox
from kivy.uix.label import Label
from kivy.uix.screenmanager import FadeTransition, Screen, ScreenManager
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


# ============ Material Design 深色主题 ============
BG          = (0.071, 0.071, 0.071, 1.0)     # #121212  页面背景
CARD        = (0.145, 0.153, 0.165, 1.0)     # #25272A  卡片背景
CARD_ELEV   = (0.176, 0.192, 0.212, 1.0)     # 输入框 / 抬升控件底色
CARD_BORDER = (0.271, 0.302, 0.353, 1.0)     # 卡片 / 控件描边
PRIMARY     = (0.118, 0.533, 0.898, 1.0)     # #1E88E5  主色（深天蓝）
PRIMARY_DK  = (0.082, 0.396, 0.753, 1.0)     # #1565C0  主色按压缩影
ACCENT      = (1.0, 0.596, 0.0, 1.0)         # #FF9800  强调色（工业橙）
TEXT        = (0.925, 0.929, 0.933, 1.0)     # #ECEDEE  主文字
TEXT_DIM    = (0.612, 0.639, 0.686, 1.0)     # #9CA3AF  次要文字
GRID        = (0.227, 0.239, 0.259, 1.0)     # #3A3D42  图表网格线
AXIS        = (0.353, 0.373, 0.416, 1.0)     # 坐标轴
DANGER      = (0.937, 0.325, 0.314, 1.0)     # #EF5350  错误提示


# ============ 工具 ============
def auto_height(widget):
    """使控件在纵向滚动容器内按自身内容自适应高度。

    Kivy 中若子控件保持默认 size_hint_y=1，ScrollView 的 content
    （size_hint_y=None + minimum_height）会把所有卡片均分高度，
    导致固定高度的内部控件溢出卡片边界而互相重叠。
    此函数将子控件设为 size_hint_y=None 并把高度绑定到 minimum_height，
    是 Kivy 滚动列表的标准做法。
    """
    widget.size_hint_y = None
    widget.bind(minimum_height=widget.setter("height"))
    return widget


# ============ 基础控件 ============
class FloatInput(TextInput):
    """支持科学计数法的浮点输入框。

    使用自定义输入过滤器，允许输入数字、小数点、负号、以及 'e'/'E'
    科学计数法标记（含其后可选的 +/- 号），例如 1.2e-6、4.5E-4。
    最终数值合法性在 collect_params 中由 float() 校验。
    """

    def __init__(self, **kwargs):
        kwargs.setdefault("multiline", False)
        super().__init__(**kwargs)
        self.input_filter = _sci_float_filter


def _sci_float_filter(substring, from_undo=False):
    """自定义浮点输入过滤器：支持科学计数法。

    Kivy 内置的 input_filter='float' 使用正则 ``^-?[0-9]*\\.?[0-9]*$``，
    不允许输入 'e' 字符，导致 1.2e-6 这样的科学计数法无法输入。
    此过滤器放行数字、小数点、负号与 e/E 等字符，拦截其余非法字符。

    返回过滤后的字符串；返回空字符串表示拒绝本次输入。
    """
    allowed = set("0123456789.-eE+")
    return "".join(ch for ch in substring if ch in allowed)


class IntInput(TextInput):
    """仅允许输入整数的文本框。"""

    def __init__(self, **kwargs):
        kwargs.setdefault("multiline", False)
        super().__init__(**kwargs)
        self.input_filter = "int"


class MdLabel(Label):
    """主题化文本标签：深色主题、左对齐、垂直居中、自动换行。"""

    def __init__(self, **kwargs):
        kwargs.setdefault("color", TEXT)
        kwargs.setdefault("font_size", sp(14))
        kwargs.setdefault("halign", "left")
        kwargs.setdefault("valign", "middle")
        super().__init__(**kwargs)
        self.bind(size=self._sync_text_size)

    def _sync_text_size(self, *_args):
        self.text_size = (self.width, self.height)


def make_title(text, **kwargs):
    """卡片标题标签。"""
    kwargs.setdefault("bold", True)
    kwargs.setdefault("font_size", sp(15))
    kwargs.setdefault("size_hint_y", None)
    kwargs.setdefault("height", dp(26))
    return MdLabel(text=text, **kwargs)


class MDCard(BoxLayout):
    """Material 卡片：圆角 + 微描边（canvas.before 绘制）。"""

    def __init__(self, radius=dp(14), bg=CARD, border=CARD_BORDER, **kwargs):
        kwargs.setdefault("orientation", "vertical")
        kwargs.setdefault("spacing", dp(10))
        kwargs.setdefault("padding", [dp(16), dp(14), dp(16), dp(14)])
        super().__init__(**kwargs)
        self._radius = radius
        with self.canvas.before:
            self._bg_col = Color(*bg)
            self._bg_rect = RoundedRectangle(
                pos=self.pos, size=self.size,
                radius=[(radius, radius)] * 4)
            self._brd_col = Color(*border)
            self._brd_line = Line(rounded_rectangle=self._rr(), width=dp(1))
        self.bind(pos=self._sync_rect, size=self._sync_rect)

    def _rr(self):
        r = self._radius
        return (self.x, self.y, self.width, self.height, r)

    def _sync_rect(self, *_args):
        self._bg_rect.pos = self.pos
        self._bg_rect.size = self.size
        self._brd_line.rounded_rectangle = self._rr()


class UnitInput(BoxLayout):
    """圆角输入框：聚焦时主色高亮边框，单位后缀内置在输入框右侧。"""

    def __init__(self, unit="", default="", input_cls=FloatInput,
                 halign="right", height=dp(46), **kwargs):
        super().__init__(orientation="horizontal", spacing=dp(2),
                         size_hint_y=None, height=height, **kwargs)
        self._radius = dp(10)
        with self.canvas.before:
            self._bg_col = Color(*CARD_ELEV)
            self._bg_rect = RoundedRectangle(
                pos=self.pos, size=self.size,
                radius=[(self._radius, self._radius)] * 4)
            self._brd_col = Color(*CARD_BORDER)
            self._brd_line = Line(rounded_rectangle=self._rr(), width=dp(1))
        self.bind(pos=self._sync_rect, size=self._sync_rect)

        self.textinput = input_cls(
            text=default, halign=halign,
            font_size=sp(15), foreground_color=TEXT,
            cursor_color=PRIMARY, cursor_width=dp(2),
            background_normal="", background_active="",
            background_color=(0, 0, 0, 0),
            padding=[dp(12), dp(8), dp(8), dp(8)])
        self.textinput.bind(focus=self._on_focus)
        self.add_widget(self.textinput)

        if unit:
            w = dp(max(28, 10 + len(unit) * 8))
            u = MdLabel(text=unit, color=TEXT_DIM, font_size=sp(12),
                        size_hint=(None, 1), width=w, halign="left")
            self.add_widget(u)

    @property
    def text(self):
        return self.textinput.text

    @text.setter
    def text(self, value):
        self.textinput.text = value

    def _rr(self):
        r = self._radius
        return (self.x, self.y, self.width, self.height, r)

    def _sync_rect(self, *_args):
        self._bg_rect.pos = self.pos
        self._bg_rect.size = self.size
        self._brd_line.rounded_rectangle = self._rr()

    def _on_focus(self, _inp, focused):
        if focused:
            self._brd_col.rgba = (*PRIMARY[:3], 1.0)
            self._bg_col.rgba = (*PRIMARY[:3], 0.10)
        else:
            self._brd_col.rgba = (*CARD_BORDER[:3], 1.0)
            self._bg_col.rgba = CARD_ELEV


class FieldRow(BoxLayout):
    """输入页一行：左侧标签 + 右侧圆角单位输入框。"""

    def __init__(self, label, unit="", default="", input_cls=FloatInput, **kwargs):
        super().__init__(orientation="horizontal", spacing=dp(10),
                         size_hint_y=None, height=dp(50), **kwargs)
        self.label = MdLabel(text=label, font_size=sp(14),
                             size_hint=(None, 1), width=dp(112))
        self.field = UnitInput(unit=unit, default=default, input_cls=input_cls)
        self.add_widget(self.label)
        self.add_widget(self.field)

    @property
    def text(self):
        return self.field.text

    @text.setter
    def text(self, value):
        self.field.text = value


class AccentButton(Button):
    """主色实心大按钮（Material 圆角），按压时加深。"""

    def __init__(self, text, bg=PRIMARY, radius=dp(14), **kwargs):
        kwargs.setdefault("font_size", sp(17))
        kwargs.setdefault("bold", True)
        kwargs.setdefault("color", (1.0, 1.0, 1.0, 1.0))
        super().__init__(text=text, background_normal="", background_down="",
                         background_color=(0, 0, 0, 0), **kwargs)
        self._radius = radius
        with self.canvas.before:
            self._bg_col = Color(*bg)
            self._bg_rect = RoundedRectangle(
                pos=self.pos, size=self.size,
                radius=[(radius, radius)] * 4)
        self.bind(pos=self._sync_rect, size=self._sync_rect)
        self.bind(on_press=self._pressed, on_release=self._released)

    def _sync_rect(self, *_args):
        self._bg_rect.pos = self.pos
        self._bg_rect.size = self.size

    def _pressed(self, *_args):
        self._bg_col.rgba = (*PRIMARY_DK[:3], 1.0)

    def _released(self, *_args):
        self._bg_col.rgba = (*PRIMARY[:3], 1.0)


class CircleButton(Button):
    """圆形按钮（步进器用）。"""

    def __init__(self, text, on_click, diameter=dp(40), **kwargs):
        kwargs.setdefault("font_size", sp(22))
        kwargs.setdefault("bold", True)
        kwargs.setdefault("color", TEXT)
        super().__init__(text=text, background_normal="", background_down="",
                         background_color=(0, 0, 0, 0),
                         size_hint=(None, None), size=(diameter, diameter), **kwargs)
        self._d = diameter
        self._on_click = on_click
        with self.canvas.before:
            self._fill = Color(*CARD_ELEV)
            self._disc = Ellipse(pos=self.pos, size=self.size)
            self._ring = Color(*CARD_BORDER)
            self._ring_line = Line(circle=(0.0, 0.0, 1.0), width=dp(1.5))
        self.bind(pos=self._sync, size=self._sync)
        self.bind(on_press=self._pressed, on_release=self._released)

    def _sync(self, *_args):
        self._disc.pos = self.pos
        self._disc.size = self.size
        self._ring_line.circle = (self.center_x, self.center_y, self._d / 2 - dp(1))

    def _pressed(self, *_args):
        self._fill.rgba = (*PRIMARY[:3], 0.35)

    def _released(self, *_args):
        self._fill.rgba = CARD_ELEV
        self._on_click()


class Stepper(BoxLayout):
    """「− / 值 / +」数字步进器（Material 风格，替代原生 Spinner）。"""

    def __init__(self, value=4, vmin=1, vmax=10, on_change=None, **kwargs):
        super().__init__(orientation="horizontal", spacing=dp(10),
                         size_hint=(None, None), size=(dp(148), dp(46)), **kwargs)
        self._vmin, self._vmax = vmin, vmax
        self._value = value
        self._on_change = on_change
        self.label = MdLabel(text=str(value), bold=True, font_size=sp(17),
                             halign="center")
        self.add_widget(CircleButton("-", self._dec))
        self.add_widget(self.label)
        self.add_widget(CircleButton("+", self._inc))

    @property
    def value(self):
        return self._value

    def _dec(self):
        self._set(self._value - 1)

    def _inc(self):
        self._set(self._value + 1)

    def _set(self, v):
        v = max(self._vmin, min(self._vmax, v))
        if v != self._value:
            self._value = v
            self.label.text = str(v)
            if self._on_change:
                self._on_change(v)


class StatRow(BoxLayout):
    """一行「标签 / 数值」展示（界面温度表、详细结果）。"""

    def __init__(self, label, value, **kwargs):
        super().__init__(orientation="horizontal", spacing=dp(10),
                         size_hint_y=None, height=dp(34), **kwargs)
        self.add_widget(MdLabel(text=label, color=TEXT_DIM, font_size=sp(13),
                                size_hint_x=0.62))
        self.add_widget(MdLabel(text=value, color=TEXT, font_size=sp(13),
                                bold=True, halign="right", size_hint_x=0.38))


# ============ 温度曲线控件（纯 Canvas 绘制） ============
class CurveWidget(Widget):
    """深色主题温度曲线：网格 + 坐标轴 + 圆点节点标记 + 刻度。

    颜色取自主题常量（可随浅/深主题切换），不依赖 matplotlib。
    控件填满所在卡片剩余空间，尺寸变化时自动重绘，适配不同屏幕。
    """

    MAX_MARKERS = 26          # 节点圆点标记的最大数量（自动抽稀）

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
        if len(self._x) < 2 or self.width <= dp(40) or self.height <= dp(40):
            return
        pad_l, pad_r = dp(46), dp(14)      # 左侧留白给温度刻度
        pad_b, pad_t = dp(30), dp(12)      # 下方留白给距离刻度
        x0, x1 = self._x[0], self._x[-1]
        t0, t1 = min(self._T), max(self._T)
        span_x = (x1 - x0) or 1.0
        span_t = (t1 - t0) or 1.0
        # 上下留 5% 余量，避免曲线贴边
        t_lo = t0 - 0.05 * span_t
        t_hi = t1 + 0.05 * span_t
        span_t2 = (t_hi - t_lo) or 1.0
        iw = self.width - pad_l - pad_r
        ih = self.height - pad_b - pad_t

        def px(xi):
            return pad_l + (xi - x0) / span_x * iw

        def py(ti):
            return pad_b + (ti - t_lo) / span_t2 * ih

        with self.canvas:
            # 网格线
            Color(*GRID)
            for k in range(1, 5):
                gx = pad_l + iw * k / 5
                Line(points=[gx, pad_b, gx, pad_b + ih], width=dp(1))
                gy = pad_b + ih * k / 5
                Line(points=[pad_l, gy, pad_l + iw, gy], width=dp(1))
            # 坐标轴
            Color(*AXIS)
            Line(points=[pad_l, pad_b, pad_l + iw, pad_b], width=dp(1))
            Line(points=[pad_l, pad_b, pad_l, pad_b + ih], width=dp(1))
            # 温度曲线
            Color(*PRIMARY)
            pts = []
            for xi, ti in zip(self._x, self._T):
                pts.extend((px(xi), py(ti)))
            Line(points=pts, width=dp(2))
            # 节点圆点标记（抽稀）：主色外圈 + 白色内芯
            stride = max(1, len(self._T) // self.MAX_MARKERS)
            for i in range(0, len(self._T), stride):
                cx, cy = px(self._x[i]), py(self._T[i])
                Color(*PRIMARY)
                Line(circle=(cx, cy, dp(3)), width=dp(1.6))
                Color(1.0, 1.0, 1.0, 1.0)
                Line(circle=(cx, cy, dp(1.2)), width=dp(1))
            # 刻度文字（Y：温度上下限/中点；X：距内壁 0 与总厚度）
            self._draw_text(f"{t_hi:.0f}", pad_l - dp(6), py(t_hi), TEXT_DIM, anchor_right=True)
            self._draw_text(f"{(t_lo + t_hi) / 2:.0f}", pad_l - dp(6), py((t_lo + t_hi) / 2), TEXT_DIM, anchor_right=True)
            self._draw_text(f"{t_lo:.0f}", pad_l - dp(6), py(t_lo), TEXT_DIM, anchor_right=True)
            self._draw_text(f"{x0:.0f}", pad_l, pad_b - dp(18), TEXT_DIM)
            self._draw_text(f"{x1:.0f}", pad_l + iw, pad_b - dp(18), TEXT_DIM, anchor_right=True)

    def _draw_text(self, text, x, y, color, font_size=sp(10), anchor_right=False):
        """将文字渲染为纹理后绘制到画布；字体渲染失败时静默跳过。"""
        try:
            cl = CoreLabel(text=text, font_size=font_size, color=color)
            cl.refresh()
        except Exception:  # noqa: BLE001 —— 字体缺失时不影响曲线绘制
            return
        tex = cl.texture
        tx = x - tex.width if anchor_right else x
        ty = y - tex.height / 2.0
        with self.canvas:
            Color(1.0, 1.0, 1.0, 1.0)
            Rectangle(texture=tex, pos=(tx, ty), size=tex.size)


# ============ 结果页指标高亮卡 ============
class MetricCard(MDCard):
    """大字号指标高亮卡：顶部强调条 + 标题 / 大数值 / 单位。"""

    def __init__(self, title, unit="", accent=ACCENT, **kwargs):
        kwargs.setdefault("padding", [dp(10), dp(14), dp(10), dp(10)])
        kwargs.setdefault("radius", dp(12))
        kwargs.setdefault("spacing", dp(2))
        super().__init__(**kwargs)
        with self.canvas.before:
            Color(*accent)
            self._strip = RoundedRectangle(pos=(0.0, 0.0), size=(0.0, dp(3)),
                                           radius=[(dp(1.5), dp(1.5))] * 4)
        self.bind(pos=self._place_strip, size=self._place_strip)
        self.title = MdLabel(text=title, color=TEXT_DIM, font_size=sp(12),
                             halign="center", size_hint_y=None, height=dp(20))
        self.value = MdLabel(text="--", color=TEXT, bold=True, font_size=sp(24),
                             halign="center", size_hint_y=None, height=dp(40))
        self.unit_label = MdLabel(text=unit, color=TEXT_DIM, font_size=sp(11),
                                  halign="center", size_hint_y=None, height=dp(16))
        self.add_widget(self.title)
        self.add_widget(self.value)
        self.add_widget(self.unit_label)

    def _place_strip(self, *_args):
        w = min(self.width * 0.4, dp(60))
        self._strip.pos = (self.x + (self.width - w) / 2, self.y + self.height - dp(3))
        self._strip.size = (w, dp(3))

    def set_value(self, text):
        self.value.text = text


# ============ 底部导航栏 ============
class NavItem(Button):
    """底部导航单项：顶部主色指示条 + 文字，点击回调 index。"""

    def __init__(self, text, index, on_select, **kwargs):
        kwargs.setdefault("font_size", sp(13))
        super().__init__(text=text, color=TEXT_DIM, background_normal="",
                         background_down="", background_color=(0, 0, 0, 0), **kwargs)
        self.index = index
        self._cb = on_select
        self._active = False
        with self.canvas.before:
            self._ind_col = Color(0.0, 0.0, 0.0, 0.0)
            self._ind = RoundedRectangle(pos=(0.0, 0.0), size=(0.0, dp(3)),
                                         radius=[(dp(1.5), dp(1.5))] * 4)
        self.bind(pos=self._place, size=self._place)
        self.bind(on_press=self._pressed)

    def _place(self, *_args):
        self._ind.pos = (self.x, self.y + self.height - dp(3))
        self._ind.size = (self.width, dp(3))

    def _pressed(self, *_args):
        self._cb(self.index)

    def set_active(self, active):
        self._active = active
        self.color = TEXT if active else TEXT_DIM
        self.bold = active
        self._ind_col.rgba = PRIMARY if active else (0.0, 0.0, 0.0, 0.0)


class BottomNavBar(BoxLayout):
    """Material 底部导航栏（两个主页面：参数设置 / 计算结果）。"""

    NAV = [("参数设置", "inputs"), ("计算结果", "results")]

    def __init__(self, on_select, **kwargs):
        super().__init__(orientation="horizontal", spacing=0,
                         size_hint_y=None, height=dp(60), **kwargs)
        with self.canvas.before:
            Color(*CARD)
            self._bg = Rectangle(pos=self.pos, size=self.size)
            Color(*CARD_BORDER)
            self._top_line = Line(points=[0.0, 0.0, 0.0, 0.0], width=dp(1))
        self.bind(pos=self._sync, size=self._sync)
        self._items = []
        for i, (text, _name) in enumerate(self.NAV):
            item = NavItem(text, i, on_select)
            self._items.append(item)
            self.add_widget(item)
        self._items[0].set_active(True)

    def _sync(self, *_args):
        self._bg.pos = self.pos
        self._bg.size = self.size
        self._top_line.points = [self.x, self.y + self.height,
                                 self.x + self.width, self.y + self.height]

    def set_index(self, index):
        for i, item in enumerate(self._items):
            item.set_active(i == index)


# ============ 参数设置页（Tab 1） ============
class InputScreen(Screen):
    """输入页：三张卡片分组（ScrollView 滚动）+ 固定底部「开始计算」大按钮。"""

    def __init__(self, on_calc, **kwargs):
        super().__init__(**kwargs)
        self.name = "inputs"
        self.on_calc = on_calc
        self._layer_rows = []      # 每项: (name, thick, mat, k, rc) —— UnitInput/Spinner
        self._fields = {}          # key -> FieldRow
        self._build()

    def _build(self):
        root = BoxLayout(orientation="vertical")

        # 外层 ScrollView：内部所有卡片均 auto_height（size_hint_y=None + minimum_height）
        scroll = ScrollView(bar_width=dp(4), bar_color=GRID,
                            bar_inactive_color=GRID)
        content = BoxLayout(orientation="vertical", spacing=dp(12),
                            padding=[dp(14), dp(14), dp(14), dp(14)],
                            size_hint_y=None)
        content.bind(minimum_height=content.setter("height"))
        scroll.add_widget(content)
        root.add_widget(scroll)

        # ---- 卡片 1：窑体几何 ----
        geom = auto_height(MDCard())
        geom.add_widget(make_title("窑体几何"))
        self._add_field(geom, "L_char", "窑内径", "m", "4")
        self._add_field(geom, "L_kiln", "窑长", "m", "60")
        row = BoxLayout(size_hint_y=None, height=dp(46), spacing=dp(10))
        row.add_widget(MdLabel(text="衬里层数", size_hint=(None, 1), width=dp(112)))
        self.stepper = Stepper(value=4, on_change=lambda *_a: self._rebuild_layers())
        row.add_widget(self.stepper)
        geom.add_widget(row)
        self.layer_grid = BoxLayout(orientation="vertical", spacing=dp(6),
                                    size_hint_y=None)
        self.layer_grid.bind(minimum_height=self.layer_grid.setter("height"))
        geom.add_widget(self.layer_grid)
        content.add_widget(geom)
        self._rebuild_layers()

        # ---- 卡片 2：热工与烟气 ----
        thermal = auto_height(MDCard())
        thermal.add_widget(make_title("热工与烟气"))
        self._add_field(thermal, "T_gas", "烟气温度", "°C", "1250")
        self._add_field(thermal, "v_gas", "烟气流速", "m/s", "3")
        self._add_field(thermal, "P_total", "窑内压力", "bar", "1.01325")
        self._add_field(thermal, "CO2", "CO2 含量", "%", "20")
        self._add_field(thermal, "H2O", "H2O 含量", "%", "8")
        self._add_field(thermal, "eps_wall", "内壁发射率", "", "0.85")
        self._add_field(thermal, "N_total", "温度曲线取点数", "点", "100",
                        input_cls=IntInput)
        content.add_widget(thermal)

        # ---- 卡片 3：环境条件 ----
        env = auto_height(MDCard())
        env.add_widget(make_title("环境条件"))
        self._add_field(env, "T_env", "环境温度", "°C", "25")
        self._add_field(env, "v_amb", "环境风速", "m/s", "2")
        self._add_field(env, "eps_shell", "外壳发射率", "", "0.85")
        content.add_widget(env)

        # ---- 底部操作区（固定在页面底部，不随卡片滚动，避免遮挡输入框） ----
        bottom = BoxLayout(orientation="vertical", spacing=dp(6),
                           size_hint_y=None, height=dp(110),
                           padding=[dp(14), dp(6), dp(14), dp(12)])
        self.error_label = MdLabel(text="", color=DANGER, font_size=sp(13),
                                   halign="center", size_hint_y=None, height=dp(26))
        bottom.add_widget(self.error_label)
        btn = AccentButton(text="开始计算", size_hint_y=None, height=dp(54))
        btn.bind(on_press=lambda *_args: self._on_calc())
        bottom.add_widget(btn)
        root.add_widget(bottom)

        self.add_widget(root)

    def _add_field(self, card, key, label, unit, default, input_cls=FloatInput):
        row = FieldRow(label, unit=unit, default=default, input_cls=input_cls)
        self._fields[key] = row
        card.add_widget(row)
        return row

    def _rebuild_layers(self):
        """按层数重建层参数模块（每个材料层一个独立卡片模块）。

        每个模块内分两行（适配手机竖屏，行间用分隔线隔开）：
          第一行：层名称 / 厚度(mm) / 材料 / 温度相关(勾选)
          第二行：导热系数 a / b / c / 接触热阻 Rc
        勾选「温度相关」后启用 b/c 输入（支持科学计数法）；
        材料下拉「自定义」+ 用户材料库，选中材料即用其 k_coef；
        「保存」按钮将当前 a/b/c 保存到用户材料库。
        模块之间用独立卡片分隔。
        """
        self.layer_grid.clear_widgets()
        self._layer_rows.clear()
        n = self.stepper.value
        user_mats = material_names()
        for i in range(n):
            # ---- 每个材料层一个独立卡片模块 ----
            # 关键：必须 auto_height（size_hint_y=None + 绑定 minimum_height→height）。
            # 否则卡片默认 size_hint_y=1，而 layer_grid（size_hint_y=None）的
            # minimum_height 只统计 size_hint_y=None 的子节点，导致卡片高度塌缩为 0，
            # 内部固定高度的行（row1/row2 等）全部溢出互相重叠（导热系数输入区重叠即由此引起）。
            card = auto_height(MDCard(spacing=dp(8), padding=[dp(12), dp(10), dp(12), dp(10)],
                                      radius=dp(12)))

            # 第一行：层名称 / 厚度 / 材料 / 温度相关
            # 固定宽仅给 层名称/厚度/勾选框，其余全部留给「材料」下拉，避免被挤成细条
            row1 = BoxLayout(spacing=dp(6), size_hint_y=None, height=dp(44))
            name = UnitInput(input_cls=TextInput, unit="", default=f"层{i+1}",
                             halign="left", height=dp(42))
            name.textinput.multiline = False    # 普通文本输入，支持中文层名
            name.size_hint_x = None
            name.width = dp(72)
            thick = UnitInput(unit="mm", default="50", height=dp(42))
            thick.size_hint_x = None
            thick.width = dp(70)
            mat = Spinner(text="自定义", values=["自定义"] + user_mats,
                          size_hint_x=1, font_size=sp(12),
                          background_color=CARD_ELEV)
            temp_cb = CheckBox(size_hint_x=None, width=dp(36), color=PRIMARY)
            row1.add_widget(name)
            row1.add_widget(thick)
            row1.add_widget(mat)
            row1.add_widget(temp_cb)
            card.add_widget(row1)

            # 第一行下方小注：材料 / 温度相关（勾选后启用 b、c）
            hint1 = BoxLayout(spacing=dp(6), size_hint_y=None, height=dp(18))
            hint1.add_widget(Widget(size_hint_x=None, width=dp(72)))
            hint1.add_widget(Widget(size_hint_x=None, width=dp(70)))
            hint1.add_widget(MdLabel(text="材料", color=TEXT_DIM, font_size=sp(10)))
            hint1.add_widget(MdLabel(text="温度相关", color=TEXT_DIM, font_size=sp(10),
                                     size_hint_x=None, width=dp(40)))
            card.add_widget(hint1)

            # 行间分隔线：清晰区分「第一行 / 第二行」
            divider = BoxLayout(size_hint_y=None, height=dp(1))
            with divider.canvas.before:
                Color(*CARD_BORDER)
                divider._line_rect = Rectangle(pos=divider.pos, size=divider.size)
            divider.bind(pos=lambda *_a, d=divider: setattr(d._line_rect, "pos", d.pos),
                         size=lambda *_a, d=divider: setattr(d._line_rect, "size", d.size))
            card.add_widget(divider)

            # 第二行：导热系数 a / b / c + 接触热阻 Rc
            row2 = BoxLayout(spacing=dp(6), size_hint_y=None, height=dp(44))
            a_in = UnitInput(unit="a", default="1.0", height=dp(42))
            a_in.size_hint_x = 1
            b = UnitInput(unit="b", default="0.0", height=dp(42))
            b.size_hint_x = 1
            c = UnitInput(unit="c", default="0.0", height=dp(42))
            c.size_hint_x = 1
            rc = UnitInput(unit="", default="0.0", height=dp(42))
            rc.size_hint_x = None
            rc.width = dp(64)
            row2.add_widget(a_in)
            row2.add_widget(b)
            row2.add_widget(c)
            row2.add_widget(rc)
            card.add_widget(row2)

            # 第二行下方小注：a/b/c 组上方为弹性「导热系数」公式说明；
            # Rc 输入框内不显示单位后缀，其说明「接触热阻 Rc」作为固定宽度
            # （与 rc 输入框等宽 dp(64)）标签，右端与输入框精确对齐。
            hint2 = BoxLayout(spacing=dp(6), size_hint_y=None, height=dp(18))
            hint2.add_widget(MdLabel(text="导热系数 k=a+bT+cT²",
                                     color=TEXT_DIM, font_size=sp(10),
                                     size_hint_x=1))
            hint2.add_widget(MdLabel(text="接触热阻 Rc", color=TEXT_DIM,
                                     font_size=sp(10), halign="left",
                                     size_hint_x=None, width=dp(64)))
            card.add_widget(hint2)

            # 保存到材料库按钮（仅自定义时可用）
            save_btn = Button(text="保存到材料库", font_size=sp(13), bold=True,
                              color=TEXT, size_hint_y=None, height=dp(36),
                              background_normal="", background_down="",
                              background_color=CARD_ELEV)
            save_btn.bind(on_release=lambda *_a, row_=i: self._save_material(row_))
            card.add_widget(save_btn)

            self.layer_grid.add_widget(card)
            self._layer_rows.append((name, thick, mat, a_in, b, c, rc, temp_cb,
                                     save_btn))

            # 勾选温度相关时启用 b/c
            def _toggle(*_a, b_=b, c_=c, cb_=temp_cb):
                b_.disabled = not cb_.active
                c_.disabled = not cb_.active
                # 未勾选温度相关时 b/c 显示为置灰但仍保留输入值
                b_.opacity = 1.0
                c_.opacity = 1.0
            temp_cb.bind(active=_toggle)
            _toggle()

            # 选择材料时自动填充 a/b/c（并勾选温度相关）
            def _on_mat(*_a, idx_=i, a_=a_in, b_=b, c_=c, cb_=temp_cb):
                self._apply_material(idx_)
            mat.bind(text=_on_mat)

        self.layer_grid.height = self.layer_grid.minimum_height

    def _apply_material(self, idx: int):
        """选中材料库材料时，将其 k_coef 填充到当前层 a/b/c。"""
        name, thick, mat, a_in, b, c, rc, temp_cb, save_btn = self._layer_rows[idx]
        if mat.text == "自定义":
            return
        try:
            from kiln_ht import get_material
            k_coef = get_material(mat.text)["k_coef"]
        except KeyError:
            return
        a_in.text = f"{k_coef[0]:g}"
        b.text = f"{k_coef[1]:g}"
        c.text = f"{k_coef[2]:g}"
        temp_cb.active = True

    def _save_material(self, idx: int):
        """将当前层 a/b/c 保存到用户材料库。"""
        name, thick, mat, a_in, b, c, rc, temp_cb, save_btn = self._layer_rows[idx]
        try:
            k_coef = (float(a_in.text), float(b.text), float(c.text))
            save_user_material(name.text.strip() or f"层{idx + 1}", k_coef)
            # 刷新材料下拉
            mat.values = ["自定义"] + material_names()
            self._flash_error("已保存到材料库 ✓")
        except ValueError as exc:
            self._flash_error(f"保存失败：{exc}")

    def collect_params(self):
        """解析界面参数，非法输入抛 ValueError。"""
        layers = []
        for i, (name, thick, mat, a_in, b, c, rc, temp_cb, save_btn) in enumerate(self._layer_rows):
            a = float(a_in.text)
            if temp_cb.active:
                k_coef = (a, float(b.text), float(c.text))
            else:
                k_coef = (a, 0.0, 0.0)   # 未勾选温度相关 -> 常数 k
            layers.append(Layer(
                name=name.text.strip() or f"层{i+1}",
                thickness=float(thick.text) / 1000.0,
                k_coef=k_coef,
                Rc=float(rc.text),
            ))
        p = self._fields
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
        return layers, params

    def _on_calc(self):
        self.error_label.text = ""
        try:
            layers, params = self.collect_params()
        except ValueError as exc:
            self._flash_error(str(exc))
            return
        self.on_calc(layers, params)

    def _flash_error(self, msg):
        self.error_label.text = f"⚠ {msg}"
        Clock.schedule_once(lambda *_args: self.error_label.__setattr__("text", ""), 3.0)


# ============ 计算结果页（Tab 2） ============
class ResultScreen(Screen):
    """结果页：顶部指标高亮卡（固定）+ 中部表格区（滚动）+ 图表区（填满剩余空间）。"""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.name = "results"
        self._last = None          # 最近一次结果 (layers, params, sol, x_mm, T_c)
        root = BoxLayout(orientation="vertical", spacing=dp(10),
                         padding=[dp(0), dp(10), dp(0), dp(0)])

        # ---- 上半区：3 个指标高亮卡（横向排列，固定高度） ----
        metrics = BoxLayout(orientation="horizontal", spacing=dp(10),
                            size_hint_y=None, height=dp(110),
                            padding=[dp(14), 0, dp(14), 0])
        self.m_outer = MetricCard("外壁面温度", "°C")
        self.m_inner = MetricCard("内壁面温度", "°C")
        self.m_eg = MetricCard("烟气发射率", "—")
        for m in (self.m_outer, self.m_inner, self.m_eg):
            metrics.add_widget(m)
        root.add_widget(metrics)

        # ---- 导出按钮（结果页顶部） ----
        export_bar = BoxLayout(orientation="horizontal", spacing=dp(10),
                               size_hint_y=None, height=dp(48),
                               padding=[dp(14), 0, dp(14), 0])
        self.export_btn = AccentButton(text="导出结果", bg=CARD_ELEV,
                                       radius=dp(10), font_size=sp(14))
        self.export_btn.bind(on_press=lambda *_a: self._export())
        self.export_status = MdLabel(text="", color=TEXT_DIM, font_size=sp(12),
                                     size_hint_y=None, height=dp(20),
                                     halign="center")
        export_bar.add_widget(self.export_btn)
        root.add_widget(export_bar)
        root.add_widget(self.export_status)

        # ---- 中部：各层界面温度 + 详细结果（固定高度，内部滚动） ----
        tables = ScrollView(bar_width=dp(4), bar_color=GRID,
                            bar_inactive_color=GRID,
                            size_hint_y=None, height=dp(230))
        tcontent = BoxLayout(orientation="vertical", spacing=dp(10),
                             padding=[dp(14), 0, dp(14), 0],
                             size_hint_y=None)
        tcontent.bind(minimum_height=tcontent.setter("height"))
        tables.add_widget(tcontent)

        iface = auto_height(MDCard())
        iface.add_widget(make_title("各层界面温度"))
        self.iface_body = BoxLayout(orientation="vertical", spacing=dp(2),
                                    size_hint_y=None)
        self.iface_body.bind(minimum_height=self.iface_body.setter("height"))
        self.iface_placeholder = MdLabel(text="点击「开始计算」后显示", color=TEXT_DIM,
                                         size_hint_y=None, height=dp(36))
        self.iface_body.add_widget(self.iface_placeholder)
        iface.add_widget(self.iface_body)
        tcontent.add_widget(iface)

        detail = auto_height(MDCard())
        detail.add_widget(make_title("详细工况结果"))
        self.detail_body = BoxLayout(orientation="vertical", spacing=dp(2),
                                     size_hint_y=None)
        self.detail_body.bind(minimum_height=self.detail_body.setter("height"))
        self.detail_placeholder = MdLabel(text="点击「开始计算」后显示", color=TEXT_DIM,
                                          size_hint_y=None, height=dp(36))
        self.detail_body.add_widget(self.detail_placeholder)
        detail.add_widget(self.detail_body)
        tcontent.add_widget(detail)

        root.add_widget(tables)

        # ---- 下半区：温度分布大图（填满剩余垂直空间，size_hint_y=1） ----
        curve_card = MDCard(spacing=dp(6), size_hint_y=1)
        curve_card.add_widget(make_title("温度分布（内壁 → 外壁）"))
        self.curve = CurveWidget(size_hint=(1, 1))
        self.curve_hint = Label(text="等待计算…", color=TEXT_DIM, font_size=sp(14),
                                size_hint=(None, None), size=(dp(200), dp(30)))
        self.curve.add_widget(self.curve_hint)
        self.curve.bind(pos=self._center_hint, size=self._center_hint)
        curve_card.add_widget(self.curve)
        self.curve_foot = MdLabel(text="", color=TEXT_DIM, font_size=sp(12),
                                  size_hint_y=None, height=dp(20))
        curve_card.add_widget(self.curve_foot)
        root.add_widget(curve_card)

        self.add_widget(root)

    def _center_hint(self, *_args):
        self.curve_hint.center = self.curve.center

    def set_result(self, layers, sol, x_mm, T_c):
        """用最新计算结果刷新整个结果页。"""
        self._last = (layers, sol, x_mm, T_c)
        self.export_status.text = ""
        self.m_outer.set_value(f"{sol.T_wN - 273.15:.1f}")
        self.m_inner.set_value(f"{sol.T_w1 - 273.15:.1f}")
        self.m_eg.set_value(f"{sol.eg:.3f}")

        self.iface_body.clear_widgets()
        rows = [("内壁面", sol.T_iface[0])]
        for i in range(1, len(sol.T_iface) - 1):
            rows.append((f"{layers[i-1].name} / {layers[i].name}", sol.T_iface[i]))
        rows.append(("外壁面", sol.T_iface[-1]))
        for name, tk in rows:
            self.iface_body.add_widget(StatRow(name, f"{tk - 273.15:.1f} °C"))
        self.iface_body.height = self.iface_body.minimum_height

        self.detail_body.clear_widgets()
        stats = [
            ("单位长度热功率 Q'", f"{sol.Qprime:.1f} W/m"),
            ("内壁热流密度 q_in", f"{sol.q_in:.1f} W/m²"),
            ("外壁热流密度 q_out", f"{sol.q_out:.1f} W/m²"),
            ("内壁总换热系数 h_in", f"{sol.h_in:.1f} W/m²·K"),
            ("　内壁对流 h_conv", f"{sol.h_conv_in:.1f} W/m²·K"),
            ("　内壁辐射 h_rad", f"{sol.h_rad_in:.1f} W/m²·K"),
            ("外壁总换热系数 h_out", f"{sol.h_out:.1f} W/m²·K"),
            ("　外壁对流 h_conv", f"{sol.h_conv_out:.1f} W/m²·K"),
            ("　外壁辐射 h_rad", f"{sol.h_rad_out:.1f} W/m²·K"),
            ("耦合迭代步数", f"{sol.iterations}"),
        ]
        for label, value in stats:
            self.detail_body.add_widget(StatRow(label, value))
        self.detail_body.height = self.detail_body.minimum_height

        self.curve.set_data(x_mm, T_c)
        self.curve_hint.opacity = 0
        self.curve_foot.text = f"距内壁 0 mm  →  {x_mm[-1]:.0f} mm"

    def _export(self):
        """导出/分享计算结果。"""
        if self._last is None:
            self.export_status.text = "⚠ 先计算再导出"
            return
        layers, sol, x_mm, T_c = self._last
        params = self._get_params()
        ok, msg = export_result(layers, params, sol, x_mm, T_c)
        self.export_status.text = f"✓ {msg}" if ok else f"⚠ {msg}"

    def _get_params(self):
        """从输入页读取当前工况参数（用于导出报告）。"""
        try:
            _layers, params = self.parent.parent.input_screen.collect_params()
            return params
        except Exception:  # noqa: BLE001
            from kiln_ht import KilnParams
            return KilnParams()


# ============ 主界面 ============
class KilnApp(BoxLayout):
    """主界面：应用栏 + ScreenManager（输入 / 结果）+ 底部导航栏。"""

    def __init__(self, **kwargs):
        super().__init__(orientation="vertical", **kwargs)
        self._build_appbar()
        self.sm = ScreenManager(transition=FadeTransition(duration=0.18))
        self.input_screen = InputScreen(on_calc=self._run_calc)
        self.result_screen = ResultScreen()
        self.sm.add_widget(self.input_screen)
        self.sm.add_widget(self.result_screen)
        self.add_widget(self.sm)
        self.nav = BottomNavBar(on_select=self._on_nav)
        self.add_widget(self.nav)

    # ---------- 顶部应用栏 ----------
    def _build_appbar(self):
        bar = BoxLayout(size_hint_y=None, height=dp(50),
                        padding=[dp(16), 0, dp(16), 0])
        with bar.canvas.before:
            Color(*CARD)
            self._bar_rect = Rectangle(pos=bar.pos, size=bar.size)
            Color(*CARD_BORDER)
            self._bar_line = Line(points=[0.0, 0.0, 0.0, 0.0], width=dp(1))
        bar.bind(pos=lambda *_a: self._sync_appbar(bar),
                 size=lambda *_a: self._sync_appbar(bar))
        title = Label(text="水泥窑窑衬传热计算", color=TEXT, bold=True,
                      font_size=sp(17), halign="left", valign="middle")
        title.bind(size=lambda *_args: setattr(title, "text_size", title.size))
        bar.add_widget(title)
        self.add_widget(bar)

    def _sync_appbar(self, bar):
        self._bar_rect.pos = bar.pos
        self._bar_rect.size = bar.size
        self._bar_line.points = [bar.x, bar.y, bar.x + bar.width, bar.y]

    # ---------- 导航 ----------
    def _on_nav(self, index):
        self.sm.current = BottomNavBar.NAV[index][1]
        self.nav.set_index(index)

    # ---------- 计算 ----------
    def _run_calc(self, layers, params):
        try:
            sol = solve_wall(layers, params)
            x_mm, T_c = compute_temperature_curve(layers, sol, n_points=params.N_total)
        except Exception as exc:  # noqa: BLE001 —— UI 层统一捕获并展示错误
            self.input_screen._flash_error(str(exc))
            return False
        self.result_screen.set_result(layers, sol, x_mm, T_c)
        self._on_nav(1)
        return True


class HeatTransferApp(App):
    """应用入口。"""

    def build(self):
        from kivy.core.window import Window
        Window.clearcolor = BG
        self.title = "水泥窑窑衬传热计算"
        return KilnApp()


if __name__ == "__main__":
    HeatTransferApp().run()
