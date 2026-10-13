import csv
import json
from pathlib import Path

import pytest

from scripts.audit_hitemp_manifest import (
    DEFAULT_LINES,
    DEFAULT_MANIFEST,
    DEFAULT_TIPS,
    LINE_COLUMNS,
    TIPS_COLUMNS,
    build_manifest,
)
from scripts.hitemp_calibration.hitemp_lbl import load_hitemp_csv
from scripts.prepare_hitemp_benchmark import LINE_FIELDS, load_and_validate_tips, parse_hitemp_line

ROOT = Path(__file__).resolve().parents[1]


def test_committed_manifest_matches_current_data_and_hashes():
    manifest = build_manifest(ROOT / DEFAULT_LINES, ROOT / DEFAULT_TIPS)
    recorded = json.loads((ROOT / DEFAULT_MANIFEST).read_text(encoding="utf-8"))
    assert manifest == recorded
    assert tuple(LINE_FIELDS) == LINE_COLUMNS
    assert TIPS_COLUMNS == ("molecule", "isotope", "temperature_K", "Q")


def test_canonical_line_schema_maps_to_offline_lbl_model(tmp_path):
    path = tmp_path / "lines.csv"
    with path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=LINE_COLUMNS)
        writer.writeheader()
        writer.writerow({
            "molec_id": 1, "local_iso_id": 3, "nu": 2100.0, "sw": 1e-22,
            "a": 1.0, "gamma_air": 0.07, "gamma_self": 0.3,
            "elower": 50.0, "n_air": 0.7, "delta_air": -0.001,
        })
    line = load_hitemp_csv(path)[0]
    assert line.molecule == "H2O"
    assert line.isotope == "3"
    assert line.strength_ref == pytest.approx(1e-22)
    assert line.temp_exponent == pytest.approx(0.7)


def test_preprocessor_preserves_source_ids_and_canonical_fields(tmp_path):
    record = (
        f"{1:02d}{3:d}{2100.0:12.6f}{1.0e-22:10.3E}{1.0:10.3E}"
        f"{0.07:5.3f}{0.30:5.3f}{50.0:10.4f}{0.70:4.2f}{-0.001:8.4f}"
    )
    parsed = parse_hitemp_line(record, tmp_path / "fixture.par")
    assert parsed is not None
    assert set(parsed) == set(LINE_COLUMNS)
    assert parsed["molec_id"] == 1
    assert parsed["local_iso_id"] == 3
    assert parsed["nu"] == pytest.approx(2100.0)


def test_preprocessor_accepts_numeric_tips_molecule_ids(tmp_path):
    tips = tmp_path / "tips.csv"
    with tips.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=TIPS_COLUMNS)
        writer.writeheader()
        for temperature in (296.0, 2400.0):
            writer.writerow({"molecule": 1, "isotope": 3, "temperature_K": temperature, "Q": temperature})
    result = load_and_validate_tips(tips, {("1", "3")})
    assert [row["molecule"] for row in result] == [1, 1]
    assert {row["isotope"] for row in result} == {3}


def test_calibration_implementation_is_outside_runtime_package():
    runtime = ROOT / "kiln_ht" / "models" / "radiation"
    assert not (runtime / "hitemp_lbl.py").exists()
    assert not (runtime / "wsgg_fit.py").exists()
    assert not (runtime / "hitemp_wsgg_calibration.py").exists()
