#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Kivy 增强组件库

包含：
- StepperRow: +/- 步进器（含震动反馈）
- LayerCard: 可滑动删除的衬层卡片
- SafetyMetricCard: 安全状态指标卡（绿/橙/红）
- AccordionSection: 折叠参数分组
- FAB: Material Design 浮动操作按钮
"""

from kivy.uix.boxlayout import BoxLayout
from kivy.uix.button import Button
from kivy.uix.label import Label
from kivy.uix.textinput import TextInput
from kivy.uix.floatlayout import FloatLayout
from kivy.uix.scrollview import ScrollView
from kivy.properties import (
    StringProperty,
    NumericProperty,
    BooleanProperty,
    ListProperty,
    ObjectProperty,
)
from kivy.animation import Animation
from kivy.graphics import Color, Rectangle, RoundedRectangle
from kivy.clock import Clock
from kivy.metrics import dp

# Android 震动反馈
try:
    from jnius import autoclass
    PythonActivity = autoclass('org.kivy.android.PythonActivity')
    Context = autoclass('android.content.Context')
    Vibrator = autoclass('android.os.Vibrator')
    ANDROID = True
except:
    ANDROID = False

def trigger_haptic(duration=50):
    """触发震动反馈（Android）

    Args:
        duration: 震动时长（毫秒），默认 50ms
    """
    if ANDROID:
        try:
            activity = PythonActivity.mActivity
            vibrator = activity.getSystemService(Context.VIBRATOR_SERVICE)
            vibrator.vibrate(duration)
        except Exception as e:
            print(f"震动反馈失败: {e}")

# ============ Material Design 3 色系 ============
MD3_PRIMARY = (168/255, 199/255, 250/255, 1)  # #A8C7FA
MD3_ON_PRIMARY = (6/255, 46/255, 111/255, 1)  # #062E6F
MD3_SURFACE = (26/255, 28/255, 30/255, 1)  # #1A1C1E
MD3_SURFACE_VARIANT = (66/255, 71/255, 78/255, 1)  # #42474E
MD3_ON_SURFACE = (226/255, 226/255, 229/255, 1)  # #E2E2E5
MD3_ERROR = (255/255, 180/255, 171/255, 1)  # #FFB4AB
MD3_SUCCESS = (76/255, 175/255, 80/255, 1)  # 绿色
MD3_WARNING = (255/255, 152/255, 0/255, 1)  # 橙色

# ============ StepperRow: +/- 步进器 ============
class StepperRow(BoxLayout):
    """数值步进器（Material Design）

    特性：
    - 左右 +/- 按钮
    - 中间显示当前值
    - 支持手动输入
    - 震动反馈（Android）
    """
    label_text = StringProperty("参数")
    unit = StringProperty("")
    value = NumericProperty(0)
    step = NumericProperty(1)
    min_value = NumericProperty(0)
    max_value = NumericProperty(100)

    def __init__(self, label="参数", unit="", value=0, step=1, min_val=0, max_val=100, **kwargs):
        super().__init__(orientation='horizontal', size_hint_y=None, height=dp(60), **kwargs)
        self.label_text = label
        self.unit = unit
        self.value = value
        self.step = step
        self.min_value = min_val
        self.max_value = max_val

        # 背景
        with self.canvas.before:
            Color(*MD3_SURFACE_VARIANT)
            self.rect = RoundedRectangle(pos=self.pos, size=self.size, radius=[dp(12)])
        self.bind(pos=self._update_rect, size=self._update_rect)

        # 标签
        self.label = Label(
            text=f"{self.label_text}",
            size_hint_x=0.4,
            color=MD3_ON_SURFACE,
            halign='left',
            valign='middle',
        )
        self.label.bind(size=self.label.setter('text_size'))
        self.add_widget(self.label)

        # 减少按钮
        self.btn_minus = Button(
            text="-",
            size_hint_x=0.15,
            background_color=MD3_PRIMARY,
            color=MD3_ON_PRIMARY,
            font_size=dp(24),
        )
        self.btn_minus.bind(on_press=self._decrement)
        self.add_widget(self.btn_minus)

        # 数值输入框
        self.input = TextInput(
            text=f"{self.value:.2f}",
            size_hint_x=0.25,
            multiline=False,
            input_filter='float',
            halign='center',
            background_color=MD3_SURFACE,
            foreground_color=MD3_ON_SURFACE,
        )
        self.input.bind(on_text_validate=self._on_input_change)
        self.add_widget(self.input)

        # 单位标签
        self.unit_label = Label(
            text=self.unit,
            size_hint_x=0.1,
            color=MD3_ON_SURFACE,
        )
        self.add_widget(self.unit_label)

        # 增加按钮
        self.btn_plus = Button(
            text="+",
            size_hint_x=0.15,
            background_color=MD3_PRIMARY,
            color=MD3_ON_PRIMARY,
            font_size=dp(24),
        )
        self.btn_plus.bind(on_press=self._increment)
        self.add_widget(self.btn_plus)

    def _update_rect(self, *args):
        self.rect.pos = self.pos
        self.rect.size = self.size

    def _increment(self, instance):
        self.value = min(self.value + self.step, self.max_value)
        self.input.text = f"{self.value:.2f}"
        trigger_haptic(30)

    def _decrement(self, instance):
        self.value = max(self.value - self.step, self.min_value)
        self.input.text = f"{self.value:.2f}"
        trigger_haptic(30)

    def _on_input_change(self, instance):
        try:
            new_val = float(instance.text)
            self.value = max(self.min_value, min(new_val, self.max_value))
            self.input.text = f"{self.value:.2f}"
        except ValueError:
            self.input.text = f"{self.value:.2f}"

# ============ LayerCard: 可滑动删除的衬层卡片 ============
class LayerCard(FloatLayout):
    """衬层卡片（支持滑动删除）

    特性：
    - 显示层名、厚度、导热系数
    - 左滑露出删除按钮
    - 点击跳转编辑页
    - 删除时震动反馈
    """
    layer_name = StringProperty("未命名层")
    thickness = NumericProperty(0)
    k_coef_str = StringProperty("0, 0, 0")
    on_delete = ObjectProperty(None)
    on_edit = ObjectProperty(None)

    def __init__(self, layer_data, on_delete=None, on_edit=None, **kwargs):
        super().__init__(size_hint_y=None, height=dp(80), **kwargs)
        self.layer_name = layer_data.get("name", "未命名层")
        self.thickness = layer_data.get("thickness_mm", 0)
        a, b, c = layer_data.get("k_coef", (0, 0, 0))
        self.k_coef_str = f"{a:.2f}, {b:.5f}, {c:.7f}"
        self.on_delete = on_delete
        self.on_edit = on_edit

        # 背景层（删除按钮背景）
        self.bg_layer = BoxLayout(size_hint=(1, 1), pos_hint={'x': 0, 'y': 0})
        with self.bg_layer.canvas.before:
            Color(*MD3_ERROR)
            self.bg_rect = Rectangle(pos=self.bg_layer.pos, size=self.bg_layer.size)
        self.bg_layer.bind(pos=self._update_bg_rect, size=self._update_bg_rect)

        # 删除按钮（隐藏在右侧）
        self.delete_btn = Button(
            text="删除",
            size_hint=(0.3, 1),
            pos_hint={'right': 1, 'y': 0},
            background_color=(0, 0, 0, 0),
            color=MD3_ON_SURFACE,
        )
        self.delete_btn.bind(on_press=self._on_delete_press)
        self.bg_layer.add_widget(self.delete_btn)
        self.add_widget(self.bg_layer)

        # 前景卡片（可滑动）
        self.card = BoxLayout(
            orientation='vertical',
            size_hint=(1, 1),
            pos_hint={'x': 0, 'y': 0},
            padding=dp(12),
            spacing=dp(4),
        )
        with self.card.canvas.before:
            Color(*MD3_SURFACE_VARIANT)
            self.card_rect = RoundedRectangle(pos=self.card.pos, size=self.card.size, radius=[dp(8)])
        self.card.bind(pos=self._update_card_rect, size=self._update_card_rect)

        # 卡片内容
        self.title_label = Label(
            text=self.layer_name,
            size_hint_y=0.5,
            color=MD3_PRIMARY,
            font_size=dp(18),
            halign='left',
            valign='middle',
        )
        self.title_label.bind(size=self.title_label.setter('text_size'))
        self.card.add_widget(self.title_label)

        self.info_label = Label(
            text=f"厚度: {self.thickness:.1f} mm | k系数: {self.k_coef_str}",
            size_hint_y=0.5,
            color=MD3_ON_SURFACE,
            font_size=dp(14),
            halign='left',
            valign='middle',
        )
        self.info_label.bind(size=self.info_label.setter('text_size'))
        self.card.add_widget(self.info_label)

        self.add_widget(self.card)

        # 触摸事件（滑动检测）
        self._touch_start_x = 0
        self._swipe_threshold = dp(50)  # 滑动阈值

    def _update_bg_rect(self, *args):
        self.bg_rect.pos = self.bg_layer.pos
        self.bg_rect.size = self.bg_layer.size

    def _update_card_rect(self, *args):
        self.card_rect.pos = self.card.pos
        self.card_rect.size = self.card.size

    def on_touch_down(self, touch):
        if self.collide_point(*touch.pos):
            self._touch_start_x = touch.x
            return True
        return super().on_touch_down(touch)

    def on_touch_move(self, touch):
        if self.collide_point(*touch.pos) and hasattr(self, '_touch_start_x'):
            delta_x = touch.x - self._touch_start_x
            # 仅允许左滑（delta_x < 0）
            if delta_x < 0:
                new_x = max(delta_x / self.width, -0.3)  # 最多露出30%
                self.card.pos_hint = {'x': new_x, 'y': 0}
            return True
        return super().on_touch_move(touch)

    def on_touch_up(self, touch):
        if self.collide_point(*touch.pos) and hasattr(self, '_touch_start_x'):
            delta_x = touch.x - self._touch_start_x

            # 判断滑动距离
            if delta_x < -self._swipe_threshold:
                # 滑动距离足够，停留在删除位置
                anim = Animation(pos_hint={'x': -0.3, 'y': 0}, duration=0.2)
                anim.start(self.card)
                trigger_haptic(50)
            else:
                # 回弹到原位
                anim = Animation(pos_hint={'x': 0, 'y': 0}, duration=0.2)
                anim.start(self.card)

            # 检测是否为点击（非滑动）
            if abs(delta_x) < dp(10) and self.on_edit:
                self.on_edit()

            return True
        return super().on_touch_up(touch)

    def _on_delete_press(self, instance):
        trigger_haptic(100)
        if self.on_delete:
            self.on_delete()

# ============ SafetyMetricCard: 安全状态指标卡 ============
class SafetyMetricCard(BoxLayout):
    """安全状态指标卡（语义色）

    特性：
    - 左侧状态条（绿/橙/红）
    - 指标名称 + 数值
    - 自动根据阈值变色
    """
    title = StringProperty("指标")
    value = NumericProperty(0)
    unit = StringProperty("")
    # 阈值：[safe_max, warning_max]
    thresholds = ListProperty([80, 120])

    def __init__(self, title="指标", value=0, unit="", thresholds=None, **kwargs):
        super().__init__(orientation='horizontal', size_hint_y=None, height=dp(80), **kwargs)
        self.title = title
        self.value = value
        self.unit = unit
        if thresholds:
            self.thresholds = thresholds

        # 左侧状态条
        self.status_bar = BoxLayout(size_hint_x=0.05)
        with self.status_bar.canvas.before:
            self.status_color = Color(*self._get_status_color())
            self.status_rect = Rectangle(pos=self.status_bar.pos, size=self.status_bar.size)
        self.status_bar.bind(pos=self._update_status_rect, size=self._update_status_rect)
        self.add_widget(self.status_bar)

        # 右侧内容
        content = BoxLayout(orientation='vertical', padding=dp(12), spacing=dp(4))

        # 背景
        with content.canvas.before:
            Color(*MD3_SURFACE_VARIANT)
            self.content_rect = RoundedRectangle(pos=content.pos, size=content.size, radius=[dp(8)])
        content.bind(pos=self._update_content_rect, size=self._update_content_rect)

        # 标题
        self.title_label = Label(
            text=self.title,
            size_hint_y=0.4,
            color=MD3_ON_SURFACE,
            font_size=dp(14),
            halign='left',
            valign='bottom',
        )
        self.title_label.bind(size=self.title_label.setter('text_size'))
        content.add_widget(self.title_label)

        # 数值
        self.value_label = Label(
            text=f"{self.value:.1f} {self.unit}",
            size_hint_y=0.6,
            color=self._get_status_color(),
            font_size=dp(28),
            bold=True,
            halign='left',
            valign='top',
        )
        self.value_label.bind(size=self.value_label.setter('text_size'))
        content.add_widget(self.value_label)

        self.add_widget(content)

        # 绑定值变化
        self.bind(value=self._on_value_change)

    def _get_status_color(self):
        """根据阈值返回颜色"""
        if self.value < self.thresholds[0]:
            return MD3_SUCCESS  # 绿色
        elif self.value < self.thresholds[1]:
            return MD3_WARNING  # 橙色
        else:
            return MD3_ERROR  # 红色

    def _update_status_rect(self, *args):
        self.status_rect.pos = self.status_bar.pos
        self.status_rect.size = self.status_bar.size

    def _update_content_rect(self, *args):
        self.content_rect.pos = self.status_rect.pos if hasattr(self, 'status_rect') else (0, 0)
        self.content_rect.size = self.status_rect.size if hasattr(self, 'status_rect') else self.size

    def _on_value_change(self, instance, value):
        """数值变化时更新颜色"""
        new_color = self._get_status_color()
        self.status_color.rgba = new_color
        self.value_label.color = new_color
        self.value_label.text = f"{value:.1f} {self.unit}"

# ============ AccordionSection: 折叠参数分组 ============
class AccordionSection(BoxLayout):
    """折叠面板（Material Design）

    特性：
    - 标题栏可点击展开/收起
    - 内容高度随子组件自动增长（minimum_height 绑定）
    - 箭头图标切换
    """

    # 内容区当前高度（展开=子组件最小高度；收起=0）
    content_height = NumericProperty(0)

    def __init__(self, title="分组", expanded=True, **kwargs):
        super().__init__(orientation='vertical', size_hint_y=None, **kwargs)
        self.title = title
        self.expanded = expanded

        # 标题栏
        self.header = BoxLayout(
            orientation='horizontal',
            size_hint_y=None,
            height=dp(56),
        )
        with self.header.canvas.before:
            Color(*MD3_SURFACE_VARIANT)
            self.header_rect = RoundedRectangle(
                pos=self.header.pos, size=self.header.size, radius=[dp(12), dp(12), 0, 0]
            )
        self.header.bind(pos=self._update_header_rect, size=self._update_header_rect)

        self.header_label = Label(
            text=self.title,
            size_hint_x=0.9,
            color=MD3_PRIMARY,
            font_size=dp(18),
            halign='left',
            valign='middle',
        )
        self.header_label.bind(size=self.header_label.setter('text_size'))
        self.header.add_widget(self.header_label)

        self.arrow_btn = Button(
            text="▼" if self.expanded else "▶",
            size_hint_x=0.1,
            background_color=(0, 0, 0, 0),
            color=MD3_ON_SURFACE,
        )
        self.arrow_btn.bind(on_press=self._toggle)
        self.header.add_widget(self.arrow_btn)
        self.add_widget(self.header)

        # 内容区容器（高度 = content_height，不再被子组件溢出）
        self.content_container = BoxLayout(
            orientation='vertical',
            size_hint_y=None,
            height=self.content_height,
        )
        self.content_container.bind(minimum_height=self._on_min_height)

        with self.content_container.canvas.before:
            Color(*MD3_SURFACE)
            self.content_rect = Rectangle(
                pos=self.content_container.pos, size=self.content_container.size
            )
        self.content_container.bind(pos=self._update_content_rect, size=self._update_content_rect)
        self.add_widget(self.content_container)

        # 本组件高度 = 标题栏 + 内容区（size_hint_y=None，由 property 驱动）
        self.bind(content_height=self._update_height)
        self._update_height()

    def _on_min_height(self, instance, value):
        """子组件最小高度变化：展开时跟随，收起时保持 0"""
        if self.expanded:
            self.content_height = value

    def _update_height(self, *args):
        """展开时高度 = 标题 + 内容；收起时仅标题"""
        self.height = dp(56) + self.content_height

    def add_content(self, widget):
        """添加内容组件"""
        self.content_container.add_widget(widget)

    def _toggle(self, instance):
        """展开/收起"""
        self.expanded = not self.expanded
        if self.expanded:
            # 展开：恢复为子组件最小高度
            self.content_height = self.content_container.minimum_height
        else:
            # 收起：内容高度归零，避免内容区覆盖/重叠
            self.content_container.height = 0
            self.content_height = 0
        # 更新箭头
        self.arrow_btn.text = "▼" if self.expanded else "▶"
        trigger_haptic(30)

    def _update_header_rect(self, *args):
        self.header_rect.pos = self.header.pos
        self.header_rect.size = self.header.size

    def _update_content_rect(self, *args):
        self.content_rect.pos = self.content_container.pos
        self.content_rect.size = self.content_container.size

# ============ FAB: 浮动操作按钮 ============
class FAB(Button):
    """Material Design 浮动操作按钮

    特性：
    - 圆形按钮
    - 固定在右下角
    - 点击震动反馈
    """
    icon = StringProperty("+")

    def __init__(self, icon="+", on_press_callback=None, **kwargs):
        super().__init__(
            text=icon,
            size_hint=(None, None),
            size=(dp(56), dp(56)),
            pos_hint={'right': 0.95, 'y': 0.05},
            font_size=dp(28),
            background_color=MD3_PRIMARY,
            color=MD3_ON_PRIMARY,
            **kwargs
        )
        self.icon = icon

        # 圆形背景
        with self.canvas.before:
            Color(*MD3_PRIMARY)
            self.circle = RoundedRectangle(
                pos=self.pos, size=self.size, radius=[dp(28)]
            )
        self.bind(pos=self._update_circle, size=self._update_circle)

        if on_press_callback:
            self.bind(on_press=lambda instance: on_press_callback())

        # 震动反馈
        self.bind(on_press=lambda instance: trigger_haptic(50))

    def _update_circle(self, *args):
        self.circle.pos = self.pos
        self.circle.size = self.size
