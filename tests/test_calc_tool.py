"""Unit tests for the calc tool (custom_components.kyber.calc_tool).

Covers the day-average case: the model computes total-kWh / days itself
instead of giving up.
"""
from __future__ import annotations

import importlib.util
import json
import sys
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

_pkg_cc = types.ModuleType("custom_components")
_pkg_cc.__path__ = [str(ROOT / "custom_components")]
sys.modules.setdefault("custom_components", _pkg_cc)

_pkg_kyber = types.ModuleType("custom_components.kyber")
_pkg_kyber.__path__ = [str(ROOT / "custom_components" / "kyber")]
sys.modules["custom_components.kyber"] = _pkg_kyber

_spec = importlib.util.spec_from_file_location(
    "custom_components.kyber.calc_tool",
    ROOT / "custom_components" / "kyber" / "calc_tool.py",
)
calc_tool = importlib.util.module_from_spec(_spec)
sys.modules["custom_components.kyber.calc_tool"] = calc_tool
_spec.loader.exec_module(calc_tool)

execute_calc = calc_tool.execute_calc


def _run(call: dict) -> dict:
    return json.loads(execute_calc(call))


class TestCalcHappyPath:
    def test_plain_expression(self):
        out = _run({"name": "calc", "expression": "3 + 4 * 2"})
        assert out["result"] == 11

    def test_day_average_with_variables(self):
        out = _run({
            "name": "calc",
            "expression": "total / days",
            "variables": {"total": 12000.0, "days": 400},
        })
        assert abs(out["result"] - 30.0) < 0.01

    def test_unit_conversion_w_to_kwh_per_day(self):
        out = _run({"name": "calc", "expression": "watt * 24 / 1000", "variables": {"watt": 850}})
        assert abs(out["result"] - 20.4) < 0.001

    def test_functions_whitelist(self):
        out = _run({"name": "calc", "expression": "round(avg([1, 2, 3]), 2)"})
        assert out["result"] == 2

    def test_sum_list(self):
        out = _run({"name": "calc", "expression": "sum([net, pv])", "variables": {"net": 4000.0, "pv": 6000.0}})
        assert out["result"] == 10000.0

    def test_power_and_mod(self):
        assert _run({"name": "calc", "expression": "2 ** 10"})["result"] == 1024
        assert _run({"name": "calc", "expression": "17 % 5"})["result"] == 2


class TestCalcSafety:
    def test_attribute_access_rejected(self):
        out = _run({"name": "calc", "expression": "().__class__"})
        assert "error" in out

    def test_name_injection_rejected(self):
        out = _run({"name": "calc", "expression": "__import__('os').system('id')"})
        assert "error" in out

    def test_open_call_rejected(self):
        out = _run({"name": "calc", "expression": "open('/etc/passwd')"})
        assert "error" in out

    def test_unknown_variable_rejected(self):
        out = _run({"name": "calc", "expression": "x + 1"})
        assert "unknown variable" in out["error"]

    def test_string_constant_rejected(self):
        out = _run({"name": "calc", "expression": "'abc'"})
        assert "error" in out

    def test_comprehension_rejected(self):
        out = _run({"name": "calc", "expression": "[i for i in range(10)]"})
        assert "error" in out

    def test_expression_length_bounded(self):
        out = _run({"name": "calc", "expression": "1+" * 3000 + "1"})
        assert "too long" in out["error"]


class TestCalcErrors:
    def test_missing_expression(self):
        assert "error" in _run({"name": "calc"})

    def test_division_by_zero(self):
        assert "division by zero" in _run({"name": "calc", "expression": "1/0"})["error"]

    def test_syntax_error_reported(self):
        out = _run({"name": "calc", "expression": "2 +"})
        assert "syntax error" in out["error"]

    def test_non_numeric_variable(self):
        out = _run({"name": "calc", "expression": "a + 1", "variables": {"a": "abc"}})
        assert "not a number" in out["error"]

    def test_huge_int_result_truncated(self):
        """Python ints are unbounded; the result must not flood the prompt."""
        out = _run({"name": "calc", "expression": "10 ** 1000"})
        assert len(json.dumps(out)) < 1200

    def test_nan_result_rejected(self):
        out = _run({"name": "calc", "expression": "sqrt(-1)"})
        assert "error" in out
