#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Kivy 增强版主应用

框架：
- InputScreen: 参数输入屏（Accordion 折叠）
- LayerManagerScreen: 衬层管理独立页
- ResultScreen: 结果屏（安全状态语义色）
- AppState: 全局状态管理
"""

from kivy.app import App
from kivy.uix.screenmanager import ScreenManager, Screen
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.scrollview import ScrollView
from kivy.uix.button import Button
from kivy.uix.label import Label
from kivy.properties import NumericProperty, ListProperty
from kivy.metrics import dp
from kivy.graphics import Color, Rectangle

# 导入增强组件
from kivy_enhanced_widgets import (
    StepperRow,
    LayerCard,
    SafetyMetricCard,
    AccordionSection,
    FAB,
    MD3_SURFACE,
    MD3_ON_SURFACE,
    MD3_PRIMARY,
    trigger_haptic,
)

# 假设 kiln_ht 核心计算已可用
try:
    from kiln_ht import Layer, KilnParams, solve_wall
    CALC_AVAILABLE = True
except ImportError:
    CALC_AVAILABLE = False
    print("⚠️ kiln_ht 模块未找到，计算功能不可用")

# ============ 全局状态管理（单例）============
class AppState:
    """全局状态管理（单例模式）"""
    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized:
            return
        self._initialized = True

        # 参数（默认值）
        self.T_gas_C = 1250.0
        self.T_env_C = 25.0
        self.v_gas = 2.5
        self.L_char = 4.0
        self.emiss_gas = 0.7
        self.emiss_wall = 0.85
        self.h_out = 15.0

        # 衬层配置
        self.layers = [
            {"name": "工作层", "thickness_mm": 150.0, "k_coef": (0.5, 0.0003, 0)},
            {"name": "保温层", "thickness_mm": 80.0, "k_coef": (0.12, 0.0001, 0)},
            {"name": "钢壳", "thickness_mm": 20.0, "k_coef": (45.0, 0, 0)},
        ]

        # 计算结果
        self.last_result = None

APP_STATE = AppState()

# ============ 参数输入屏（Accordion 折叠）============
class InputScreen(Screen):
    """参数输入页面

    特性：
    - Accordion 三档分组（必填/常用/高级）
    - StepperRow 步进器输入
    - 底部「开始计算」按钮
    """

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.name = 'input'

        # 主布局
        layout = BoxLayout(orientation='vertical')
        with layout.canvas.before:
            Color(*MD3_SURFACE)
            self.bg = Rectangle(pos=layout.pos, size=layout.size)
        layout.bind(pos=self._update_bg, size=self._update_bg)

        # 标题
        title = Label(
            text="工况参数",
            size_hint_y=None,
            height=dp(60),
            color=MD3_PRIMARY,
            font_size=dp(24),
        )
        layout.add_widget(title)

        # 滚动容器
        scroll = ScrollView()
        content = BoxLayout(orientation='vertical', size_hint_y=None, spacing=dp(10), padding=dp(10))
        content.bind(minimum_height=content.setter('height'))

        # Accordion 1: 必填参数（默认展开）
        section1 = AccordionSection(title="必填参数", expanded=True)

        self.stepper_T_gas = StepperRow("烟气温度", "°C", APP_STATE.T_gas_C, 10, 500, 2000)
        section1.add_content(self.stepper_T_gas)

        self.stepper_T_env = StepperRow("环境温度", "°C", APP_STATE.T_env_C, 1, -20, 60)
        section1.add_content(self.stepper_T_env)

        content.add_widget(section1)

        # Accordion 2: 常用参数（默认展开）
        section2 = AccordionSection(title="常用参数", expanded=True)

        self.stepper_v_gas = StepperRow("烟气流速", "m/s", APP_STATE.v_gas, 0.1, 0.1, 20.0)
        section2.add_content(self.stepper_v_gas)

        self.stepper_L_char = StepperRow("窑内径", "m", APP_STATE.L_char, 0.1, 1.0, 10.0)
        section2.add_content(self.stepper_L_char)

        content.add_widget(section2)

        # Accordion 3: 高级参数（默认收起）
        section3 = AccordionSection(title="高级参数", expanded=False)

        self.stepper_emiss_gas = StepperRow("烟气发射率", "", APP_STATE.emiss_gas, 0.01, 0.1, 1.0)
        section3.add_content(self.stepper_emiss_gas)

        self.stepper_emiss_wall = StepperRow("内壁发射率", "", APP_STATE.emiss_wall, 0.01, 0.1, 1.0)
        section3.add_content(self.stepper_emiss_wall)

        self.stepper_h_out = StepperRow("外表面对流系数", "W/m²K", APP_STATE.h_out, 1.0, 1.0, 50.0)
        section3.add_content(self.stepper_h_out)

        content.add_widget(section3)

        scroll.add_widget(content)
        layout.add_widget(scroll)

        # 底部按钮区
        btn_layout = BoxLayout(size_hint_y=None, height=dp(70), spacing=dp(10), padding=dp(10))

        btn_layers = Button(
            text="衬层配置",
            background_color=MD3_PRIMARY,
            on_press=self._goto_layers,
        )
        btn_layout.add_widget(btn_layers)

        btn_calc = Button(
            text="开始计算",
            background_color=(76/255, 175/255, 80/255, 1),  # 绿色
            on_press=self._start_calculation,
        )
        btn_layout.add_widget(btn_calc)

        layout.add_widget(btn_layout)

        self.add_widget(layout)

    def _update_bg(self, *args):
        self.bg.pos = self.pos
        self.bg.size = self.size

    def _goto_layers(self, instance):
        """跳转到衬层管理页"""
        self.manager.current = 'layers'
        trigger_haptic(30)

    def _start_calculation(self, instance):
        """开始计算"""
        trigger_haptic(50)

        if not CALC_AVAILABLE:
            self._show_error("计算模块未加载，无法计算")
            return

        try:
            # 从 Stepper 读取参数（实际值）
            APP_STATE.T_gas_C = self.stepper_T_gas.value
            APP_STATE.T_env_C = self.stepper_T_env.value
            APP_STATE.v_gas = self.stepper_v_gas.value
            APP_STATE.L_char = self.stepper_L_char.value
            APP_STATE.emiss_gas = self.stepper_emiss_gas.value
            APP_STATE.emiss_wall = self.stepper_emiss_wall.value
            APP_STATE.h_out = self.stepper_h_out.value

            # 构造 Layer 对象（thickness 单位为米）
            layers = [
                Layer(
                    name=l["name"],
                    thickness=l["thickness_mm"] / 1000.0,
                    k_coef=l["k_coef"],
                )
                for l in APP_STATE.layers
            ]

            # 构造 KilnParams（烟气发射率取默认；外部对流由环境风速+外壳发射率驱动）
            params = KilnParams(
                T_gas=APP_STATE.T_gas_C + 273.15,
                T_env=APP_STATE.T_env_C + 273.15,
                v_gas=APP_STATE.v_gas,
                L_char=APP_STATE.L_char,
                eps_wall=APP_STATE.emiss_wall,
                eps_shell=APP_STATE.emiss_wall,
                v_amb=max(0.5, APP_STATE.h_out / 2.0),
            )

            # 调用计算（返回单个 WallSolution）
            sol = solve_wall(layers, params)

            # 保存结果
            APP_STATE.last_result = {
                "solution": sol,
            }

            # 跳转到结果页
            self.manager.current = 'result'
            print("计算完成")

        except Exception as e:
            import traceback
            traceback.print_exc()
            self._show_error(f"计算失败: {e}")

    def _show_error(self, message):
        """错误弹窗（Popup），确保错误对用户可见"""
        from kivy.uix.popup import Popup
        content = BoxLayout(orientation='vertical', padding=dp(20), spacing=dp(10))
        content.add_widget(Label(text=message, color=(1, 0.3, 0.3, 1)))
        btn_ok = Button(
            text="确定",
            size_hint_y=None,
            height=dp(48),
            background_color=MD3_PRIMARY,
        )
        content.add_widget(btn_ok)
        popup = Popup(title="错误", content=content, size_hint=(0.8, 0.4))
        btn_ok.bind(on_press=popup.dismiss)
        popup.open()

# ============ 衬层管理屏（独立页）============
class LayerManagerScreen(Screen):
    """衬层管理页面

    特性：
    - 列表显示所有衬层（LayerCard）
    - FAB 添加新衬层
    - 滑动删除
    - 点击跳转编辑页（待实现）
    """

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.name = 'layers'

        # 主布局
        self.layout = BoxLayout(orientation='vertical')
        with self.layout.canvas.before:
            Color(*MD3_SURFACE)
            self.bg = Rectangle(pos=self.layout.pos, size=self.layout.size)
        self.layout.bind(pos=self._update_bg, size=self._update_bg)

        # 标题栏
        header = BoxLayout(size_hint_y=None, height=dp(60), padding=dp(10))

        back_btn = Button(
            text="< 返回",
            size_hint_x=0.3,
            background_color=MD3_PRIMARY,
            on_press=self._go_back,
        )
        header.add_widget(back_btn)

        title = Label(
            text="衬层配置",
            color=MD3_PRIMARY,
            font_size=dp(20),
        )
        header.add_widget(title)

        self.layout.add_widget(header)

        # 滚动列表
        self.scroll = ScrollView()
        self.layer_list = BoxLayout(
            orientation='vertical',
            size_hint_y=None,
            spacing=dp(8),
            padding=dp(10),
        )
        self.layer_list.bind(minimum_height=self.layer_list.setter('height'))
        self.scroll.add_widget(self.layer_list)
        self.layout.add_widget(self.scroll)

        # FAB 添加按钮
        fab = FAB(icon="+", on_press_callback=self._add_layer)
        self.layout.add_widget(fab)

        self.add_widget(self.layout)

    def on_enter(self):
        """进入页面时刷新列表"""
        self._refresh_list()

    def _update_bg(self, *args):
        self.bg.pos = self.layout.pos
        self.bg.size = self.layout.size

    def _go_back(self, instance):
        self.manager.current = 'input'
        trigger_haptic(30)

    def _refresh_list(self):
        """刷新衬层列表"""
        self.layer_list.clear_widgets()

        for i, layer_data in enumerate(APP_STATE.layers):
            card = LayerCard(
                layer_data=layer_data,
                on_delete=lambda idx=i: self._delete_layer(idx),
                on_edit=lambda idx=i: self._edit_layer(idx),
            )
            self.layer_list.add_widget(card)

    def _add_layer(self):
        """添加新衬层"""
        APP_STATE.layers.append({
            "name": f"新层{len(APP_STATE.layers)+1}",
            "thickness_mm": 50.0,
            "k_coef": (0.5, 0, 0),
        })
        self._refresh_list()
        trigger_haptic(50)

    def _delete_layer(self, index):
        """删除指定衬层"""
        if 0 <= index < len(APP_STATE.layers):
            APP_STATE.layers.pop(index)
            self._refresh_list()
            trigger_haptic(100)

    def _edit_layer(self, index):
        """编辑衬层（跳转编辑页）"""
        # ponytail: 待实现 LayerEditScreen
        print(f"编辑层 {index}（功能待实现）")
        trigger_haptic(30)

# ============ 结果屏（安全状态语义色）============
class ResultScreen(Screen):
    """计算结果页面

    特性：
    - 安全状态指标卡（SafetyMetricCard）
    - 关键数值展示
    - 温度曲线（待实现）
    """

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.name = 'result'

        # 主布局
        self.layout = BoxLayout(orientation='vertical')
        with self.layout.canvas.before:
            Color(*MD3_SURFACE)
            self.bg = Rectangle(pos=self.layout.pos, size=self.layout.size)
        self.layout.bind(pos=self._update_bg, size=self._update_bg)

        # 标题栏
        header = BoxLayout(size_hint_y=None, height=dp(60), padding=dp(10))

        back_btn = Button(
            text="< 返回",
            size_hint_x=0.3,
            background_color=MD3_PRIMARY,
            on_press=self._go_back,
        )
        header.add_widget(back_btn)

        title = Label(
            text="计算结果",
            color=MD3_PRIMARY,
            font_size=dp(20),
        )
        header.add_widget(title)

        self.layout.add_widget(header)

        # 滚动容器
        scroll = ScrollView()
        self.content = BoxLayout(
            orientation='vertical',
            size_hint_y=None,
            spacing=dp(12),
            padding=dp(10),
        )
        self.content.bind(minimum_height=self.content.setter('height'))
        scroll.add_widget(self.content)
        self.layout.add_widget(scroll)

        self.add_widget(self.layout)

    def on_enter(self):
        """进入页面时刷新结果"""
        self._display_result()

    def _update_bg(self, *args):
        self.bg.pos = self.layout.pos
        self.bg.size = self.layout.size

    def _go_back(self, instance):
        self.manager.current = 'input'
        trigger_haptic(30)

    def _display_result(self):
        """显示计算结果"""
        self.content.clear_widgets()

        if APP_STATE.last_result is None:
            no_data = Label(
                text="暂无结果，请先计算",
                color=MD3_ON_SURFACE,
                size_hint_y=None,
                height=dp(200),
            )
            self.content.add_widget(no_data)
            return

        sol = APP_STATE.last_result["solution"]

        # 关键指标卡片
        card1 = SafetyMetricCard(
            title="外壁温度",
            value=sol.T_wN - 273.15,
            unit="°C",
            thresholds=[80, 120],  # 绿 < 80, 橙 80-120, 红 > 120
        )
        self.content.add_widget(card1)

        card2 = SafetyMetricCard(
            title="热损失",
            value=sol.Qprime,
            unit="W/m",
            thresholds=[500, 1000],  # 绿 < 500, 橙 500-1000, 红 > 1000
        )
        self.content.add_widget(card2)

        # 其他指标
        info_box = BoxLayout(
            orientation='vertical',
            size_hint_y=None,
            height=dp(150),
            padding=dp(12),
            spacing=dp(8),
        )

        info_label1 = Label(
            text=f"内壁温度: {sol.T_w1 - 273.15:.1f} °C",
            color=MD3_ON_SURFACE,
            size_hint_y=None,
            height=dp(30),
            halign='left',
        )
        info_label1.bind(size=info_label1.setter('text_size'))
        info_box.add_widget(info_label1)

        info_label2 = Label(
            text=f"内表面对流系数: {sol.h_in:.1f} W/m²K",
            color=MD3_ON_SURFACE,
            size_hint_y=None,
            height=dp(30),
            halign='left',
        )
        info_label2.bind(size=info_label2.setter('text_size'))
        info_box.add_widget(info_label2)

        info_label3 = Label(
            text=f"迭代次数: {sol.iterations}",
            color=MD3_ON_SURFACE,
            size_hint_y=None,
            height=dp(30),
            halign='left',
        )
        info_label3.bind(size=info_label3.setter('text_size'))
        info_box.add_widget(info_label3)

        self.content.add_widget(info_box)

        # ponytail: 温度曲线绘制待实现（可用 kivy.garden.graph 或 matplotlib）
        curve_placeholder = Label(
            text="温度曲线（待实现）",
            color=MD3_ON_SURFACE,
            size_hint_y=None,
            height=dp(200),
        )
        self.content.add_widget(curve_placeholder)

# ============ 主应用 ============
class KilnHTApp(App):
    """水泥窑传热计算 Kivy 应用"""

    def build(self):
        sm = ScreenManager()
        sm.add_widget(InputScreen())
        sm.add_widget(LayerManagerScreen())
        sm.add_widget(ResultScreen())
        return sm

if __name__ == '__main__':
    KilnHTApp().run()
