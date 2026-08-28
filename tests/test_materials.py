# -*- coding: utf-8 -*-
"""材料库单元测试。"""
import math
import pytest

from kiln_ht.materials import MATERIALS, get_material, material_names


def test_materials_present():
    """应内置常用耐火材料。"""
    for name in ["硅酸铝纤维", "轻质砖", "高铝砖", "重质高铝浇注料", "钢壳"]:
        assert name in MATERIALS


def test_materials_k_coef_shape():
    """每个材料 k_coef 为 3 元组且数值有限。"""
    for name, m in MATERIALS.items():
        assert len(m["k_coef"]) == 3
        assert all(math.isfinite(v) for v in m["k_coef"])
        assert m["valid_range_c"][0] < m["valid_range_c"][1]


def test_materials_k_positive_in_range():
    """材料 k(T) 在有效温度范围内为正值。"""
    for name, m in MATERIALS.items():
        lo, hi = m["valid_range_c"]
        a, b, c = m["k_coef"]
        for T in [lo, (lo + hi) / 2, hi]:
            k = a + b * T + c * T * T
            assert k > 0, f"{name} 在 {T}℃ 时 k={k} <= 0"


def test_get_material():
    """get_material 返回与 MATERIALS 一致。"""
    assert get_material("硅酸铝纤维") == MATERIALS["硅酸铝纤维"]


def test_get_material_unknown():
    """未知材料抛 KeyError。"""
    with pytest.raises(KeyError):
        get_material("不存在的材料")


def test_material_names():
    """material_names 返回全部材料名。"""
    assert set(material_names()) == set(MATERIALS.keys())
