# -*- coding: utf-8 -*-
"""用户自定义材料库（JSON 持久化，零第三方依赖）。

不再内置任何材料数据（内置数据不准确，见需求）。材料库由用户自行维护：
用户可将自定义的 k(T) 导热系数（a/b/c）保存到本库，供后续重复选用。

存储格式（JSON）：
    {"材料名": {"k_coef": [a, b, c]}}

存储位置：
- Android：Kivy App 的用户数据目录（App.user_data_dir）
- 桌面 / 服务端：~/.kiln_heat/user_materials.json

本模块保持零第三方依赖：仅在需要解析存储路径时惰性尝试导入 Kivy，
失败（服务端无 Kivy）则回退到用户主目录。
"""

import json
import os
from typing import Dict, List

_STORE_NAME = "user_materials.json"


def materials_path() -> str:
    """返回材料库 JSON 文件的完整路径（按平台选择用户可写目录）。"""
    base = None
    try:
        from kivy.app import App
        app = App.get_running_app()
        if app is not None:
            base = app.user_data_dir
    except Exception:  # noqa: BLE001 —— 无 Kivy 环境（服务端）时回退
        base = None
    if base is None:
        base = os.path.join(os.path.expanduser("~"), ".kiln_heat")
    os.makedirs(base, exist_ok=True)
    return os.path.join(base, _STORE_NAME)


def load_user_materials(path: str = None) -> Dict[str, dict]:
    """读取全部用户材料，返回 {名称: {"k_coef": [a,b,c]}}。"""
    path = path or materials_path()
    if not os.path.exists(path):
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return {}
    result = {}
    for name, val in data.items():
        if isinstance(val, dict) and "k_coef" in val:
            result[name] = val
        elif isinstance(val, (list, tuple)) and len(val) == 3:
            # 兼容旧格式：直接存 [a,b,c]
            result[name] = {"k_coef": [float(v) for v in val]}
    return result


def save_user_material(name: str, k_coef, path: str = None) -> None:
    """保存/覆盖一个用户材料。name 为材料名，k_coef 为 (a,b,c)。"""
    name = (name or "").strip()
    if not name:
        raise ValueError("材料名称不能为空")
    store = load_user_materials(path)
    store[name] = {"k_coef": [float(v) for v in k_coef]}
    path = path or materials_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(store, f, ensure_ascii=False, indent=2)


def material_names(path: str = None) -> List[str]:
    """返回全部用户材料名。"""
    return list(load_user_materials(path).keys())


def get_material(name: str, path: str = None) -> dict:
    """按名称获取材料，未知名称抛 KeyError。"""
    store = load_user_materials(path)
    if name not in store:
        raise KeyError(f"未知材料: {name}（可选：{', '.join(store)}）")
    return store[name]
