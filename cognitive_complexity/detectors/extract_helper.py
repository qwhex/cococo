"""Detector: pull a heavy control-flow region into a named helper function."""

from __future__ import annotations

from cognitive_complexity.detectors.base import (
    EXTRACT_MIN_LINES,
    EXTRACT_MIN_POINTS,
    MAX_COUPLING,
    DetectorContext,
    Suggestion,
    analyze_coupling,
    is_extractable_region,
    make_suggestion,
    subtree_points,
)

KIND = "extract_helper"
TITLE = "Extract this block into a helper function"
AUTOFIXABLE = False
STEPS = (
    "Move this block into a small named helper.",
    "Pass the values it reads as parameters.",
    "Return what the caller needs.",
)


def detect(ctx: DetectorContext) -> list[Suggestion]:
    out: list[Suggestion] = []
    for region in ctx.regions:
        start = region.lineno
        end = region.end_lineno or start
        points = subtree_points(ctx.breakdown, start, end)
        # ``points < total`` keeps us from advising "extract the whole function"
        # when one region spans the entire body and carries every point.
        big_enough = points >= EXTRACT_MIN_POINTS and (end - start + 1) >= EXTRACT_MIN_LINES
        if (
            big_enough
            and points < ctx.total
            and is_extractable_region(region)
            and analyze_coupling(ctx.funcdef, region) <= MAX_COUPLING
        ):
            out.append(
                make_suggestion(
                    kind=KIND,
                    title=TITLE,
                    steps=STEPS,
                    autofixable=AUTOFIXABLE,
                    start=start,
                    end=end,
                    reduction=points,
                    total=ctx.total,
                )
            )
    return out
