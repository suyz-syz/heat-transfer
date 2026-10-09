# -*- coding: utf-8 -*-
"""可插拔的回转窑对流关联式接口。

Gnielinski 是管内流动关联式，不能未经验证直接视为旋转窑内颗粒/
气固两相流的通用模型。旋转筒专用经验式通过 RotaryKilnCorrelationAdapter
注入；实现方必须记录文献来源、适用范围和验证状态。
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Mapping, Protocol, runtime_checkable


@dataclass(frozen=True)
class ConvectionEvaluation:
    """对流模型评估结果；h 单位 W/(m² K)。"""
    h_w_m2_k: float
    model_name: str
    source: str
    applicability: str
    warnings: tuple[str, ...] = ()


@runtime_checkable
class ConvectionModel(Protocol):
    """供未来轴向求解器注入的最小接口。"""

    def evaluate(self, *, bulk_temperature_k: float, wall_temperature_k: float,
                 velocity_m_s: float, characteristic_diameter_m: float,
                 length_m: float, pressure_pa: float,
                 properties: Mapping[str, float] | None = None,
                 rotation_rpm: float | None = None) -> ConvectionEvaluation:
        ...


@dataclass(frozen=True)
class GnielinskiPipeModel:
    """现有 Gnielinski 管内关联式的显式包装；不改变 solve_wall 旧路径。"""

    source: str = "Gnielinski (internal forced convection)"
    applicability: str = (
        "Pipe-flow correlation; verify Reynolds/Prandtl range and kiln-specific "
        "gas-solid/rotation effects before applying to a rotary kiln."
    )

    def evaluate(self, *, bulk_temperature_k: float, wall_temperature_k: float,
                 velocity_m_s: float, characteristic_diameter_m: float,
                 length_m: float, pressure_pa: float,
                 properties: Mapping[str, float] | None = None,
                 rotation_rpm: float | None = None) -> ConvectionEvaluation:
        from ...calc import inner_convection_h

        h = inner_convection_h(
            velocity_m_s, characteristic_diameter_m, length_m,
            0.5 * (bulk_temperature_k + wall_temperature_k),
            P_pa=pressure_pa,
        )
        return ConvectionEvaluation(
            h_w_m2_k=h,
            model_name="gnielinski-pipe",
            source=self.source,
            applicability=self.applicability,
            warnings=(
                "Not a rotary-kiln-specific correlation; validate against kiln data.",
            ),
        )


@dataclass(frozen=True)
class RotaryKilnCorrelationAdapter:
    """Li/Tscheng-Watkinson 等回转筒关联式的可插拔适配器。

    本适配器不内置或臆造任何文献公式。调用方提供已核验的 evaluator，
    并填写准确文献出处与适用范围；evaluator 返回 h [W/(m² K)]。
    """
    model_name: str
    source: str
    applicability: str
    evaluator: Callable[..., float]

    def evaluate(self, *, bulk_temperature_k: float, wall_temperature_k: float,
                 velocity_m_s: float, characteristic_diameter_m: float,
                 length_m: float, pressure_pa: float,
                 properties: Mapping[str, float] | None = None,
                 rotation_rpm: float | None = None) -> ConvectionEvaluation:
        if not self.source.strip() or not self.applicability.strip():
            raise ValueError("旋转筒关联式必须注明文献来源和适用范围")
        h = float(self.evaluator(
            bulk_temperature_k=bulk_temperature_k,
            wall_temperature_k=wall_temperature_k,
            velocity_m_s=velocity_m_s,
            characteristic_diameter_m=characteristic_diameter_m,
            length_m=length_m,
            pressure_pa=pressure_pa,
            properties=properties or {},
            rotation_rpm=rotation_rpm,
        ))
        if not (h > 0.0 and h < float("inf")):
            raise ValueError("回转窑对流关联式必须返回有限正值 h [W/(m² K)]")
        return ConvectionEvaluation(
            h_w_m2_k=h,
            model_name=self.model_name,
            source=self.source,
            applicability=self.applicability,
        )


__all__ = [
    "ConvectionEvaluation",
    "ConvectionModel",
    "GnielinskiPipeModel",
    "RotaryKilnCorrelationAdapter",
]
