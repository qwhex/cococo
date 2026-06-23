"""Detector: drop a redundant ``else`` after a terminal ``if`` body.

When every path through an ``if`` body ends in a ``Return`` or ``Raise``
the subsequent ``else:`` is structurally redundant — control can only
reach it when the ``if`` condition was false, which is exactly what falling
through the ``if`` already expresses.  De-indenting the ``else`` body
removes the ``else``'s own complexity point **and** lowers the nesting
level of every nesting-counted construct inside it.
"""

from __future__ import annotations

import ast

from cognitive_complexity.detectors.base import (
    DetectorContext,
    Suggestion,
    make_suggestion,
)

KIND = "flatten_else_after_return"
TITLE = "Drop the else after the early return"
AUTOFIXABLE = False
STEPS = (
    "Remove the `else:` keyword and de-indent its body one level.",
    "Verify every path through the `if` body already returns or raises.",
    "Run the test suite — behaviour is unchanged because the else was unreachable.",
)


def detect(ctx: DetectorContext) -> list[Suggestion]:
    """Emit a suggestion for each ``if … else`` where the ``if`` body always terminates."""
    elif_ids = _elif_node_ids(ctx.funcdef)
    out: list[Suggestion] = []
    for node in ctx.regions:
        suggestion = _check_node(node, ctx, elif_ids)
        if suggestion is not None:
            out.append(suggestion)
    return out


def _elif_node_ids(funcdef: ast.AST) -> set[int]:
    """Return ``id()``s of ``If`` nodes that are ``elif`` arms of a chain.

    An ``elif`` appears as the sole ``ast.If`` in its parent ``If``'s ``orelse``.
    Such nodes must not trigger the detector even if their own body terminates and
    their own ``orelse`` is a real else — they are syntactically part of an
    ``if/elif/else`` chain, not a standalone ``if … else``.
    """
    ids: set[int] = set()
    for node in ast.walk(funcdef):
        if (
            isinstance(node, ast.If)
            and len(node.orelse) == 1
            and isinstance(node.orelse[0], ast.If)
        ):
            ids.add(id(node.orelse[0]))
    return ids


def _has_real_else(node: ast.If) -> bool:
    """True if ``node`` has an ``else`` block (not an ``elif`` chain)."""
    return bool(node.orelse) and not (len(node.orelse) == 1 and isinstance(node.orelse[0], ast.If))


def _check_node(node: ast.stmt, ctx: DetectorContext, elif_ids: set[int]) -> Suggestion | None:
    """Return a suggestion if ``node`` is a terminal ``if`` with a redundant ``else``."""
    if not isinstance(node, ast.If):
        return None
    if id(node) in elif_ids:
        return None
    if not _has_real_else(node):
        return None
    if not _always_terminates(node.body):
        return None
    reduction = _else_reduction(node, ctx)
    if reduction < 1:
        return None  # pragma: no cover - else_point is always 1 for a real else
    return make_suggestion(
        kind=KIND,
        title=TITLE,
        steps=STEPS,
        autofixable=AUTOFIXABLE,
        start=node.lineno,
        end=node.end_lineno or node.lineno,
        reduction=reduction,
        total=ctx.total,
    )


def _always_terminates(stmts: list[ast.stmt]) -> bool:
    """True if every path through ``stmts`` ends in a ``Return`` or ``Raise``.

    The last statement must itself be terminal:
    - A ``Return`` or ``Raise`` — unconditionally terminates.
    - An ``If`` node whose ``body`` AND ``orelse`` both always-terminate —
      every branch exits so control cannot fall through.

    Anything else (assignment, call, loop, …) means the block can fall through.
    """
    if not stmts:
        return False  # pragma: no cover - ast.If.body is always non-empty in valid Python
    last = stmts[-1]
    if isinstance(last, (ast.Return, ast.Raise)):
        return True
    if isinstance(last, ast.If) and last.orelse:
        return _always_terminates(last.body) and _always_terminates(last.orelse)
    return False


def _else_reduction(node: ast.If, ctx: DetectorContext) -> int:
    """Points removed by dropping the redundant ``else``.

    The saving has two components:
    1. The ``else``'s own complexity point (always 1 when an ``else`` exists).
    2. One nesting-counted saving per nesting-counted construct inside the
       ``else`` body — each one de-indents one level, losing its nesting penalty.
    """
    else_start = node.orelse[0].lineno
    else_end = node.end_lineno or else_start
    # Component 1: the else's own point (present whenever orelse is non-empty).
    else_point = 1
    # Component 2: de-nesting savings for constructs inside the else body.
    denest = sum(
        1
        for c in ctx.breakdown
        if else_start <= c.lineno <= else_end
        and c.nesting_counted
        and c.lineno != node.lineno  # exclude the if itself
    )
    return else_point + denest
