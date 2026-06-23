"""Detector: replace an equality branch ladder / simple match with a dispatch table."""

from __future__ import annotations

from cognitive_complexity.detectors.base import (
    DetectorContext,
    Suggestion,
    dispatch_reduction,
    make_suggestion,
)

KIND = "split_dispatcher"
TITLE = "Replace the branch ladder with a dispatch table"
AUTOFIXABLE = False
STEPS = (
    "Map each case to a named handler function.",
    "Replace the chain with a dispatch dict (or a thin delegating match).",
    "Keep this function a shallow orchestrator.",
)


def detect(ctx: DetectorContext) -> list[Suggestion]:
    out: list[Suggestion] = []
    for region in ctx.regions:
        reduction = dispatch_reduction(region)
        if reduction:
            end = region.end_lineno or region.lineno
            out.append(
                make_suggestion(
                    kind=KIND,
                    title=TITLE,
                    steps=STEPS,
                    autofixable=AUTOFIXABLE,
                    start=region.lineno,
                    end=end,
                    reduction=reduction,
                    total=ctx.total,
                )
            )
    return out
