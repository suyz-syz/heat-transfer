"""Small, deterministic checks for schema v2 config file round trips."""
import json

import pytest

from kiln_ht.config_schema import SCHEMA_VERSION, normalize_config


def test_schema_v2_round_trip_preserves_units_and_conductivity_modes():
    source = {
        "schema_version": 2,
        "params": {
            "N_total": 200, "T_gas": 1523.15, "T_env": 298.15,
            "v_gas": 3.0, "L_char": 4.0, "L_kiln": 60.0, "P_total": 1.01325,
        },
        "layers": [
            {"name": "constant", "thickness_m": 0.1,
             "thermal_conductivity": {"mode": "constant", "value": 1.7}},
            {"name": "polynomial", "thickness_m": 0.08,
             "thermal_conductivity": {"mode": "polynomial", "temperature_unit": "degC",
                                      "coefficients": [1.2, 0.0002, 0.0]}},
            {"name": "table", "thickness_m": 0.05,
             "thermal_conductivity": {"mode": "table", "points": [[250, 1.5], [800, 1.1]]}},
        ],
    }
    first = normalize_config(source)
    second = normalize_config(json.loads(json.dumps(first)))
    assert first == second
    assert second["schema_version"] == SCHEMA_VERSION == 2
    assert second["params"]["T_gas"] == pytest.approx(1523.15)
    assert [x["thickness_m"] for x in second["layers"]] == [0.1, 0.08, 0.05]
    assert [x["thermal_conductivity"]["mode"] for x in second["layers"]] == [
        "constant", "polynomial", "table"
    ]


def test_legacy_layer_aliases_migrate_without_changing_si_units():
    migrated = normalize_config({
        "params": {"T_gas_K": 1400.0, "T_env_K": 300.0, "L_kiln": 60.0},
        "lining_layers": [{"name": "legacy", "thickness": 0.12, "k": 2.0, "Rc": 0.001}],
    })
    assert migrated["schema_version"] == 2
    assert migrated["params"]["T_gas"] == 1400.0
    assert migrated["layers"][0]["thickness_m"] == 0.12
    assert migrated["layers"][0]["contact_resistance_m2_k_w"] == 0.001
    assert migrated["layers"][0]["thermal_conductivity"] == {"mode": "constant", "value": 2.0}
