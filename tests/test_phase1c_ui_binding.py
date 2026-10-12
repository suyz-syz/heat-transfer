"""Tests for the Phase 1C outer-wall-temperature KPI binding.

The helper is extracted from main.py's AST so these tests do not need to initialize
Kivy or create a graphical window.
"""
import ast
import math
from pathlib import Path
from types import SimpleNamespace
import unittest


MAIN_PATH = Path(__file__).resolve().parents[1] / "main.py"
SOURCE = MAIN_PATH.read_text(encoding="utf-8")
TREE = ast.parse(SOURCE)


def _load_wall_temperature_helper():
    node = next(
        item for item in TREE.body
        if isinstance(item, ast.FunctionDef)
        and item.name == "_get_display_wall_temperature"
    )
    module = ast.Module(body=[node], type_ignores=[])
    namespace = {"math": math}
    exec(compile(module, str(MAIN_PATH), "exec"), namespace)
    return namespace[node.name]


get_display_wall_temperature = _load_wall_temperature_helper()


class DisplayWallTemperatureTests(unittest.TestCase):
    def setUp(self):
        self.sol = SimpleNamespace(T_wN=1200.0)

    def test_uses_mean_axial_outer_wall_temperature_for_three_phase(self):
        axial_data = {
            "wall_outer_temperature_k": [900.0, 1100.0, 1300.0],
            "material_temperature_k": [700.0, 800.0, 900.0],
        }

        value, source = get_display_wall_temperature(
            self.sol, axial_data, use_three_phase=True
        )

        self.assertEqual(value, 1100.0)
        self.assertEqual(
            source, "当前显示：三相轴向耦合外壁温（轴向平均值）"
        )

    def test_falls_back_when_three_phase_data_is_missing(self):
        value, source = get_display_wall_temperature(
            self.sol, {}, use_three_phase=True
        )

        self.assertEqual(value, 1200.0)
        self.assertEqual(
            source, "当前显示：径向稳态基线外壁温（三相耦合结果不可用）"
        )

    def test_falls_back_for_mismatched_or_invalid_values(self):
        invalid_axial_data = [
            {
                "wall_outer_temperature_k": [900.0, 1000.0],
                "material_temperature_k": [700.0],
            },
            {
                "wall_outer_temperature_k": [900.0, float("nan")],
                "material_temperature_k": [700.0, 800.0],
            },
            {
                "wall_outer_temperature_k": [900.0, float("inf")],
                "material_temperature_k": [700.0, 800.0],
            },
            {
                "wall_outer_temperature_k": [900.0, -1.0],
                "material_temperature_k": [700.0, 800.0],
            },
            {
                "wall_outer_temperature_k": ["bad"],
                "material_temperature_k": [700.0],
            },
        ]

        for axial_data in invalid_axial_data:
            with self.subTest(axial_data=axial_data):
                value, source = get_display_wall_temperature(
                    self.sol, axial_data, use_three_phase=True
                )
                self.assertEqual(value, 1200.0)
                self.assertEqual(
                    source, "当前显示：径向稳态基线外壁温（三相耦合结果不可用）"
                )

    def test_uses_radial_baseline_when_three_phase_is_disabled(self):
        axial_data = {
            "wall_outer_temperature_k": [900.0, 1100.0],
            "material_temperature_k": [700.0, 800.0],
        }

        value, source = get_display_wall_temperature(
            self.sol, axial_data, use_three_phase=False
        )

        self.assertEqual(value, 1200.0)
        self.assertEqual(source, "当前显示：径向稳态基线外壁温")

    def test_result_screen_binds_kpi_and_source_to_selected_mode(self):
        result_screen = next(
            item for item in TREE.body
            if isinstance(item, ast.ClassDef) and item.name == "ResultScreen"
        )
        set_result = next(
            item for item in result_screen.body
            if isinstance(item, ast.FunctionDef) and item.name == "set_result"
        )
        calls = [
            node for node in ast.walk(set_result)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "_get_display_wall_temperature"
        ]

        self.assertEqual(len(calls), 1)
        call = calls[0]
        keyword_values = {item.arg: item.value for item in call.keywords}
        self.assertIn("axial_data", keyword_values)
        self.assertTrue(
            any(
                isinstance(node, ast.Attribute)
                and node.attr == "axial_bed_enabled"
                for node in ast.walk(keyword_values["use_three_phase"])
            )
        )
        self.assertIn("display_wall_temperature_k", ast.unparse(set_result))
        self.assertIn("wall_temperature_source", ast.unparse(set_result))


if __name__ == "__main__":
    unittest.main()
