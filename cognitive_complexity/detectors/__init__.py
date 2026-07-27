"""Refactor-suggestion detectors and the public entry point.

``REGISTRY`` is the single wiring point: each detector is a self-contained module
(written independently, possibly in parallel) and is added here once. ``suggest_refactors``
runs every detector and ``select`` picks the highest-value, non-overlapping few.
"""

from __future__ import annotations

from cognitive_complexity.api import Contribution
from cognitive_complexity.common_types import AnyFuncdef
from cognitive_complexity.detectors import (
    decompose_by_span,
    extract_helper,
    extract_predicate,
    flatten_else_after_return,
    guard_clause,
    merge_nested_if,
    sequential_dispatch,
    split_dispatcher,
)
from cognitive_complexity.detectors.base import (
    MAX_SUGGESTIONS,
    MIN_REDUCTION,
    Detector,
    DetectorContext,
    Suggestion,
    iter_regions,
)

# The wiring point — add a new detector's ``detect`` here once its module exists.
REGISTRY: list[Detector] = [
    guard_clause.detect,
    extract_helper.detect,
    split_dispatcher.detect,
    extract_predicate.detect,
    merge_nested_if.detect,
    flatten_else_after_return.detect,
    sequential_dispatch.detect,
]

__all__ = ["Suggestion", "suggest_refactors"]


def suggest_refactors(funcdef: AnyFuncdef, breakdown: list[Contribution]) -> list[Suggestion]:
    """Up to a few high-value refactors for ``funcdef``, biggest reduction first."""
    ctx = DetectorContext(
        funcdef=funcdef,
        breakdown=breakdown,
        total=sum(c.points for c in breakdown),
        regions=iter_regions(funcdef),
    )
    candidates: list[Suggestion] = []
    for detect in REGISTRY:
        candidates += detect(ctx)
    selected = _select(candidates)
    # Fallback only when no named refactor fits, so a complex but pattern-less
    # function still gets a concrete pointer instead of a dead end.
    return selected or decompose_by_span.fallback(ctx)


def _select(candidates: list[Suggestion]) -> list[Suggestion]:
    """The biggest win per hotspot, biggest first, capped at ``MAX_SUGGESTIONS``.

    Overlapping suggestions describe the same hotspot whatever their kind: each
    estimate is measured against the untouched total, so they don't add up, and some
    are mutually exclusive (inverting an ``if`` into a guard clause destroys the
    ``if a: if b:`` shell a merge would need). Keeping one per span keeps the
    report's arithmetic satisfiable and spends the slots on distinct places.
    """
    good = [c for c in candidates if c.estimated_reduction >= MIN_REDUCTION]
    good.sort(key=lambda c: (-c.estimated_reduction, c.line_start))
    out: list[Suggestion] = []
    for candidate in good:
        if any(_overlaps(s, candidate) for s in out):
            continue
        out.append(candidate)
        if len(out) == MAX_SUGGESTIONS:
            break
    return out


def _overlaps(one: Suggestion, other: Suggestion) -> bool:
    return one.line_start <= other.line_end and other.line_start <= one.line_end
