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


def test_move_layer_affects_calculation(app):
    """上下移动衬层后，计算结果（外壁面温度）应随之改变。"""
    from kiln_ht import KilnParams, Layer, solve_wall

    # 给第 0、1 层设置不同的厚度和导热系数，使交换后结果可区分
    # 厚绝缘层在外壁 vs 在内壁，外壁温度不同
    n0 = [t for t in app.text_input if (t.key or "").endswith("_name")]
    n0[0].set_value("A").run()
    n0[1].set_value("B").run()
    # 设置不同厚度：A 厚 200mm k=0.1(绝缘), B 厚 10mm k=45(钢壳)
    thick0 = [n for n in app.number_input if (n.key or "").endswith("_thick")]
    k0 = [n for n in app.number_input if (n.key or "").endswith("_k")]
    thick0[0].set_value(200.0).run()
    k0[0].set_value(0.1).run()
    thick0[1].set_value(10.0).run()
    k0[1].set_value(45.0).run()

    _click_calc(app)
    before = float([m.value for m in app.metric if m.label == "外壁面温度"][0].split()[0])

    # 下移第 0 层（与第 1 层交换顺序）
    dn = [b for b in app.button if (b.key or "").endswith("_down") and not b.disabled]
    assert dn, "未找到可用的 ⬇ 按钮"
    dn[0].click().run()
    _click_calc(app)

    after = float([m.value for m in app.metric if m.label == "外壁面温度"][0].split()[0])
    assert before != after, "层顺序调换后外壁面温度应发生变化"


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


def test_api_solve_with_k_compat(api_client):
    """/solve 端点接受旧 k 字段（兼容）。"""
    resp = api_client.post("/solve", json={
        "layers": [{"name": "砖", "thickness": 0.05, "k": 0.10}],
    })
    assert resp.status_code == 200
    data = resp.json()
    assert data["Qprime"] > 0
