"""Detector: flatten a nested block with an early-return/continue guard clause."""

from __future__ import annotations

import ast

from cognitive_complexity.detectors.base import (
    DetectorContext,
    Suggestion,
    make_suggestion,
)

KIND = "guard_clause"
TITLE = "Flatten nested block with a guard clause"
AUTOFIXABLE = True
STEPS = (
    "Invert the condition and return/continue early when it fails.",
    "De-indent the main path one level.",
    "Repeat for any further nested guards.",
)


def detect(ctx: DetectorContext) -> list[Suggestion]:
    out: list[Suggestion] = []
    for node in ctx.regions:
        if not isinstance(node, ast.If) or node.orelse or not node.body:
            continue
        body_start = node.body[0].lineno
        end = node.end_lineno or body_start
        saved = sum(
            1
            for c in ctx.breakdown
            if body_start <= c.lineno <= end and c.nesting_counted and c.lineno != node.lineno
        )
        if saved:
            out.append(
                make_suggestion(
                    kind=KIND,
                    title=TITLE,
                    steps=STEPS,
                    autofixable=AUTOFIXABLE,
                    start=node.lineno,
                    end=end,
                    reduction=saved,
                    total=ctx.total,
                )
            )
    return out
