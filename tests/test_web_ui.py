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
    assert {"径向基线外壁面温度", "内壁面温度", "总热损失 Q'", "烟气发射率"} <= labels
    # 数值应非空
    for m in app.metric:
        assert m.value


def test_layer_operation_buttons_have_visible_labels(app):
    labels = {button.label for button in app.button}
    assert {"↑ 上移", "↓ 下移", "删除"} <= labels


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
    assert abs(val["径向基线外壁面温度"] - (sol.T_wN - 273.15)) < 0.5
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
    """已删除内置预设（材料数据不准确），侧边栏不应再出现预设下拉。"""
    preset_sb = [s for s in app.selectbox if s.key == "preset_choice"]
    assert not preset_sb, "内置预设已删除，不应出现预设选择框"


def test_edit_layer_name(app):
    """修改层名称后应能反映到计算结果。"""
    # 前 4 个 text_input 分别是 layer_0〜3_name
    text_inputs = [t for t in app.text_input if t.key.endswith("_name")]
    assert text_inputs, "未找到层名称输入框"
    text_inputs[0].set_value("高铝砖").run()
    _click_calc(app)
    assert not app.exception


def test_move_layer_affects_calculation(app):
    """上下移动衬层后，计算结果（径向基线外壁面温度）应随之改变。"""
    from kiln_ht import KilnParams, Layer, solve_wall

    # 给第 0、1 层设置不同的厚度和导热系数，使交换后结果可区分
    # 厚绝缘层在外壁 vs 在内壁，外壁温度不同
    n0 = [t for t in app.text_input if (t.key or "").endswith("_name")]
    n0[0].set_value("A").run()
    n0[1].set_value("B").run()
    # 设置不同厚度：A 厚 200mm k=0.1(绝缘), B 厚 10mm k=45(钢壳)
    thick0 = [n for n in app.number_input if (n.key or "").endswith("_thick")]
    a0 = [n for n in app.number_input if (n.key or "").endswith("_lambda0")]
    thick0[0].set_value(200.0).run()
    a0[0].set_value(0.1).run()
    thick0[1].set_value(10.0).run()
    a0[1].set_value(45.0).run()

    _click_calc(app)
    before = float([m.value for m in app.metric if m.label == "径向基线外壁面温度"][0].split()[0])

    # 下移第 0 层（与第 1 层交换顺序）
    dn = [b for b in app.button if (b.key or "").endswith("_down") and not b.disabled]
    assert dn, "未找到可用的 ⬇ 按钮"
    dn[0].click().run()
    _click_calc(app)

    after = float([m.value for m in app.metric if m.label == "径向基线外壁面温度"][0].split()[0])
    assert before != after, "层顺序调换后径向基线外壁面温度应发生变化"


def test_first_layer_up_disabled(app):
    """第一层的 ⬆ 按钮应禁用（避免越界）。"""
    up0 = [b for b in app.button if (b.key or "").endswith("_up")]
    assert up0, "未找到 ⬆ 按钮"
    assert up0[0].disabled is True, "第一层 ⬆ 应禁用"


def test_last_layer_down_disabled(app):
    """最后一层的 ⬇ 按钮应禁用（避免越界）。"""
    dns = [b for b in app.button if (b.key or "").endswith("_down")]
    assert dns, "未找到 ⬇ 按钮"
    assert dns[-1].disabled is True, "最后一层 ⬇ 应禁用"


# ============ FastAPI API 测试 ============
@pytest.fixture(scope="module")
def api_client():
    from fastapi.testclient import TestClient
    import server
    return TestClient(server.app)


def test_api_layer_k_compat(api_client):
    """API 只传 k 时经 _to_domain 兼容为 k_coef=(k,0,0)。"""
    from server import LayerIn, SolveRequest, _to_domain
    req = SolveRequest(layers=[LayerIn(name="砖", thickness=0.05, k=0.10)])
    layers, _ = _to_domain(req)
    assert layers[0].k_coef == (0.10, 0.0, 0.0)
    assert layers[0].Rc == 0.0


def test_api_layer_k_coef_direct(api_client):
    """API LayerIn 支持直接传 k_coef 与 Rc，经 _to_domain 转换。"""
    from server import LayerIn, SolveRequest, _to_domain
    req = SolveRequest(layers=[LayerIn(
        name="纤维", thickness=0.05, k_coef=[0.08, 1.2e-4, 0.0], Rc=0.005)])
    layers, _ = _to_domain(req)
    assert layers[0].k_coef == (0.08, 1.2e-4, 0.0)
    assert layers[0].Rc == 0.005


