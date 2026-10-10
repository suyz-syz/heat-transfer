# -*- coding: utf-8 -*-
"""Tscheng-Watkinson rotary-kiln gas convection correlations.

Reference:
Tscheng, S. H. & Watkinson, A. P. (1979), "Convective heat transfer in a
rotary kiln", The Canadian Journal of Chemical Engineering 57(4), 433-443.
https://doi.org/10.1002/cjce.5450570405

The correlations are restricted to the pilot-kiln regime reported in the
literature. They must not be silently extrapolated to industrial cement kilns.
Thermophysical properties are supplied explicitly to make the property basis
and units auditable.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Mapping

from . import ConvectionEvaluation


@dataclass(frozen=True)
class TschengWatkinsonCorrelation:
    """Published gas-to-wall or gas-to-bed correlation.

    Required properties keys:
      * thermal_conductivity_w_m_k: gas conductivity, W/(m K)
      * kinematic_viscosity_m2_s: gas kinematic viscosity, m²/s
      * filling_degree: solids cross-sectional filling fraction, 0 < f <= 0.17

    The reported regression domain is Re_F=1600..7800, Re_R=20..800.
    The original experimental study used a 0.19 m ID x 2.5 m kiln, hot air
    at 350..590 K, rotation up to 6 rpm and holdup up to 17%. The Re domain
    is enforced; the apparatus/temperature/fill/rotation bounds are also
    checked to prevent accidental industrial-scale extrapolation.
    """
    transfer_path: str = "gas-wall"

    def __post_init__(self) -> None:
        if self.transfer_path not in ("gas-wall", "gas-bed"):
            raise ValueError("transfer_path must be 'gas-wall' or 'gas-bed'")

    @property
    def model_name(self) -> str:
        return "tscheng-watkinson-1979-" + self.transfer_path

    @property
    def source(self) -> str:
        return ("Tscheng & Watkinson (1979), Can. J. Chem. Eng. 57, 433-443; "
                "doi:10.1002/cjce.5450570405")

    @property
    def applicability(self) -> str:
        return ("Pilot non-fired rotary kiln; original study: ID about 0.19 m, "
                "gas 350-590 K, rotation <= 6 rpm, filling <= 0.17; "
                "Re_F=1600-7800 and Re_R=20-800. Not validated for industrial "
                "cement kilns or combustion/radiating gas.")

    def evaluate(self, *, bulk_temperature_k: float, wall_temperature_k: float,
                 velocity_m_s: float, characteristic_diameter_m: float,
                 length_m: float, pressure_pa: float,
                 properties: Mapping[str, float] | None = None,
                 rotation_rpm: float | None = None) -> ConvectionEvaluation:
        props = properties or {}
        required = ("thermal_conductivity_w_m_k", "kinematic_viscosity_m2_s",
                    "filling_degree")
        missing = [key for key in required if key not in props]
        if missing:
            raise ValueError("missing gas properties: " + ", ".join(missing))
        k = float(props["thermal_conductivity_w_m_k"])
        nu = float(props["kinematic_viscosity_m2_s"])
        fill = float(props["filling_degree"])
        values = (bulk_temperature_k, wall_temperature_k, velocity_m_s,
                  characteristic_diameter_m, length_m, pressure_pa, k, nu, fill)
        if not all(math.isfinite(float(v)) for v in values):
            raise ValueError("all Tscheng-Watkinson inputs must be finite")
        if min(bulk_temperature_k, wall_temperature_k, velocity_m_s,
               characteristic_diameter_m, length_m, pressure_pa, k, nu) <= 0:
            raise ValueError("temperatures, velocity, geometry, pressure, k and nu must be positive")
        if not (0.0 < fill <= 0.17):
            raise ValueError("filling_degree must be in (0, 0.17] for the reported pilot domain")
        if rotation_rpm is None or not math.isfinite(rotation_rpm) or not (0.0 <= rotation_rpm <= 6.0):
            raise ValueError("rotation_rpm must be supplied in the reported range [0, 6]")
        if not (350.0 <= bulk_temperature_k <= 590.0):
            raise ValueError("bulk_temperature_k is outside the original 350-590 K test range")
        if abs(characteristic_diameter_m - 0.19) / 0.19 > 0.25:
            raise ValueError("diameter differs by >25% from the original 0.19 m pilot kiln; extrapolation blocked")

        re_flow = velocity_m_s * characteristic_diameter_m / nu
        omega = rotation_rpm * 2.0 * math.pi / 60.0
        re_rotation = characteristic_diameter_m ** 2 * omega / nu
        if not (1600.0 <= re_flow <= 7800.0):
            raise ValueError(f"Re_F={re_flow:.3g} outside published regression range [1600, 7800]")
        if not (20.0 <= re_rotation <= 800.0):
            raise ValueError(f"Re_R={re_rotation:.3g} outside published regression range [20, 800]")

        if self.transfer_path == "gas-wall":
            # Nu_GW = 1.54 Re_F^0.575 Re_R^-0.292
            nu_number = 1.54 * re_flow ** 0.575 * re_rotation ** -0.292
        else:
            # Nu_GS = 0.46 Re_R^0.535 Re_F^0.104 f^-0.341
            nu_number = 0.46 * re_rotation ** 0.535 * re_flow ** 0.104 * fill ** -0.341
        h = nu_number * k / characteristic_diameter_m
        if not math.isfinite(h) or h <= 0.0:
            raise ValueError("correlation returned non-finite/non-positive h")
        return ConvectionEvaluation(
            h_w_m2_k=h,
            model_name=self.model_name,
            source=self.source,
            applicability=self.applicability,
            warnings=("Published pilot-kiln regression; not a cement-kiln validation.",
                      f"Re_F={re_flow:.6g}; Re_R={re_rotation:.6g}; filling={fill:.6g}"),
        )


class TschengWatkinsonGasWall(TschengWatkinsonCorrelation):
    """Tscheng-Watkinson 1979 gas-to-exposed-wall coefficient."""
    def __init__(self) -> None:
        super().__init__(transfer_path="gas-wall")


class TschengWatkinsonGasBed(TschengWatkinsonCorrelation):
    """Tscheng-Watkinson 1979 gas-to-bed coefficient (not gas-to-wall)."""
    def __init__(self) -> None:
        super().__init__(transfer_path="gas-bed")
