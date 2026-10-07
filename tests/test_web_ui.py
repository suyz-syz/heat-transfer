# -*- coding: utf-8 -*-
"""Streamlit Web GUI 回归测试（基于 streamlit.testing.v1.AppTest，无头模式）。

运行：
    python -m pytest tests/test_web_ui.py -v

说明：v2 重构后主区改为「衬层配置 / 计算结果 / 温度曲线」三分区视图，
侧边栏为可折叠的「工况参数 / 材料库 / 帮助」三区块。衬层仍以
``layer_{uid}_{字段}`` 作为控件 key，故测试按 key 前缀筛选控件，
不再依赖「第 N 个 number_input」这类位置假设。
"""
import os

import pytest

pytest.importorskip("streamlit")
pytest.importorskip("streamlit.testing.v1")

from streamlit.testing.v1 import AppTest

# AppTest.from_file 的相对路径以调用方文件目录为基准，这里用绝对路径指向仓库根目录的 app.py
_APP_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "app.py")

CALC_LABEL = "🚀 开始计算"


@pytest.fixture
def app():
    # 每个测试独立构建 AppTest，避免共享 session_state 相互污染
    at = AppTest.from_file(_APP_PATH, default_timeout=90)
    at.run()
    assert not at.exception, f"应用构建异常：{at.exception}"
    return at


# ---------- 控件筛选工具 ----------
def _layer_widgets(at, element, suffix):
    """按 key 筛选衬层控件：key 形如 layer_{uid}_{suffix}。"""
    return [w for w in getattr(at, element)
            if (w.key or "").startswith("layer_") and (w.key or "").endswith(suffix)]


def _click_calc(at):
    calc = [b for b in at.button if b.label == CALC_LABEL]
    assert calc, "未找到「开始计算」按钮"
    calc[0].click().run()
    return at


def _metric_value(at, keyword):
    """按关键词取指标卡数值（标签含 emoji 前缀，用包含匹配）。"""
    hit = [m for m in at.metric if keyword in m.label]
    assert hit, f"未找到指标「{keyword}」，现有：{[m.label for m in at.metric]}"
    return float(hit[0].value.split()[0])


def _view(at):
    return at.segmented_control[0].value


# ---------- 基础构建 ----------
def test_app_builds_without_exception(app):
    assert not app.exception


def test_initial_view_is_layer_config(app):
    """默认视图应为「衬层配置」。"""
    assert _view(app) == "衬层配置"


def test_initial_layers(app):
    """初始应加载 4 个默认衬层。"""
    names = _layer_widgets(app, "text_input", "_name")
    assert len(names) == 4


def test_sidebar_has_three_collapsible_sections(app):
    """侧边栏应有「工况参数 / 材料库 / 帮助」三个可折叠区块。"""
    labels = [e.label for e in app.sidebar.expander]
    for kw in ("工况参数", "材料库", "帮助"):
        assert any(kw in lb for lb in labels), f"侧边栏缺少「{kw}」区块：{labels}"


# ---------- 计算与结果 ----------
def test_calculation_produces_metrics(app):
    _click_calc(app)
    assert not app.exception
    assert not app.error, [e.value for e in app.error]
    labels = " ".join(m.label for m in app.metric)
    for kw in ("外壁面温度", "内壁面温度", "总热损失 Q'", "烟气发射率"):
        assert kw in labels, f"缺少指标「{kw}」"
    for m in app.metric:
        assert m.value


def test_auto_switch_to_results_after_calc(app):
    """计算完成后应自动切换到「计算结果」视图。"""
    assert _view(app) == "衬层配置"
    _click_calc(app)
    assert _view(app) == "计算结果"


def test_calculation_matches_core(app):
    """Web GUI 计算结果应与直接调用核心一致（默认 4 层：50mm / k=1.0）。"""
    from kiln_ht import KilnParams, Layer, solve_wall

    _click_calc(app)
    # GUI 默认层：4 层，厚度 50mm，导热系数 1.0
    layers = [Layer(name=f"层{i+1}", thickness=0.050, k=1.0) for i in range(4)]
    sol = solve_wall(layers, KilnParams())
    assert abs(_metric_value(app, "外壁面温度") - (sol.T_wN - 273.15)) < 0.5
    assert abs(_metric_value(app, "内壁面温度") - (sol.T_w1 - 273.15)) < 0.5
    assert abs(_metric_value(app, "烟气发射率") - sol.eg) < 0.001
    assert abs(_metric_value(app, "总热损失 Q'") - sol.Qprime) < 1.0


