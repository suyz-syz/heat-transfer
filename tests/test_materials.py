# -*- coding: utf-8 -*-
"""用户自定义材料库单元测试（无内置材料，纯用户持久化）。"""
import json
import math
import os

import pytest

from kiln_ht.materials import (
    get_material,
    load_user_materials,
    material_names,
    save_user_material,
)


@pytest.fixture
def tmp_store(tmp_path):
    """临时 JSON 文件路径，避免污染真实用户数据。"""
    return str(tmp_path / "user_materials.json")


def test_no_builtin_materials(tmp_store):
    """应不内置任何材料（空库）。"""
    assert load_user_materials(tmp_store) == {}
    assert material_names(tmp_store) == []


def test_save_and_load_roundtrip(tmp_store):
    """保存自定义材料后应能读回相同 k_coef。"""
    save_user_material("我的浇注料", (1.2, 4.5e-4, -1.2e-7), path=tmp_store)
    store = load_user_materials(tmp_store)
    assert "我的浇注料" in store
    assert store["我的浇注料"]["k_coef"] == [1.2, 4.5e-4, -1.2e-7]
    assert "我的浇注料" in material_names(tmp_store)


def test_get_material(tmp_store):
    save_user_material("高铝砖X", (1.05, 1.5e-4, 0.0), path=tmp_store)
    m = get_material("高铝砖X", path=tmp_store)
    assert m["k_coef"][0] == pytest.approx(1.05)


def test_get_material_unknown(tmp_store):
    with pytest.raises(KeyError):
        get_material("不存在的材料", path=tmp_store)


def test_save_empty_name_rejected(tmp_store):
    with pytest.raises(ValueError):
        save_user_material("  ", (1.0, 0.0, 0.0), path=tmp_store)


def test_save_overwrites(tmp_store):
    save_user_material("材料A", (1.0, 0.0, 0.0), path=tmp_store)
    save_user_material("材料A", (2.0, 1e-4, 0.0), path=tmp_store)
    store = load_user_materials(tmp_store)
    assert len(store) == 1
    assert store["材料A"]["k_coef"] == [2.0, 1e-4, 0.0]


def test_load_corrupted_json_returns_empty(tmp_path):
    """损坏的 JSON 文件应返回空库而非崩溃。"""
    p = tmp_path / "user_materials.json"
    p.write_text("{ not valid json", encoding="utf-8")
    assert load_user_materials(str(p)) == {}
