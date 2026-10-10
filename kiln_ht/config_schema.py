# -*- coding: utf-8 -*-
"""Shared, dependency-light configuration schema and legacy migration helpers.

Canonical units: temperatures K at API/domain boundaries; lengths m; pressure bar;
velocity m/s; gas fractions mole fractions in [0, 1]; conductivity W/(m K).
Legacy Layer.k / k_coef and Rc names remain readable.
"""
from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any, Dict, Mapping, Optional


SCHEMA_VERSION = 2
GAS_COMPONENTS = ("CO2", "H2O", "N2", "O2")


def _finite_number(value: Any, name: str) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} 必须为数值") from exc
    if not math.isfinite(result):
        raise ValueError(f"{name} 必须为有限数值")
    return result


def normalize_layer(raw: Mapping[str, Any]) -> Dict[str, Any]:
    """Normalize a legacy or v2 layer to canonical SI-oriented mapping."""
    if not isinstance(raw, Mapping):
        raise ValueError("layer 必须是对象")
    result = dict(raw)
    result["name"] = str(result.get("name") or "层")
    # Legacy thickness is already metres in Layer/API; explicit v2 key wins.
    if "thickness_m" in result:
        thickness_m = result["thickness_m"]
    elif "thickness" in result:
        thickness_m = result["thickness"]
    else:
        thickness_m = _finite_number(result.get("thickness_mm", 50.0), "thickness_mm") / 1000.0
    result["thickness_m"] = _finite_number(thickness_m, "thickness_m")
    result["contact_resistance_m2_k_w"] = _finite_number(
        result.get("contact_resistance_m2_k_w", result.get("Rc", 0.0)), "Rc"
    )
    tc = result.get("thermal_conductivity")
    if isinstance(tc, Mapping):
        mode = str(tc.get("mode", "constant")).lower()
        if mode == "constant":
            k = _finite_number(tc.get("value", result.get("k", 1.0)), "k")
            result["thermal_conductivity"] = {"mode": "constant", "value": k}
        elif mode == "polynomial":
            coef = tc.get("coefficients", result.get("k_coef", [result.get("k", 1.0), 0.0, 0.0]))
            if not isinstance(coef, (list, tuple)) or len(coef) != 3:
                raise ValueError("多项式导热系数 coefficients 必须含 3 个系数")
            result["thermal_conductivity"] = {
                "mode": "polynomial",
                "temperature_unit": tc.get("temperature_unit", "degC"),
                "coefficients": [_finite_number(v, f"coefficients[{i}]") for i, v in enumerate(coef)],
            }
        elif mode == "table":
            points = tc.get("points", [])
            if len(points) < 2:
                raise ValueError("插值表至少需要两个温度-导热系数点")
            normalized = []
            for i, point in enumerate(points):
                if isinstance(point, Mapping):
                    t, k = point.get("temperature_k"), point.get("conductivity_w_m_k")
                elif isinstance(point, (list, tuple)) and len(point) == 2:
                    t, k = point
                else:
                    raise ValueError(f"第 {i+1} 个插值点格式无效")
                normalized.append([_finite_number(t, "temperature_k"), _finite_number(k, "conductivity")])
            if any(normalized[i][0] >= normalized[i+1][0] for i in range(len(normalized)-1)):
                raise ValueError("插值表温度必须严格递增且不能重复")
            if any(k <= 0 for _, k in normalized):
                raise ValueError("插值表导热系数必须全部为正")
            result["thermal_conductivity"] = {"mode": "table", "points": normalized}
        else:
            raise ValueError(f"不支持的导热系数模式: {mode}")
    else:
        # Backward compatibility: explicit k_coef takes precedence over k.
        coef = result.get("k_coef")
        if coef is not None:
            if not isinstance(coef, (list, tuple)) or len(coef) != 3:
                raise ValueError("k_coef 必须含 3 个系数")
            result["thermal_conductivity"] = {
                "mode": "polynomial", "temperature_unit": "degC",
                "coefficients": [_finite_number(v, f"k_coef[{i}]") for i, v in enumerate(coef)],
            }
        else:
            result["thermal_conductivity"] = {
                "mode": "constant", "value": _finite_number(result.get("k", 1.0), "k")
            }
    return result


