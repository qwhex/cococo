"""Detector: name a complex boolean condition as a predicate function."""

from __future__ import annotations

from cognitive_complexity.detectors.base import (
    PREDICATE_MIN_POINTS,
    DetectorContext,
    Suggestion,
    make_suggestion,
    predicate_unsafe_lines,
)

KIND = "extract_predicate"
TITLE = "Name this complex condition as a predicate"
AUTOFIXABLE = False
STEPS = (
    "Move this boolean expression into a well-named predicate function.",
    "Call the predicate in the condition.",
    "Keep the control flow here focused on branching.",
)


def detect(ctx: DetectorContext) -> list[Suggestion]:
    unsafe_lines = predicate_unsafe_lines(ctx.funcdef)
    return [
        make_suggestion(
            kind=KIND,
            title=TITLE,
            steps=STEPS,
            autofixable=AUTOFIXABLE,
            start=c.lineno,
            end=c.lineno,
            reduction=c.points,
            total=ctx.total,
        )
        for c in ctx.breakdown
        if c.label == "bool-op"
        and c.points >= PREDICATE_MIN_POINTS
        and c.lineno not in unsafe_lines
    ]
