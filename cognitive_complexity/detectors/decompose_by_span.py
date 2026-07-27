"""Fallback: point at the heaviest cohesive span when no named refactor fits.

This runs only when every named detector stayed silent on a function that is still
complex — the scattered-branches shape where no single region is extractable and no
dispatch/predicate/guard pattern matches. Rather than the dead-end "no mechanical
refactor found", it points at the heaviest contiguous run of top-level statements to
split out.

Advice only, and worded as "split by responsibility *near* lines X-Y": a span chosen
by points may not be a semantically cohesive unit, so the human judges the boundary —
the engine only locates the hotspot.
"""

from __future__ import annotations

import ast

from cognitive_complexity.api import Contribution
from cognitive_complexity.common_types import is_funcdef
from cognitive_complexity.detectors.base import (
    DetectorContext,
    Suggestion,
    make_suggestion,
    subtree_points,
)

KIND = "decompose_by_span"
TITLE = "Split by responsibility"
AUTOFIXABLE = False
STEPS = (
    "Group the flagged span into a cohesive unit (a phase, a validation pass, …).",
    "Pull it into a well-named helper and call it here.",
    "Repeat for the next-heaviest span until this function reads as a short outline.",
)


def fallback(ctx: DetectorContext) -> list[Suggestion]:
    """The decompose-by-span suggestion, or [] if nothing meaningful to split."""
    span = _heaviest_span(ctx.funcdef.body, ctx.breakdown, ctx.total)
    if span is None:
        return []
    start_line, end_line, points = span
    return [
        make_suggestion(
            kind=KIND,
            title=TITLE,
            steps=STEPS,
            autofixable=AUTOFIXABLE,
            start=start_line,
            end=end_line,
            reduction=points,
            total=ctx.total,
        )
    ]


def _heaviest_span(
    body: list[ast.stmt], breakdown: list[Contribution], total: int
) -> tuple[int, int, int] | None:
    """Heaviest contiguous top-level span carrying >= half the points but < the whole.

    Returns ``(start_line, end_line, points)`` or None. Requiring less than the whole
    body avoids "extract the whole function"; requiring at least half the function's
    points keeps the pointer on a substantial chunk, not a stray statement.

    The ceiling is the points the *body* carries, not the function total: a
    contribution anchored outside every statement (recursion is charged to the ``def``
    line) is in the total but in no span, and comparing against it would let the whole
    body through — exactly the advice the ceiling exists to prevent.
    """
    if any(is_funcdef(stmt) for stmt in body):
        return None
    points = [subtree_points(breakdown, s.lineno, s.end_lineno or s.lineno) for s in body]
    floor = max(2, (total + 1) // 2)
    best = _best_run(points, floor, sum(points))
    if best is None:
        return None
    run_points, i, j = best
    return body[i].lineno, body[j].end_lineno or body[j].lineno, run_points


def _best_run(points: list[int], floor: int, body_total: int) -> tuple[int, int, int] | None:
    """Max-points contiguous run in ``[floor, body_total)``; earliest wins ties."""
    best: tuple[int, int, int] | None = None
    for i in range(len(points)):
        cand = _best_run_from(points, i, floor, body_total)
        if cand is not None and (best is None or cand[0] > best[0]):
            best = cand
    return best


def _best_run_from(
    points: list[int], start: int, floor: int, body_total: int
) -> tuple[int, int, int] | None:
    """Best in-range run that begins at ``start``."""
    best: tuple[int, int, int] | None = None
    run = 0
    for j in range(start, len(points)):
        run += points[j]
        if run >= body_total:
            break
        if floor <= run and (best is None or run > best[0]):
            best = (run, start, j)
    return best
