"""Tiny, safe arithmetic/boolean evaluator for rule formulas.

Rule packs are data, so formulas must never reach Python's eval. Only
numbers, variables, + - * / // % **, comparisons, and/or/not, the ternary
`a if cond else b`, and a few whitelisted functions are allowed.
"""

from __future__ import annotations

import ast
import math
import operator as op
from functools import lru_cache

FUNCS = {"ceil": math.ceil, "floor": math.floor, "min": min, "max": max, "round": round, "abs": abs}

_BIN = {
    ast.Add: op.add, ast.Sub: op.sub, ast.Mult: op.mul, ast.Div: op.truediv,
    ast.FloorDiv: op.floordiv, ast.Mod: op.mod, ast.Pow: op.pow,
}
_CMP = {
    ast.Lt: op.lt, ast.LtE: op.le, ast.Gt: op.gt, ast.GtE: op.ge, ast.Eq: op.eq, ast.NotEq: op.ne,
}
_UNARY = {ast.USub: op.neg, ast.UAdd: op.pos, ast.Not: op.not_}


class ExprError(ValueError):
    pass


@lru_cache(maxsize=512)
def compile_expr(src: str) -> ast.Expression:
    try:
        tree = ast.parse(src, mode="eval")
    except SyntaxError as exc:
        raise ExprError(f"bad formula {src!r}: {exc.msg}") from exc
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            if not isinstance(node.func, ast.Name) or node.func.id not in FUNCS or node.keywords:
                raise ExprError(f"function not allowed in {src!r}")
        elif not isinstance(
            node,
            (ast.Expression, ast.BinOp, ast.UnaryOp, ast.BoolOp, ast.Compare, ast.IfExp,
             ast.Name, ast.Load, ast.Constant, ast.And, ast.Or, *_BIN, *_CMP, *_UNARY),
        ):
            raise ExprError(f"{type(node).__name__} not allowed in {src!r}")
        if isinstance(node, ast.Constant) and not isinstance(node.value, (int, float, bool)):
            raise ExprError(f"only numeric constants allowed in {src!r}")
    return tree


def names(src: str) -> set[str]:
    tree = compile_expr(src)
    return {n.id for n in ast.walk(tree) if isinstance(n, ast.Name) and n.id not in FUNCS}


def evaluate(src: str, env: dict[str, float]):
    return _eval(compile_expr(src).body, env, src)


def _eval(n: ast.AST, env: dict, src: str):
    if isinstance(n, ast.Constant):
        return n.value
    if isinstance(n, ast.Name):
        if n.id not in env:
            raise ExprError(f"unknown variable {n.id!r} in {src!r}")
        return env[n.id]
    if isinstance(n, ast.BinOp):
        return _BIN[type(n.op)](_eval(n.left, env, src), _eval(n.right, env, src))
    if isinstance(n, ast.UnaryOp):
        return _UNARY[type(n.op)](_eval(n.operand, env, src))
    if isinstance(n, ast.BoolOp):
        vals = (_eval(v, env, src) for v in n.values)
        return all(vals) if isinstance(n.op, ast.And) else any(vals)
    if isinstance(n, ast.Compare):
        left = _eval(n.left, env, src)
        for o, right_node in zip(n.ops, n.comparators):
            right = _eval(right_node, env, src)
            if not _CMP[type(o)](left, right):
                return False
            left = right
        return True
    if isinstance(n, ast.IfExp):
        return _eval(n.body, env, src) if _eval(n.test, env, src) else _eval(n.orelse, env, src)
    if isinstance(n, ast.Call):
        return FUNCS[n.func.id](*(_eval(a, env, src) for a in n.args))
    raise ExprError(f"unsupported expression in {src!r}")