def test_api_solve_with_k_coef(api_client):
    """/solve 端点接受 k_coef，返回 k_avg。"""
    resp = api_client.post("/solve", json={
        "layers": [{"name": "纤维", "thickness": 0.15, "k_coef": [0.08, 1.2e-4, 0.0]}],
        "params": {},
    })
    assert resp.status_code == 200
    data = resp.json()
    assert "k_avg" in data
    assert len(data["k_avg"]) == 1


def test_api_solve_with_polynomial_conductivity(api_client):
    """The API's v2 polynomial payload reaches the solver with all a/b/c values."""
    from kiln_ht import ConductivityModel, KilnParams, Layer, solve_wall

    coefficients = [1.8, 0.0000016, -0.00000017]
    payload = {
        "layers": [{
            "name": "polynomial",
            "thickness": 0.10,
            "thermal_conductivity": {
                "mode": "polynomial",
                "temperature_unit": "degC",
                "coefficients": coefficients,
            },
        }],
        "params": {},
    }
    response = api_client.post("/solve", json=payload)
    assert response.status_code == 200, response.text
    result = response.json()

    reference = solve_wall([Layer(
        name="polynomial",
        thickness=0.10,
        k=coefficients[0],
        k_coef=tuple(coefficients),
        conductivity_model=ConductivityModel.polynomial(coefficients, "degC"),
    )], KilnParams())
    constant = solve_wall([Layer(
        name="constant", thickness=0.10, k=coefficients[0]
    )], KilnParams())

    assert result["T_wN"] == pytest.approx(reference.T_wN, abs=1e-6)
    assert result["Qprime"] == pytest.approx(reference.Qprime, rel=1e-9)
    assert result["T_wN"] != pytest.approx(constant.T_wN, abs=1e-4)


def test_api_gas_modes_normalize_composition(api_client):
    from kiln_ht import KilnParams, gas_fractions_for_mode, solve_wall, Layer

    layer_payload = [{"name": "lining", "thickness": 0.10, "k": 1.8}]
    for gas_mode, co2, h2o in (
        ("combustion", 0.18, 0.10),
        ("hot_air", 0.20, 0.08),
    ):
        response = api_client.post("/solve", json={
            "layers": layer_payload,
            "params": {"gas_mode": gas_mode, "CO2": co2, "H2O": h2o},
        })
        assert response.status_code == 200, response.text
        fractions = gas_fractions_for_mode(co2, h2o, mode=gas_mode)
        expected = solve_wall(
            [Layer(name="lining", thickness=0.10, k=1.8)],
            KilnParams(**fractions),
        )
        assert response.json()["Qprime"] == pytest.approx(expected.Qprime, rel=1e-9)
        assert response.json()["T_wN"] == pytest.approx(expected.T_wN, abs=1e-6)
        if gas_mode == "hot_air":
            assert response.json()["eg"] == 0.0


def test_api_solve_with_k_compat(api_client):
    """/solve 端点接受旧 k 字段（兼容）。"""
    resp = api_client.post("/solve", json={
        "layers": [{"name": "砖", "thickness": 0.05, "k": 0.10}],
    })
    assert resp.status_code == 200
    data = resp.json()
    assert data["Qprime"] > 0


def test_web_ui_polynomial_coefficients_reach_solver(app):
    """Changing the Web UI's a/b/c inputs changes the result and matches core."""
    from kiln_ht import ConductivityModel, KilnParams, Layer, solve_wall

    mode = next(
        item for item in app.selectbox
        if item.key == "layer_1_conductivity_mode"
    )
    mode.set_value("polynomial").run()

    for key, value in (
        ("layer_1_a", 1.8),
        ("layer_1_b", 0.0000016),
        ("layer_1_c", -0.00000017),
    ):
        field = next(item for item in app.number_input if item.key == key)
        field.set_value(value).run()

    _click_calc(app)
    assert not app.exception
    assert not app.error, [error.value for error in app.error]
    displayed_outer = float(
        next(metric.value for metric in app.metric
             if metric.label == "径向基线外壁面温度").split()[0]
    )

    coefficients = (1.8, 0.0000016, -0.00000017)
    layers = [Layer(
        name="层1",
        thickness=0.05,
        k=coefficients[0],
        k_coef=coefficients,
        conductivity_model=ConductivityModel.polynomial(coefficients, "degC"),
    )] + [
        Layer(name=f"层{i+1}", thickness=0.05, k=1.0)
        for i in range(1, 4)
    ]
    reference = solve_wall(layers, KilnParams())
    constant = solve_wall([
        Layer(name=f"层{i+1}", thickness=0.05,
              k=coefficients[0] if i == 0 else 1.0)
        for i in range(4)
    ], KilnParams())

    assert displayed_outer == pytest.approx(reference.T_wN - 273.15, abs=0.5)
    assert displayed_outer != pytest.approx(constant.T_wN - 273.15, abs=0.1)


