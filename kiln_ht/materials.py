# -*- coding: utf-8 -*-
"""耐火材料 k(T) 导热系数库（工程数据，来自耐火材料手册/国标）。

k(T) = a + b·T + c·T²（T 单位 ℃）。valid_range_c 为有效温度范围 (℃)。
数据来源：耐火材料手册、GB/T 标准及主流产品技术参数。
"""

from typing import Dict, List, Tuple

MATERIALS: Dict[str, dict] = {
    "硅酸铝纤维":      {"k_coef": (0.08, 1.2e-4, 0.0),     "valid_range_c": (0, 1200)},
    "轻质砖":          {"k_coef": (0.32, 1.8e-4, 0.0),     "valid_range_c": (0, 1200)},
    "高铝砖":          {"k_coef": (1.05, 1.5e-4, 0.0),     "valid_range_c": (0, 1400)},
    "重质高铝浇注料":   {"k_coef": (1.2, 4.5e-4, -1.2e-7),   "valid_range_c": (0, 1400)},
    "钢壳":            {"k_coef": (45.0, 0.0, 0.0),        "valid_range_c": (0, 500)},
}


def get_material(name: str) -> dict:
    """按名称获取材料，未知名称抛 KeyError。"""
    if name not in MATERIALS:
        raise KeyError(f"未知材料: {name}（可选：{', '.join(MATERIALS)}）")
    return MATERIALS[name]


def material_names() -> List[str]:
    """返回全部材料名。"""
    return list(MATERIALS.keys())