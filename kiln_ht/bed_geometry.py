"""Ideal circular kiln bed geometry helpers (P2).

The model assumes a stationary, horizontal, flat bed surface in an ideal circular
cylinder. Areas are geometric per-unit-axial-length quantities; this module does
not estimate heat-transfer coefficients or account for rolling/cascading beds.
"""
from __future__ import annotations

import math
from typing import Dict, Optional

ASSUMPTIONS = (
    "ideal circular cylinder; stationary bed with a horizontal flat free surface; "
    "uniform axial fill; covered wall arc is fully in bed contact; no lifters, "
    "rolling/cascading, slumping, or three-dimensional effects; fill fraction "
    "describes the bed-envelope cross-section, not solids mass fraction"
)


def filling_fraction_from_angle(beta_rad: float) -> float:
    """Return circular-segment area fraction for a central angle in [0, 2*pi]."""
    beta = float(beta_rad)
    if not math.isfinite(beta) or beta < 0.0 or beta > 2.0 * math.pi:
        raise ValueError("filling angle beta_rad must be finite and in [0, 2*pi]")
    if beta == 0.0:
        return 0.0
    if beta == 2.0 * math.pi:
        return 1.0
    return (beta - math.sin(beta)) / (2.0 * math.pi)


def filling_angle_from_fraction(fraction: float, *, tolerance: float = 1.0e-13) -> float:
    """Invert the monotone circular-segment relation by bounded bisection."""
    f = float(fraction)
    if not math.isfinite(f) or f < 0.0 or f > 1.0:
        raise ValueError("filling_fraction must be finite and in [0, 1]")
    if not math.isfinite(tolerance) or tolerance <= 0.0:
        raise ValueError("tolerance must be finite and positive")
    if f == 0.0:
        return 0.0
    if f == 1.0:
        return 2.0 * math.pi
    lo, hi = 0.0, 2.0 * math.pi
    for _ in range(100):
        mid = 0.5 * (lo + hi)
        if filling_fraction_from_angle(mid) < f:
            lo = mid
        else:
            hi = mid
        if hi - lo <= tolerance:
            break
    return 0.5 * (lo + hi)


def calculate_bed_geometry(
    inner_diameter_m: float,
    *,
    filling_fraction: Optional[float] = None,
    filling_angle_deg: Optional[float] = None,
) -> Dict:
    """Resolve fill fraction/angle and return arc and cross-section geometry.

    wall_bed_contact_per_length_m is covered arc length R*beta (m²/m = m).
    gas_bed_area_per_length_m is the bed free-surface chord length 2R*sin(beta/2)
    (m²/m = m), i.e. the gas-bed interface area per unit kiln length.
    """
    diameter = float(inner_diameter_m)
    if not math.isfinite(diameter) or diameter <= 0.0:
        raise ValueError("inner_diameter_m must be finite and positive")
    if (filling_fraction is None) == (filling_angle_deg is None):
        raise ValueError("provide exactly one of filling_fraction or filling_angle_deg")
    if filling_angle_deg is not None:
        deg = float(filling_angle_deg)
        if not math.isfinite(deg) or deg < 0.0 or deg > 360.0:
            raise ValueError("filling_angle_deg must be finite and in [0, 360]")
        beta = math.radians(deg)
        fraction = filling_fraction_from_angle(beta)
        source = "filling_angle_deg"
        input_value = deg
    else:
        fraction = float(filling_fraction)
        beta = filling_angle_from_fraction(fraction)
        source = "filling_fraction"
        input_value = fraction

    radius = diameter / 2.0
    arc = radius * beta
    chord = 2.0 * radius * math.sin(beta / 2.0)
    # Explicit endpoint values avoid floating point residue at full/empty fill.
    if fraction == 0.0:
        arc = chord = 0.0
    elif fraction == 1.0:
        arc, chord = 2.0 * math.pi * radius, 0.0
    return {
        "enabled": True,
        "status": "provisional_geometry_estimate",
        "source": source,
        "input_value": input_value,
        "inner_diameter_m": diameter,
        "filling_fraction": fraction,
        "filling_angle_rad": beta,
        "filling_angle_deg": math.degrees(beta),
        "wall_bed_contact_per_length_m_computed": arc,
        "gas_bed_area_per_length_m_computed": chord,
        "wall_bed_contact_per_length_m_effective": arc,
        "gas_bed_area_per_length_m_effective": chord,
        "wall_bed_area_source": "geometry",
        "gas_bed_area_source": "geometry",
        "assumptions": ASSUMPTIONS,
    }