# ============ Streamlit 材料下拉 / 接触热阻 ============
def test_web_ui_material_select(app):
    """衬层应有材料下拉框（用户材料库，无内置材料）。"""
    # 每层应有一个材料选择框（selectbox）；预设已删除，无额外预设框
    mat_sb = [s for s in app.selectbox if (s.key or "").endswith("_material")]
    assert len(mat_sb) == 4   # 每层一个材料下拉
    # 默认应为「自定义」（无任何内置材料）
    assert mat_sb
    assert all(s.value == "自定义" for s in mat_sb)
    # 材料下拉仅含「自定义」（用户库为空时）
    for s in mat_sb:
        assert s.options == ["自定义"], f"不应内置材料：{s.options}"
    # 选择某层后计算应成功
    _click_calc(app)
    assert not app.exception


def test_web_ui_rc_input(app):
    """衬层应有接触热阻输入框（默认 0）。"""
    rc_inputs = [n for n in app.number_input if (n.key or "").endswith("_rc")]
    assert len(rc_inputs) == 4
    assert all(n.value == 0.0 for n in rc_inputs)


def test_web_ui_combustion_composition_is_completed(app):
    from kiln_ht import KilnParams, Layer, gas_fractions_for_mode, solve_wall

    next(item for item in app.number_input if item.key == "CO2").set_value(18.0).run()
    next(item for item in app.number_input if item.key == "H2O").set_value(10.0).run()
    _click_calc(app)
    assert not app.exception
    assert not app.error, [error.value for error in app.error]

    fractions = gas_fractions_for_mode(0.18, 0.10, mode="combustion")
    layers = [Layer(name=f"层{i+1}", thickness=0.05, k=1.0) for i in range(4)]
    expected = solve_wall(layers, KilnParams(**fractions))
    displayed = float(
        next(metric.value for metric in app.metric
             if metric.label == "径向基线外壁面温度").split()[0]
    )
    assert displayed == pytest.approx(expected.T_wN - 273.15, abs=0.5)


def test_web_ui_hot_air_mode_uses_clean_air(app):
    from kiln_ht import KilnParams, Layer, gas_fractions_for_mode, solve_wall

    next(item for item in app.checkbox if item.key == "hot_air_mode").set_value(True).run()
    _click_calc(app)
    assert not app.exception
    assert not app.error, [error.value for error in app.error]

    fractions = gas_fractions_for_mode(0.20, 0.08, mode="hot_air")
    layers = [Layer(name=f"层{i+1}", thickness=0.05, k=1.0) for i in range(4)]
    expected = solve_wall(layers, KilnParams(**fractions))
    displayed = float(
        next(metric.value for metric in app.metric
             if metric.label == "径向基线外壁面温度").split()[0]
    )
    assert displayed == pytest.approx(expected.T_wN - 273.15, abs=0.5)


def test_web_ui_custom_k_coef_fills(app):
    """自定义层 a/b/c 输入应参与计算（而非默认 k=1）。"""
    from kiln_ht import KilnParams, Layer, solve_wall

    # 切到多项式模式后，第 0 层的系数 a 输入框才会出现。
    mode = next(s for s in app.selectbox if s.key == "layer_1_conductivity_mode")
    mode.set_value("polynomial").run()
    a_inputs = [n for n in app.number_input if (n.key or "").endswith("_a")]
    assert a_inputs, "未找到系数 a 输入框"
    a_inputs[0].set_value(0.1).run()
    assert not app.exception

    # 计算成功
    _click_calc(app)
    assert not app.exception
    assert not app.error, [e.value for e in app.error]

    # 关键断言：app 实际计算的外壁温度应等于用 a=0.1 的参考值
    # （若 bug 存在，app 会用默认 k=1 计算，外壁温度显著不同）
    outer_val = float([m.value for m in app.metric if m.label == "径向基线外壁面温度"][0].split()[0])

    ref_layers = [Layer(name=f"层{i+1}", thickness=0.050,
                        k_coef=(0.1 if i == 0 else 1.0, 0.0, 0.0)) for i in range(4)]
    ref_sol = solve_wall(ref_layers, KilnParams())
    ref_outer = ref_sol.T_wN - 273.15
    assert abs(outer_val - ref_outer) < 0.5, \
        f"自定义 a 未生效：app={outer_val:.1f} vs 参考={ref_outer:.1f}"
