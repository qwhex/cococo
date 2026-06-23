"""Detector: merge `if a: if b:` (no else on either) into `if a and b:`.

Behavior-preserving: ``a and b`` short-circuits identically to the nested form —
``b`` is evaluated only when ``a`` is truthy — so the merge is safe even when ``b``
has side effects.
"""

from __future__ import annotations

import ast

from cognitive_complexity.detectors.base import (
    DetectorContext,
    Suggestion,
    make_suggestion,
)

KIND = "merge_nested_if"
TITLE = "Merge nested conditions with `and`"
AUTOFIXABLE = False
STEPS = (
    "Combine both conditions: `if outer_cond and inner_cond:`.",
    "De-indent the inner body one level.",
    "Remove the now-empty outer `if` shell.",
)

_IF_BASE = 1  # structural (non-nesting) cost of a plain `if`


def detect(ctx: DetectorContext) -> list[Suggestion]:
    """Emit a suggestion for each `if a: if b:` pair (no else on either)."""
    out: list[Suggestion] = []
    for node in ctx.regions:
        inner = _merge_candidate(node)
        if inner is None:
            continue
        reduction = _merge_reduction(inner, ctx)
        end = inner.end_lineno or node.lineno
        out.append(
            make_suggestion(
                kind=KIND,
                title=TITLE,
                steps=STEPS,
                autofixable=AUTOFIXABLE,
                start=node.lineno,
                end=end,
                reduction=reduction,
                total=ctx.total,
            )
        )
    return out


def _merge_candidate(node: ast.stmt) -> ast.If | None:
    """Return the inner `If` if ``node`` is a bare `if a: if b:` shell, else None."""
    if not isinstance(node, ast.If) or node.orelse:
        return None
    if len(node.body) != 1 or not isinstance(node.body[0], ast.If):
        return None
    inner = node.body[0]
    return None if inner.orelse else inner


def _merge_reduction(inner: ast.If, ctx: DetectorContext) -> int:
    """Points removed by merging: inner `if`'s nesting penalty (points - base).

    Merging folds the inner ``if`` into an ``and`` expression; the merged
    ``if`` keeps the outer's nesting level so the inner's nesting penalty
    disappears entirely.  The ``and`` adds no extra complexity point since it
    becomes part of the outer ``if``'s test rather than an independent
    bool-op node.
    """
    for c in ctx.breakdown:
        if c.lineno == inner.lineno and c.nesting_counted and c.nesting > 0:
            return c.points - _IF_BASE
    return 0  # pragma: no cover - a nested inner `if` always has a nesting contribution
