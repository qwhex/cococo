"""Refactor-suggestion detectors and the public entry point.

``REGISTRY`` is the single wiring point: each detector is a self-contained module
(written independently, possibly in parallel) and is added here once. ``suggest_refactors``
runs every detector and ``select`` picks the highest-value, non-overlapping few.
"""

from __future__ import annotations

from cognitive_complexity.api import Contribution
from cognitive_complexity.common_types import AnyFuncdef
from cognitive_complexity.detectors import (
    extract_helper,
    extract_predicate,
    flatten_else_after_return,
    guard_clause,
    merge_nested_if,
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
    return _select(candidates)


def _select(candidates: list[Suggestion]) -> list[Suggestion]:
    good = [c for c in candidates if c.estimated_reduction >= MIN_REDUCTION]
    good.sort(key=lambda c: (-c.estimated_reduction, c.line_start))
    out: list[Suggestion] = []
    for candidate in good:
        if any(_contains(s, candidate) for s in out):
            continue
        out.append(candidate)
        if len(out) == MAX_SUGGESTIONS:
            break
    return out


def _contains(outer: Suggestion, inner: Suggestion) -> bool:
    return (
        outer.kind == inner.kind
        and outer.line_start <= inner.line_start
        and outer.line_end >= inner.line_end
    )
