# -*- coding: utf-8 -*-
"""UI 冒烟测试：验证界面构建、参数采集、计算、结果展示全流程。

运行方式（Kivy mock window，无头模式）：
    python -m pytest tests/test_ui.py -v
"""

import os
import sys

# 在导入 kivy 之前设置为 mock 窗口
os.environ["KIVY_UNITTEST"] = "1"

from kivy.config import Config
Config.set("kivy", "window", "mock")
Config.set("kivy", "log_level", "warning")

import pytest
from kiln_ht import compute_temperature_curve

# 注册 mock 窗口后导入 App 模块
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


@pytest.fixture(scope="module")
def app():
    import main as ui_module
    # 确保 HeatTransferApp 未被缓存旧状态
    app = ui_module.HeatTransferApp()
    root = app.build()
    return app, root


class TestUIBuild:
    """界面构建测试。"""

    def test_app_builds(self, app):
        _, root = app
        assert root is not None
        assert hasattr(root, "sm")
        assert hasattr(root, "nav")
        assert hasattr(root, "input_screen")
        assert hasattr(root, "result_screen")

    def test_bottom_nav(self, app):
        _, root = app
        assert len(root.nav._items) == 2
        assert root.nav._items[0]._active is True
        assert root.nav._items[1]._active is False

    def test_input_fields_exist(self, app):
        _, root = app
        ins = root.input_screen
        required_keys = ["T_gas", "v_gas", "L_char", "L_kiln", "P_total",
                         "CO2", "H2O", "eps_wall", "T_env", "v_amb", "eps_shell", "N_total"]
        for key in required_keys:
            assert key in ins._fields, f"Missing field: {key}"

    def test_default_layers(self, app):
        _, root = app
        ins = root.input_screen
        layers, _ = ins.collect_params()
        assert len(layers) == 4
        assert layers[0].name == "层1"
        assert layers[0].thickness == 0.05
        assert layers[0].k_coef == (1.0, 0.0, 0.0)
        assert layers[0].Rc == 0.0

    def test_layer_name_accepts_custom_text(self, app):
        """层名输入框必须允许输入任意文本（如中文层名），不被浮点过滤器拦截。"""
        _, root = app
        ins = root.input_screen
        name, thick, mat, rc = ins._layer_rows[0]
        # 名称输入框应是普通 TextInput（无 float 过滤）
        assert name.textinput.input_filter is None, "层名输入框不应有输入过滤器"
        # 清空后输入中文层名，应能被 collect_params 正确解析
        name.text = "耐火砖"
        layers, _ = ins.collect_params()
        assert layers[0].name == "耐火砖"
        # 重新输入英文/数字混合名称同样正常
        name.text = "Steel shell 1"
        layers, _ = ins.collect_params()
        assert layers[0].name == "Steel shell 1"

    def test_layer_rows_have_kt_fields(self, app):
        """每层行应包含材料 Spinner 与接触热阻输入。"""
        _, root = app
        ins = root.input_screen
        assert len(ins._layer_rows[0]) == 4
        name, thick, mat, rc = ins._layer_rows[0]
        from kivy.uix.spinner import Spinner
        assert isinstance(mat, Spinner)
        assert mat.text == "自定义"
        assert "硅酸铝纤维" in mat.values
        assert rc.text == "0.0"

    def test_collect_params_from_material(self, app):
        """选择材料后 collect_params 应使用材料 k_coef。"""
        _, root = app
        ins = root.input_screen
        name, thick, mat, rc = ins._layer_rows[0]
        mat.text = "硅酸铝纤维"
        layers, _ = ins.collect_params()
        from kiln_ht import get_material
        assert layers[0].k_coef == get_material("硅酸铝纤维")["k_coef"]
        assert layers[0].Rc == 0.0

    def test_stepper(self, app):
        _, root = app
        ins = root.input_screen
        assert ins.stepper.value == 4
        ins.stepper._set(6)
        assert ins.stepper.value == 6
        assert len(ins._layer_rows) == 6
        ins.stepper._set(4)
        assert len(ins._layer_rows) == 4


class TestUICalculation:
    """计算与结果展示流程测试。"""

    def test_full_calc_flow(self, app):
        _, root = app
        ins = root.input_screen
        res = root.result_screen

        # 采集参数
        layers, params = ins.collect_params()
        assert len(layers) == 4
        assert params.T_gas == 1250.0 + 273.15

        # 执行计算
        ok = root._run_calc(layers, params)
        assert ok is True

        # 验证自动切换至结果页
        assert root.sm.current == "results"

        # 指标卡
        outer_val = res.m_outer.value.text
        inner_val = res.m_inner.value.text
        eg_val = res.m_eg.value.text
        assert float(outer_val) > 0
        assert float(inner_val) > 0
        assert float(eg_val) > 0
        # 外壁 < 内壁
        assert float(outer_val) < float(inner_val)

        # 界面温度表
        assert len(res.iface_body.children) == 5  # 4 层 + 1 外壁

        # 详细结果
        assert len(res.detail_body.children) == 10

        # 温度曲线
        assert len(res.curve._x) > 10
        assert len(res.curve._T) > 10

    def test_calc_with_custom_layers(self, app):
        _, root = app
        ins = root.input_screen
        from kiln_ht import Layer, KilnParams

        layers = [
            Layer(name="硅酸铝纤维", thickness=0.150, k=0.10),
            Layer(name="轻质砖", thickness=0.100, k=0.30),
            Layer(name="高铝砖", thickness=0.080, k=1.50),
            Layer(name="钢壳", thickness=0.012, k=45.0),
        ]
        params = KilnParams()
        ok = root._run_calc(layers, params)
        assert ok is True
        assert root.sm.current == "results"

        res = root.result_screen
        assert float(res.m_inner.value.text) > float(res.m_outer.value.text)
        assert float(res.m_eg.value.text) > 0.1

    def test_curve_data_matches_solution(self, app):
        """验证温度曲线数据与求解结果一致。"""
        _, root = app
        ins = root.input_screen
        layers, params = ins.collect_params()
        ok = root._run_calc(layers, params)
        assert ok is True
        res = root.result_screen
        # 曲线首尾温度应与内壁/外壁近似
        x_mm = res.curve._x
        T_c = res.curve._T
        assert abs(x_mm[0]) < 1e-9
        assert x_mm[-1] > 0
        # 内壁端温度 ≈ 内壁面温度
        inner_from_curve = T_c[0]
        outer_from_curve = T_c[-1]
        inner_from_card = float(res.m_inner.value.text)
        outer_from_card = float(res.m_outer.value.text)
        assert abs(inner_from_curve - inner_from_card) < 5.0
        assert abs(outer_from_curve - outer_from_card) < 5.0


class TestUIErrorHandling:
    """错误处理流程测试。"""

    def test_empty_layers(self, app):
        _, root = app
        from kiln_ht import Layer, KilnParams
        ok = root._run_calc([], KilnParams())
        assert ok is False

    def test_invalid_velocity(self, app):
        _, root = app
        from kiln_ht import Layer, KilnParams
        layers = [Layer(thickness=0.05, k=1.0)]
        params = KilnParams(v_gas=0.0)
        ok = root._run_calc(layers, params)
        assert ok is False