def resolve_bed_geometry(
    config: Optional[dict],
    inner_diameter_m: float,
    *,
    gas_bed_area_per_length_m: Optional[float] = None,
    wall_bed_contact_per_length_m: Optional[float] = None,
):
    """Resolve opt-in config and independent manual area overrides.

    Disabled/missing config leaves legacy area inputs untouched and returns
    metadata with explicit n/a values.
    """
    if config is None or not config.get("enabled", False):
        return gas_bed_area_per_length_m, wall_bed_contact_per_length_m, {
            "enabled": False,
            "status": "disabled_legacy_inputs",
            "source": "manual" if (gas_bed_area_per_length_m is not None or wall_bed_contact_per_length_m is not None) else "n/a",
            "input_value": None,
            "inner_diameter_m": None,
            "filling_fraction": None,
            "filling_angle_rad": None,
            "filling_angle_deg": None,
            "gas_bed_area_per_length_m_computed": None,
            "wall_bed_contact_per_length_m_computed": None,
            "gas_bed_area_per_length_m_effective": gas_bed_area_per_length_m,
            "wall_bed_contact_per_length_m_effective": wall_bed_contact_per_length_m,
            "gas_bed_area_source": "manual" if gas_bed_area_per_length_m is not None else "n/a",
            "wall_bed_area_source": "manual" if wall_bed_contact_per_length_m is not None else "n/a",
            "assumptions": "geometry helper disabled; legacy/manual areas are used",
        }
    if not isinstance(config, dict):
        raise ValueError("bed_geometry must be an object")
    mode = config.get("input_mode", "filling_fraction")
    if mode == "filling_fraction":
        geometry = calculate_bed_geometry(
            inner_diameter_m, filling_fraction=config.get("filling_fraction")
        )
    elif mode == "filling_angle":
        geometry = calculate_bed_geometry(
            inner_diameter_m, filling_angle_deg=config.get("filling_angle_deg")
        )
    else:
        raise ValueError("bed_geometry.input_mode must be 'filling_fraction' or 'filling_angle'")

    for name, value in (
        ("gas_bed_area_per_length_m", gas_bed_area_per_length_m),
        ("wall_bed_contact_per_length_m", wall_bed_contact_per_length_m),
    ):
        if value is not None and (not math.isfinite(float(value)) or float(value) < 0.0):
            raise ValueError(f"{name} manual override must be finite and non-negative")
    gas_effective = (
        float(gas_bed_area_per_length_m)
        if gas_bed_area_per_length_m is not None
        else geometry["gas_bed_area_per_length_m_computed"]
    )
    wall_effective = (
        float(wall_bed_contact_per_length_m)
        if wall_bed_contact_per_length_m is not None
        else geometry["wall_bed_contact_per_length_m_computed"]
    )
    geometry["gas_bed_area_per_length_m_effective"] = gas_effective
    geometry["wall_bed_contact_per_length_m_effective"] = wall_effective
    geometry["gas_bed_area_source"] = "manual_override" if gas_bed_area_per_length_m is not None else "geometry"
    geometry["wall_bed_area_source"] = "manual_override" if wall_bed_contact_per_length_m is not None else "geometry"
    if geometry["filling_fraction"] == 1.0 and gas_effective == 0.0:
        geometry["applicability"] = "invalid_for_three_phase_plug_flow"
    else:
        geometry["applicability"] = "geometry_resolved"
    return gas_effective, wall_effective, geometry
