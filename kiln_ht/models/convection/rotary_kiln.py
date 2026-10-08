# -*- coding: utf-8 -*-
"""回转窑专用对流关联式预留接口；第二阶段校核。"""
class RotaryKilnCorrelationUnavailable(NotImplementedError):
    pass

def evaluate(*args, **kwargs):
    raise RotaryKilnCorrelationUnavailable("回转窑专用关联式将在第二阶段根据文献/实测数据标定")
