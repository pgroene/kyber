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

Resources: a turn timeout cannot stop an executor thread, so every
operation must be cheap by construction.  The nesting depth is checked
before evaluation, integer powers and sequence repetition are sized before
they are computed, every intermediate value is bounded (integer bits,
sequence length, flat sequences only), and round() gets a bounded ndigits.
Any expression the model writes therefore finishes in milliseconds.
"""
from __future__ import annotations

import ast
import json
import math
import operator
from typing import Any

_MAX_EXPR_LEN = 2000
_MAX_RESULT_REPR = 4000
# Nesting depth of the parsed tree.  A left-associative chain such as
# "a + b + c + ..." is as deep as it is long, so this stays well above any
# hand-written chain while keeping the recursive evaluator far below
# Python's recursion limit, which it shares with Home Assistant's frames.
_MAX_DEPTH = 200
# Size of any integer, intermediate or final.  10 000 bits are about 3000
# decimal digits: far beyond any measurement, cheap to compute with, and
# below Python's 4300-digit limit for int -> str, so every accepted result
# can be printed.
_MAX_INT_BITS = 10_000
# Length of any list or tuple.  Literals are already bounded by
# _MAX_EXPR_LEN (about 1000 values); this bounds repetition like [0] * n.
_MAX_SEQ_LEN = 10_000
# round(x, ndigits): rounding an int to -n digits computes 10 ** n.
_MAX_ROUND_DIGITS = 100


class CalcError(ValueError):
    """Raised for any rejected expression; message is safe to show the AI."""


def _is_seq(value: Any) -> bool:
    return isinstance(value, (list, tuple))


def _checked(value: Any) -> Any:
    """Reject values that would make the next operation expensive."""
    if isinstance(value, int) and not isinstance(value, bool):
        if value.bit_length() > _MAX_INT_BITS:
            raise CalcError(
                f"integer too large (max {_MAX_INT_BITS} bits, about 3000 digits)"
            )
    elif isinstance(value, complex):
        raise CalcError(
            "result is a complex number (negative base with a fractional exponent?)"
        )
    elif _is_seq(value) and len(value) > _MAX_SEQ_LEN:
        raise CalcError(f"list too long (max {_MAX_SEQ_LEN} items)")
    return value


def _pow(base: Any, exp: Any) -> Any:
    # Only int ** positive int grows without bound; float powers overflow
    # with OverflowError, negative exponents give a float.  The result of
    # |base| ** exp has more than (bit_length - 1) * exp bits, so anything
    # past the limit is refused before computing.  Below it the result has
    # fewer than 2 * _MAX_INT_BITS bits and is cheap; _checked bounds it.
    if (
        isinstance(base, int)
        and isinstance(exp, int)
        and exp > 0
        and (abs(base).bit_length() - 1) * exp >= _MAX_INT_BITS
    ):
        raise CalcError(
            f"power too large (result over {_MAX_INT_BITS} bits, about 3000 digits)"
        )
    return operator.pow(base, exp)


def _mul(left: Any, right: Any) -> Any:
    # Sequence repetition is sized before it allocates anything.
    if _is_seq(left) or _is_seq(right):
        seq, count = (left, right) if _is_seq(left) else (right, left)
        if isinstance(count, int) and len(seq) * count > _MAX_SEQ_LEN:
            raise CalcError(f"list too long (max {_MAX_SEQ_LEN} items)")
    return operator.mul(left, right)


def _round(number: Any, ndigits: Any = None) -> Any:
    if ndigits is None:
        return round(number)
    if isinstance(ndigits, int) and abs(ndigits) > _MAX_ROUND_DIGITS:
        raise CalcError(f"round() digits out of range (max {_MAX_ROUND_DIGITS})")
    return round(number, ndigits)


_BIN_OPS: dict[type, Any] = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: _mul,
    ast.Div: operator.truediv,
    ast.FloorDiv: operator.floordiv,
    ast.Mod: operator.mod,
    ast.Pow: _pow,
}
_UNARY_OPS: dict[type, Any] = {
    ast.UAdd: operator.pos,
    ast.USub: operator.neg,
}

_FUNCS: dict[str, Any] = {
    "abs": abs,
    "round": _round,
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


def _check_depth(tree: ast.AST) -> None:
    """Refuse deep trees iteratively, before the recursive evaluator runs."""
    stack = [(tree, 1)]
    while stack:
        node, depth = stack.pop()
        if depth > _MAX_DEPTH:
            raise CalcError(f"expression nested too deeply (max depth {_MAX_DEPTH})")
        stack.extend((child, depth + 1) for child in ast.iter_child_nodes(node))


def _eval(node: ast.AST, variables: dict[str, float]) -> Any:
    return _checked(_eval_node(node, variables))


def _eval_node(node: ast.AST, variables: dict[str, float]) -> Any:
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
    if isinstance(node, (ast.List, ast.Tuple)):
        items = [_eval(e, variables) for e in node.elts]
        # Flat sequences only: nesting has no use here, and a list of
        # repeated lists would make printing the result explode.
        if any(_is_seq(item) for item in items):
            raise CalcError("nested lists are not allowed")
        return items if isinstance(node, ast.List) else tuple(items)
    raise CalcError(f"expression element not allowed: {type(node).__name__}")


def _evaluate(expr: str, variables: dict[str, float]) -> Any:
    if len(expr) > _MAX_EXPR_LEN:
        raise CalcError(f"expression too long (max {_MAX_EXPR_LEN} chars)")
    try:
        tree = ast.parse(expr.strip(), mode="eval")
    except SyntaxError as err:
        raise CalcError(f"syntax error: {err.msg}") from None
    _check_depth(tree)
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
    except (RecursionError, MemoryError):
        # Backstops: the limits above should make both unreachable.
        return json.dumps({"error": "expression too complex — simplify it"})

    if isinstance(result, float) and not math.isfinite(result):
        return json.dumps({"error": "result is not finite (inf/nan)"})

    out: dict[str, Any] = {"expression": expr, "result": result}
    if isinstance(result, float):
        out["result_rounded"] = round(result, 4)
    if len(json.dumps(out)) > _MAX_RESULT_REPR:
        return json.dumps({"expression": expr, "result": str(result)[:500]})
    return json.dumps(out)