def test_results_persist_across_view_switch(app):
    """切到「温度曲线」再切回，结果仍在（不会因切视图而丢失）。"""
    _click_calc(app)
    app.segmented_control[0].set_value("温度曲线").run()
    assert not app.exception
    assert not app.metric, "温度曲线视图不应显示指标卡"
    app.segmented_control[0].set_value("计算结果").run()
    assert _metric_value(app, "外壁面温度") > 0


# ---------- 衬层编辑 ----------
def test_add_and_remove_layer(app):
    add_btn = [b for b in app.button if b.label == "➕ 添加衬层"]
    assert add_btn
    add_btn[0].click().run()
    assert len(_layer_widgets(app, "text_input", "_name")) == 5
    assert not app.exception
    del_btn = [b for b in app.button if b.key == "layer_4_del"]
    assert del_btn
    del_btn[0].click().run()
    assert len(_layer_widgets(app, "text_input", "_name")) == 4
    assert not app.exception


def test_edit_layer_name(app):
    """修改层名称后应能反映到计算结果。"""
    text_inputs = _layer_widgets(app, "text_input", "_name")
    assert text_inputs, "未找到层名称输入框"
    text_inputs[0].set_value("高铝砖").run()
    _click_calc(app)
    assert not app.exception
    assert app.session_state["layers"][0]["name"] == "高铝砖"


def test_move_layer_affects_calculation(app):
    """上下移动衬层后，计算结果（外壁面温度）应随之改变。"""
    n0 = _layer_widgets(app, "text_input", "_name")
    n0[0].set_value("A").run()
    n0[1].set_value("B").run()
    # A 厚 200mm k=0.1（隔热），B 厚 10mm k=45（钢壳）
    thick0 = _layer_widgets(app, "number_input", "_thick")
    a0 = _layer_widgets(app, "number_input", "_a")
    thick0[0].set_value(200.0).run()
    a0[0].set_value(0.1).run()
    thick0[1].set_value(10.0).run()
    a0[1].set_value(45.0).run()

    # 先点击计算获取基准结果
    _click_calc(app)
    before = _metric_value(app, "外壁面温度")

    # 切回衬层配置视图，找到并点击下移按钮
    app.segmented_control[0].set_value("衬层配置").run()
    dn = [b for b in app.button
          if (b.key or "").endswith("_down") and not b.disabled
          and (b.key or "").startswith("layer_")]
    assert dn, "未找到可用的 ⬇ 按钮"
    dn[0].click().run()
    assert not app.exception
    _click_calc(app)

    after = _metric_value(app, "外壁面温度")
    assert before != after, "层顺序调换后外壁面温度应发生变化"


def test_first_layer_up_disabled(app):
    """第一层的 ⬆ 按钮应禁用（避免越界）。"""
    up0 = _layer_widgets(app, "button", "_up")
    assert up0, "未找到 ⬆ 按钮"
    assert up0[0].disabled is True, "第一层 ⬆ 应禁用"


def test_last_layer_down_disabled(app):
    """最后一层的 ⬇ 按钮应禁用（避免越界）。"""
    dns = _layer_widgets(app, "button", "_down")
    assert dns, "未找到 ⬇ 按钮"
    assert dns[-1].disabled is True, "最后一层 ⬇ 应禁用"


def test_web_ui_material_select(app):
    """衬层应有材料下拉框（用户材料库，无内置材料）。"""
    mat_sb = _layer_widgets(app, "selectbox", "_material")
    assert len(mat_sb) == 4
    assert all(s.value == "自定义" for s in mat_sb)
    for s in mat_sb:
        assert s.options == ["自定义"], f"不应内置材料：{s.options}"
    _click_calc(app)
    assert not app.exception


def test_web_ui_rc_input(app):
    """衬层应有接触热阻输入框（默认 0）。"""
    rc_inputs = _layer_widgets(app, "number_input", "_rc")
    assert len(rc_inputs) == 4
    assert all(n.value == 0.0 for n in rc_inputs)


