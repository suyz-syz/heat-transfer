import json
import pytest

from kiln_ht.config_schema import normalize_config, normalize_layer, validate_kiln_params
from kiln_ht.conductivity import ConductivityModel


def test_legacy_k_config_migrates_to_constant():
    cfg = normalize_config({"layers": [{"name": "brick", "thickness": 0.08, "k": 1.4, "Rc": 0.0}]})
    layer = cfg["layers"][0]
    assert cfg["schema_version"] == 2
    assert layer["thickness_m"] == pytest.approx(0.08)
    assert layer["thermal_conductivity"] == {"mode": "constant", "value": 1.4}
    assert layer["contact_resistance_m2_k_w"] == 0.0


def test_legacy_k_coef_preserved_and_preferred():
    layer = normalize_layer({"k": 99, "k_coef": [1.2, 0.0004, -1e-7], "thickness": 0.1})
    assert layer["thermal_conductivity"]["mode"] == "polynomial"
    assert layer["thermal_conductivity"]["coefficients"] == [1.2, 0.0004, -1e-7]


def test_table_interpolation_and_no_extrapolation():
    model = ConductivityModel.table([(300, 1.5), (800, 1.0), (1200, 0.8)])
    assert model.conductivity(550) == pytest.approx(1.25)
    with pytest.raises(ValueError, match="不允许静默外推"):
        model.conductivity(250)


def test_polynomial_uses_legacy_celsius_by_default():
    model = ConductivityModel.polynomial((1.2, 4.5e-4, -1.2e-7))
    assert model.conductivity(773.15) == pytest.approx(1.2 + 4.5e-4*500 - 1.2e-7*500**2)


def test_rejects_nonpositive_table_values_and_unsorted_temperatures():
    with pytest.raises(ValueError):
        ConductivityModel.table([(300, 1.0), (800, 0.0)])
    with pytest.raises(ValueError):
        ConductivityModel.table([(800, 1.0), (300, 0.8)])


def test_guardrails_gas_fraction_sum():
    with pytest.raises(ValueError, match="之和必须为 1"):
        validate_kiln_params({"CO2": .2, "H2O": .1, "N2": .6, "O2": .1 + 0.02})


def test_guardrails_temperature_domain():
    with pytest.raises(ValueError, match="300–2400 K"):
        validate_kiln_params({"T_gas": 250.0}, require_temperature_domain=True)


def test_json_legacy_roundtrip(tmp_path):
    p = tmp_path / "legacy.json"
    p.write_text(json.dumps({"layers": [{"thickness": .1, "k": 2.0}]}), encoding="utf-8")
    cfg = normalize_config(json.loads(p.read_text(encoding="utf-8")))
    assert cfg["layers"][0]["thermal_conductivity"]["value"] == 2.0
