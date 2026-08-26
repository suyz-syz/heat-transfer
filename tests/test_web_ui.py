# -*- coding: utf-8 -*-
"""Streamlit Web GUI 回归测试（基于 streamlit.testing.v1.AppTest，无头模式）。

运行：
    python -m pytest tests/test_web_ui.py -v
"""
import os

import pytest

pytest.importorskip("streamlit")
pytest.importorskip("streamlit.testing.v1")

from streamlit.testing.v1 import AppTest

# AppTest.from_file 的相对路径以调用方文件目录为基准，这里用绝对路径指向仓库根目录的 app.py
_APP_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "app.py")


@pytest.fixture
def app():
    # 每个测试独立构建 AppTest，避免共享 session_state 相互污染
    at = AppTest.from_file(_APP_PATH, default_timeout=60)
    at.run()
    assert not at.exception, f"应用构建异常：{at.exception}"
    return at


def _click_calc(at):
    calc = [b for b in at.button if b.label == "🚀 开始计算"]
    assert calc, "未找到「开始计算」按钮"
    calc[0].click().run()
    return at


def test_app_builds_without_exception(app):
    assert not app.exception


def test_initial_layers(app):
    """初始应加载 4 个默认衬层。"""
    names = [t.value for t in app.text_input]
    assert len(names) == 4


def test_calculation_produces_metrics(app):
    _click_calc(app)
    assert not app.exception
    assert not app.error, [e.value for e in app.error]
    labels = {m.label for m in app.metric}
    assert {"外壁面温度", "内壁面温度", "总热损失 Q'", "烟气发射率"} <= labels
    # 数值应非空
    for m in app.metric:
        assert m.value


def test_calculation_matches_core(app):
    """Web GUI 计算结果应与直接调用核心一致（使用 GUI 默认的 4 层：50mm / k=1.0）。"""
    from kiln_ht import KilnParams, Layer, solve_wall

    _click_calc(app)
    val = {}
    for m in app.metric:
        val[m.label] = float(m.value.split()[0])

    # GUI 默认层：4 层，厚度 50mm，导热系数 1.0，无名称
    layers = [Layer(name=f"层{i+1}", thickness=0.050, k=1.0) for i in range(4)]
    sol = solve_wall(layers, KilnParams())
    assert abs(val["外壁面温度"] - (sol.T_wN - 273.15)) < 0.5
    assert abs(val["内壁面温度"] - (sol.T_w1 - 273.15)) < 0.5
    assert abs(val["烟气发射率"] - sol.eg) < 0.001


def test_add_and_remove_layer(app):
    # 添加衬层
    add_btn = [b for b in app.button if b.label == "➕ 添加衬层"]
    assert add_btn
    add_btn[0].click().run()
    assert len(app.text_input) == 5
    assert not app.exception
    # 删除最后一个衬层
    del_btn = [b for b in app.button if b.key == "layer_4_del"]
    assert del_btn
    del_btn[0].click().run()
    assert len(app.text_input) == 4
    assert not app.exception


def test_preset_loads(app):
    """一键加载预设应重建衬层列表。"""
    assert app.selectbox[0].value == "（手动配置）"
    app.selectbox[0].select("典型2层轻质保温衬体").run()
    assert not app.exception
    assert len(app.text_input) == 2


def test_edit_layer_name(app):
    """修改层名称后应能反映到计算结果。"""
    # 前 4 个 text_input 分别是 layer_0〜3_name
    text_inputs = [t for t in app.text_input if t.key.endswith("_name")]
    assert text_inputs, "未找到层名称输入框"
    text_inputs[0].set_value("高铝砖").run()
    _click_calc(app)
    assert not app.exception