def normalize_config(raw: Mapping[str, Any]) -> Dict[str, Any]:
    """Migrate supported legacy JSON/YAML-like mappings to schema version 2."""
    if not isinstance(raw, Mapping):
        raise ValueError("配置根节点必须是对象")
    data = dict(raw)
    params = dict(data.get("params") or {})
    # Legacy API/UI names are canonical aliases; do not silently change units.
    aliases = {"T_gas_K": "T_gas", "T_env_K": "T_env", "pressure_bar": "P_total",
               "inner_diameter_m": "L_char", "kiln_length_m": "L_kiln"}
    for new, old in aliases.items():
        if new in params and old not in params:
            params[old] = params.pop(new)
    layers_raw = data.get("layers", data.get("lining_layers", []))
    if not isinstance(layers_raw, list):
        raise ValueError("layers 必须是数组")
    normalized_layers = [normalize_layer(layer) for layer in layers_raw]
    for key in ("N_total", "T_gas", "T_env", "v_gas", "L_char", "L_kiln", "P_total"):
        if key in params:
            params[key] = _finite_number(params[key], key)
    for key in ("N_total", "L_char", "L_kiln", "P_total", "T_gas", "T_env", "v_gas"):
        if key in params and params[key] <= 0:
            raise ValueError(f"{key} 必须大于 0")
    if "N_total" in params and int(params["N_total"]) != params["N_total"]:
        raise ValueError("N_total 必须为整数")
    params["N_total"] = int(params.get("N_total", 100))
    fractions = []
    for key in GAS_COMPONENTS:
        if key in params:
            value = _finite_number(params[key], key)
            if value < 0 or value > 1:
                raise ValueError(f"{key} 摩尔分数必须在 [0, 1] 内")
            params[key] = value
            fractions.append(value)
    if fractions and any(key not in params for key in GAS_COMPONENTS):
        # Only enforce closure when all four species were explicitly supplied.
        pass
    if all(key in params for key in GAS_COMPONENTS) and abs(sum(params[k] for k in GAS_COMPONENTS)-1.0) > 1e-8:
        raise ValueError("CO2/H2O/N2/O2 摩尔分数之和必须为 1")
    for i, layer in enumerate(normalized_layers):
        if layer["thickness_m"] <= 0:
            raise ValueError(f"第 {i+1} 层厚度必须大于 0")
        if layer["contact_resistance_m2_k_w"] < 0:
            raise ValueError(f"第 {i+1} 层接触热阻不能为负")
        tc = layer["thermal_conductivity"]
        if tc["mode"] == "constant" and tc["value"] <= 0:
            raise ValueError(f"第 {i+1} 层导热系数必须为正")
        if tc["mode"] == "polynomial" and tc["temperature_unit"] not in ("degC", "K"):
            raise ValueError("多项式温度单位必须为 degC 或 K")
    data["schema_version"] = SCHEMA_VERSION
    data["params"] = params
    data["layers"] = normalized_layers
    data.pop("lining_layers", None)
    return data


def load_config(path: str | Path) -> Dict[str, Any]:
    """Read JSON or YAML config; PyYAML is optional and imported only for YAML."""
    file_path = Path(path)
    text = file_path.read_text(encoding="utf-8")
    if file_path.suffix.lower() == ".json":
        raw = json.loads(text)
    elif file_path.suffix.lower() in (".yaml", ".yml"):
        try:
            import yaml
        except ImportError as exc:
            raise RuntimeError("读取 YAML 需要安装 PyYAML；JSON 无额外依赖") from exc
        raw = yaml.safe_load(text)
    else:
        raise ValueError("仅支持 .json / .yaml / .yml 配置文件")
    return normalize_config(raw)


def validate_kiln_params(params: Mapping[str, Any], *, require_temperature_domain: bool = False) -> None:
    """Validate cross-field guardrails without binding the UI/API to Pydantic."""
    p = dict(params)
    for key in ("T_gas", "T_env", "P_total", "v_gas", "L_char", "L_kiln"):
        if key in p and _finite_number(p[key], key) <= 0:
            raise ValueError(f"{key} 必须大于 0")
    if "N_total" in p and not 10 <= int(p["N_total"]) <= 5000:
        raise ValueError("N_total 必须在 10–5000 之间")
    for key in ("eps_wall", "eps_shell"):
        if key in p and not 0 < _finite_number(p[key], key) <= 1:
            raise ValueError(f"{key} 必须在 (0, 1] 内")
    if "v_amb" in p and _finite_number(p["v_amb"], "v_amb") < 0:
        raise ValueError("v_amb 不能为负")
    if all(k in p for k in GAS_COMPONENTS):
        for k in GAS_COMPONENTS:
            if not 0 <= _finite_number(p[k], k) <= 1:
                raise ValueError(f"{k} 必须在 [0, 1] 内")
        if abs(sum(float(p[k]) for k in GAS_COMPONENTS) - 1.0) > 1e-8:
            raise ValueError("CO2/H2O/N2/O2 摩尔分数之和必须为 1")
    if require_temperature_domain and "T_gas" in p and not 300 <= float(p["T_gas"]) <= 2400:
        raise ValueError("气体温度超出该界面的 300–2400 K 防护范围；请核对具体模型适用域")
