# -*- coding: utf-8 -*-
"""回转窑几何数据结构。"""
from dataclasses import dataclass

@dataclass(frozen=True)
class KilnGeometry:
    inner_diameter: float
    length: float
    def __post_init__(self):
        if self.inner_diameter <= 0 or self.length <= 0:
            raise ValueError("窑内径和窑长必须为正")
    @property
    def inner_radius(self) -> float:
        return self.inner_diameter / 2.0