def test_web_ui_custom_k_coef_fills(app):
    """自定义层 a/b/c 输入应参与计算（而非默认 k=1）。"""
    from kiln_ht import KilnParams, Layer, solve_wall

    a_inputs = _layer_widgets(app, "number_input", "_a")
    assert a_inputs, "未找到系数 a 输入框"
    a_inputs[0].set_value(0.1).run()
    assert not app.exception
    _click_calc(app)
    assert not app.exception
    assert not app.error, [e.value for e in app.error]

    # 关键断言：实际计算的外壁温度应等于 a=0.1 的参考值
    outer_val = _metric_value(app, "外壁面温度")
    ref_layers = [Layer(name=f"层{i+1}", thickness=0.050,
                        k_coef=(0.1 if i == 0 else 1.0, 0.0, 0.0)) for i in range(4)]
    ref_sol = solve_wall(ref_layers, KilnParams())
    assert abs(outer_val - (ref_sol.T_wN - 273.15)) < 0.5, \
        f"自定义 a 未生效：app={outer_val:.1f} vs 参考={ref_sol.T_wN - 273.15:.1f}"


# ---------- 视图 / 模式开关 ----------
def test_slim_mode_hides_bc_columns(app):
    """精简模式应隐藏 b/c 输入，只保留 a。"""
    assert len(_layer_widgets(app, "number_input", "_b")) == 4
    app.toggle(key="slim_mode").set_value(True).run()
    assert not app.exception
    assert len(_layer_widgets(app, "number_input", "_b")) == 0
    assert len(_layer_widgets(app, "number_input", "_a")) == 4
    # 精简模式下 ⬆⬇🗑 收进弹出面板
    assert not _layer_widgets(app, "button", "_up")


def test_auto_calc_toggle(app):
    """打开「自动计算」后，改参数即自动出结果（无需点按钮）。"""
    assert not app.metric
    app.toggle(key="auto_calc").set_value(True).run()
    assert not app.exception
    assert not app.error, [e.value for e in app.error]
    assert _metric_value(app, "外壁面温度") > 0

    # 改一个工况参数，结果应自动更新
    before = _metric_value(app, "外壁面温度")
    app.number_input(key="T_env_C").set_value(60.0).run()
    after = _metric_value(app, "外壁面温度")
    assert after > before, "环境温度升高后外壁温度应上升"


def test_curve_view_after_calc(app):
    """温度曲线视图应能正常渲染（不抛异常）。"""
    _click_calc(app)
    app.segmented_control[0].set_value("温度曲线").run()
    assert not app.exception
    assert not app.error, [e.value for e in app.error]
    x_mm, T_c = app.session_state["last_result"][3], app.session_state["last_result"][4]
    assert len(x_mm) == len(T_c) > 10
    assert x_mm[0] == 0.0


# ---------- 预设工况 ----------
def test_preset_loads_conditions_only(app):
    """常用工况一键加载：只写工况参数，不改变衬层结构。"""
    layers_before = [dict(r) for r in app.session_state["layers"]]
    app.selectbox(key="preset_choice").select("预分解窑 · 烧成带（Φ4.8×74m）").run()
    btn = [b for b in app.button if b.label == "载入所选工况"]
    assert btn, "未找到「载入所选工况」按钮"
    btn[0].click().run()
    assert not app.exception
    assert app.number_input(key="T_gas_C").value == 1450.0
    assert app.number_input(key="L_char").value == 4.8
    # 衬层结构保持不变（不含内置材料数据）
    assert [dict(r) for r in app.session_state["layers"]] == layers_before


# ---------- 材料库 ----------
def test_material_library_save_and_delete(app, monkeypatch, tmp_path):
    """材料库区块应能新增与删除材料，且衬层下拉随之刷新。"""
    import kiln_ht.materials as mat_mod
    path = str(tmp_path / "user_materials.json")
    monkeypatch.setattr(mat_mod, "materials_path", lambda: path)

    app.text_input(key="new_mat_name").set_value("测试浇注料").run()
    app.number_input(key="new_mat_a").set_value(1.2).run()
    app.number_input(key="new_mat_b").set_value(4.5e-4).run()
    submit = [b for b in app.button if b.label == "保存到材料库"]
    assert submit
    submit[0].click().run()
    assert not app.exception

    from kiln_ht.materials import load_user_materials
    assert "测试浇注料" in load_user_materials(path)
    # 衬层材料下拉应包含新材料
    opts = _layer_widgets(app, "selectbox", "_material")[0].options
    assert "测试浇注料" in opts

    # 删除
    dele = [b for b in app.button if b.key == "mat_del_测试浇注料"]
    assert dele, "未找到材料删除按钮"
    dele[0].click().run()
    assert not app.exception
    assert "测试浇注料" not in load_user_materials(path)


# ---------- FastAPI API 测试 ----------
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
