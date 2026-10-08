# -*- coding: utf-8 -*-
"""用户自定义物性表接口（第一阶段基础版）。"""
from bisect import bisect_left
from dataclasses import dataclass

@dataclass(frozen=True)
class PropertyTable:
    temperatures: tuple
    values: tuple
    def __post_init__(self):
        if len(self.temperatures) != len(self.values) or len(self.temperatures) < 2:
            raise ValueError("温度表至少需要两个点且长度一致")
        if any(self.temperatures[i] >= self.temperatures[i+1] for i in range(len(self.temperatures)-1)):
            raise ValueError("温度表必须严格递增")
    def evaluate(self, T: float) -> float:
        if T < self.temperatures[0] or T > self.temperatures[-1]:
            raise ValueError("T 超出用户物性表范围")
        i = bisect_left(self.temperatures, T)
        if i == 0: return self.values[0]
        if i == len(self.temperatures): return self.values[-1]
        t0,t1 = self.temperatures[i-1],self.temperatures[i]
        v0,v1 = self.values[i-1],self.values[i]
        return v0+(v1-v0)*(T-t0)/(t1-t0)
