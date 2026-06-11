"""Machine-readable JSON report, so cococo can sit in a pipeline.

Each shown function is emitted with its score, the per-construct breakdown, and
the refactor suggestions. The shape is stable and flat enough to filter with
``jq`` or feed to an agent.
"""

from __future__ import annotations

import json

from cognitive_complexity.api import get_cognitive_complexity_breakdown
from cognitive_complexity.common_types import ScoredFunction, SkippedFile
from cognitive_complexity.refactor import suggest_refactors


def func_key(func: ScoredFunction) -> str:
    """Stable identity for a function across runs, used as the baseline key."""
    return f"{func.path}::{func.qualname}"


def is_over(func: ScoredFunction, max_: int | None, baseline: dict[str, int] | None) -> bool:
    """Whether ``func`` fails the gate: over ``--max``, not ignored, not grandfathered.

    With a ``baseline`` the effective ceiling for a recorded function is the
    higher of ``--max`` and its baseline score, so a known offender passes at its
    recorded score and fails only when it regresses above it; a function absent
    from the baseline is gated at ``--max`` like any new code.
    """
    if max_ is None or func.ignored:
        return False
    ceiling = max(max_, baseline.get(func_key(func), max_)) if baseline is not None else max_
    return func.score > ceiling


def build_report(
    funcs: list[ScoredFunction],
    max_: int | None,
    min_: int,
    skipped: list[SkippedFile],
    files_scanned: int,
    baseline: dict[str, int] | None = None,
) -> dict[str, object]:
    """Assemble the JSON-able report for the already-filtered ``funcs``.

    ``files_scanned`` and ``skipped`` make scan coverage explicit so a consumer
    can tell a clean scan from a partial one: ``"exceeded": 0`` over a tree where
    files failed to parse is no longer indistinguishable from a genuinely clean
    tree. ``over``/``exceeded`` honor ``# cococo: ignore`` and the baseline.
    """
    entries = [_func_entry(func, max_, baseline) for func in funcs]
    return {
        "max": max_,
        "min": min_,
        "functions": entries,
        "exceeded": sum(1 for entry in entries if entry["over"]),
        "files_scanned": files_scanned,
        "skipped": [{"path": str(s.path), "reason": s.reason} for s in skipped],
    }


def _func_entry(
    func: ScoredFunction, max_: int | None, baseline: dict[str, int] | None
) -> dict[str, object]:
    breakdown = get_cognitive_complexity_breakdown(func.funcdef)
    suggestions = suggest_refactors(func.funcdef, breakdown)
    return {
        "path": str(func.path),
        "lineno": func.lineno,
        "qualname": func.qualname,
        "complexity": func.score,
        "over": is_over(func, max_, baseline),
        "breakdown": [c._asdict() for c in breakdown],
        "suggestions": [s._asdict() for s in suggestions],
    }


def to_json(report: dict[str, object]) -> str:
    return json.dumps(report, indent=2)
