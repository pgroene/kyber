"""Unit tests for the calc tool (custom_components.kyber.calc_tool).

Covers the day-average case: the model computes total-kWh / days itself
instead of giving up.
"""
from __future__ import annotations

import importlib.util
import json
import sys
import time
import types
from pathlib import Path

import pytest

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


def _run_timed(expr: str) -> tuple[dict, float]:
    start = time.perf_counter()
    out = _run({"name": "calc", "expression": expr})
    return out, time.perf_counter() - start


class TestCalcResourceLimits:
    """Hostile expressions must be refused fast: a turn timeout cannot stop
    the executor thread the calc tool runs in."""

    @pytest.mark.parametrize(
        ("expr", "message"),
        [
            ("9**9**9", "power too large"),
            ("10**5000", "power too large"),
            ("2**10**4", "power too large"),
            ("[1]*10**8", "list too long"),
            ("10**8*[1]", "list too long"),
            ("(1, 2)*10**8", "list too long"),
            ("-" * 1500 + "1", "nested too deeply"),
            ("+".join(["1"] * 500), "nested too deeply"),
            ("round(5, -10**9)", "digits out of range"),
            ("[[1]*10000]*10000", "nested lists are not allowed"),
            ("[1]*5000 + [1]*5001", "list too long"),
            ("(10**3000)*(10**3000)", "integer too large"),
            ("3**7000", "integer too large"),
            ("(-8)**0.5", "complex number"),
            ("10.0**400", "overflow"),
            ("2.0**(10**400)", "overflow"),
        ],
    )
    def test_rejected_fast_with_clear_message(self, expr, message):
        out, elapsed = _run_timed(expr)
        assert message in out.get("error", ""), out
        assert elapsed < 1.0, f"{expr!r} took {elapsed:.2f}s"

    def test_recursion_and_memory_errors_are_reported(self, monkeypatch):
        for exc in (RecursionError, MemoryError):
            def _boom(expr, variables, exc=exc):
                raise exc()
            monkeypatch.setattr(calc_tool, "_evaluate", _boom)
            out = _run({"name": "calc", "expression": "1 + 1"})
            assert "too complex" in out["error"]

    def test_limits_are_named_constants(self):
        assert calc_tool._MAX_DEPTH >= 100
        assert calc_tool._MAX_INT_BITS >= 4000
        assert calc_tool._MAX_SEQ_LEN >= 1000
        assert calc_tool._MAX_ROUND_DIGITS >= 20


class TestCalcLimitsKeepNormalMath:
    """Counter-checks: the limits must not break real calculations."""

    def test_large_but_bounded_powers(self):
        assert _run({"name": "calc", "expression": "2 ** 64"})["result"] == 2 ** 64
        out, elapsed = _run_timed("2 ** 9999")
        assert "error" not in out and elapsed < 1.0

    def test_trivial_bases_with_huge_exponents(self):
        assert _run({"name": "calc", "expression": "(-1) ** (10 ** 3000)"})["result"] == 1
        assert _run({"name": "calc", "expression": "1 ** (10 ** 3000)"})["result"] == 1

    def test_float_and_negative_powers(self):
        assert _run({"name": "calc", "expression": "2 ** -2"})["result"] == 0.25
        out = _run({"name": "calc", "expression": "1.05 ** 10"})
        assert abs(out["result"] - 1.628894627) < 1e-6

    def test_round_with_digits(self):
        assert _run({"name": "calc", "expression": "round(1234.5678, 2)"})["result"] == 1234.57
        assert _run({"name": "calc", "expression": "round(1234, -2)"})["result"] == 1200

    def test_statistics_over_many_measurements(self):
        values = [round(18.0 + (i % 50) * 0.1, 1) for i in range(300)]
        literal = "[" + ",".join(str(v) for v in values) + "]"
        out = _run({"name": "calc", "expression": f"round(avg({literal}), 3)"})
        assert out["result"] == round(sum(values) / len(values), 3)
        half = "[" + ",".join(str(v) for v in values[:150]) + "]"
        out = _run({"name": "calc", "expression": f"round(max({half}) - min({half}), 1)"})
        assert out["result"] == 4.9

    def test_small_repetition_and_concatenation(self):
        out = _run({"name": "calc", "expression": "avg([20.0] * 3 + [22.0] * 1)"})
        assert out["result"] == 20.5
        assert _run({"name": "calc", "expression": "len([0] * 24)"})["result"] == 24

    def test_long_variable_chain(self):
        names = [f"v{i}" for i in range(150)]
        out = _run({
            "name": "calc",
            "expression": " + ".join(names),
            "variables": {n: 1.5 for n in names},
        })
        assert out["result"] == 225.0

    def test_nested_parentheses(self):
        out = _run({"name": "calc", "expression": "(" * 100 + "2" + ")" * 100 + " * 3"})
        assert out["result"] == 6
