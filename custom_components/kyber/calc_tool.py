"""Sandboxed arithmetic tool for the chat AI.

The model cannot reliably do multi-step arithmetic (day averages, unit
conversions, percentage shares) in free-form generation, and Kyber had no
way to compute over numbers at all — so questions like "average daily
consumption of this total-energy counter" ended in "I cannot calculate
that".  This tool lets the model build its own tiny calculation: plain
Python expressions over values it fetched via get_entity_state.

Safety: expressions are parsed with ``ast`` and only a whitelist of nodes,
operators and math functions is evaluated — no names, no attribute access,
no calls beyond the whitelist, bounded expression length.  Execution runs
in an executor job (see _ASYNC_TOOLS routing in tool_execution).
"""
from __future__ import annotations

import ast
import json
import math
import operator
from typing import Any

_MAX_EXPR_LEN = 2000
_MAX_RESULT_REPR = 4000

_BIN_OPS: dict[type, Any] = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.FloorDiv: operator.floordiv,
    ast.Mod: operator.mod,
    ast.Pow: operator.pow,
}
_UNARY_OPS: dict[type, Any] = {
    ast.UAdd: operator.pos,
    ast.USub: operator.neg,
}

_FUNCS: dict[str, Any] = {
    "abs": abs,
    "round": round,
    "min": min,
    "max": max,
    "sum": sum,
    "len": len,
    "int": int,
    "float": float,
    "sqrt": math.sqrt,
    "log": math.log,
    "log10": math.log10,
    "exp": math.exp,
    "pow": math.pow,
    "floor": math.floor,
    "ceil": math.ceil,
    "fabs": math.fabs,
    "avg": lambda xs: (sum(xs) / len(xs)) if len(xs) else None,
}


class CalcError(ValueError):
    """Raised for any rejected expression; message is safe to show the AI."""


def _eval(node: ast.AST, variables: dict[str, float]) -> Any:
    if isinstance(node, ast.Expression):
        return _eval(node.body, variables)
    if isinstance(node, ast.Constant):
        if isinstance(node.value, (int, float)) and not isinstance(node.value, bool):
            return node.value
        raise CalcError(f"unsupported constant: {node.value!r}")
    if isinstance(node, ast.BinOp):
        op = _BIN_OPS.get(type(node.op))
        if op is None:
            raise CalcError(f"operator not allowed: {type(node.op).__name__}")
        return op(_eval(node.left, variables), _eval(node.right, variables))
    if isinstance(node, ast.UnaryOp):
        op = _UNARY_OPS.get(type(node.op))
        if op is None:
            raise CalcError(f"operator not allowed: {type(node.op).__name__}")
        return op(_eval(node.operand, variables))
    if isinstance(node, ast.Name):
        if node.id in variables:
            return variables[node.id]
        raise CalcError(f"unknown variable {node.id!r} — pass it in 'variables'")
    if isinstance(node, ast.Call):
        if not isinstance(node.func, ast.Name) or node.func.id not in _FUNCS:
            raise CalcError("only whitelisted functions: " + ", ".join(sorted(_FUNCS)))
        if node.keywords:
            raise CalcError("keyword arguments are not allowed")
        args = [_eval(a, variables) for a in node.args]
        if isinstance(node.func.id, str) and node.func.id == "sum" and len(args) == 1 and isinstance(args[0], (list, tuple)):
            return sum(args[0])
        return _FUNCS[node.func.id](*args)
    if isinstance(node, ast.List):
        return [_eval(e, variables) for e in node.elts]
    if isinstance(node, ast.Tuple):
        return tuple(_eval(e, variables) for e in node.elts)
    raise CalcError(f"expression element not allowed: {type(node).__name__}")


def _evaluate(expr: str, variables: dict[str, float]) -> Any:
    if len(expr) > _MAX_EXPR_LEN:
        raise CalcError(f"expression too long (max {_MAX_EXPR_LEN} chars)")
    try:
        tree = ast.parse(expr.strip(), mode="eval")
    except SyntaxError as err:
        raise CalcError(f"syntax error: {err.msg}") from None
    return _eval(tree, variables)


def execute_calc(call: dict[str, Any]) -> str:
    """Run one calc tool call, return a JSON string."""
    expr = str(call.get("expression") or call.get("expr") or "").strip()
    if not expr:
        return json.dumps({"error": "Missing 'expression' argument"})

    raw_vars = call.get("variables")
    variables: dict[str, float] = {}
    if isinstance(raw_vars, dict):
        for key, val in raw_vars.items():
            if not isinstance(key, str) or not key.isidentifier() or key in _FUNCS:
                return json.dumps({"error": f"invalid variable name: {key!r}"})
            try:
                variables[key] = float(val)
            except (TypeError, ValueError):
                return json.dumps({"error": f"variable {key!r} is not a number: {val!r}"})

    try:
        result = _evaluate(expr, variables)
    except CalcError as err:
        return json.dumps({"error": str(err)})
    except ZeroDivisionError:
        return json.dumps({"error": "division by zero"})
    except OverflowError:
        return json.dumps({"error": "numeric overflow — check the expression"})
    except (TypeError, ValueError) as err:
        return json.dumps({"error": f"calculation failed: {err}"})

    if isinstance(result, float) and not math.isfinite(result):
        return json.dumps({"error": "result is not finite (inf/nan)"})

    out: dict[str, Any] = {"expression": expr, "result": result}
    if isinstance(result, float):
        out["result_rounded"] = round(result, 4)
    if len(json.dumps(out)) > _MAX_RESULT_REPR:
        return json.dumps({"expression": expr, "result": str(result)[:500]})
    return json.dumps(out)
