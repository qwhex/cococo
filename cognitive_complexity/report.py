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


def build_report(
    funcs: list[ScoredFunction],
    max_: int | None,
    min_: int,
    skipped: list[SkippedFile],
    files_scanned: int,
) -> dict[str, object]:
    """Assemble the JSON-able report for the already-filtered ``funcs``.

    ``files_scanned`` and ``skipped`` make scan coverage explicit so a consumer
    can tell a clean scan from a partial one: ``"exceeded": 0`` over a tree where
    files failed to parse is no longer indistinguishable from a genuinely clean
    tree.
    """
    entries = [_func_entry(func, max_) for func in funcs]
    return {
        "max": max_,
        "min": min_,
        "functions": entries,
        "exceeded": sum(1 for entry in entries if entry["over"]),
        "files_scanned": files_scanned,
        "skipped": [{"path": str(s.path), "reason": s.reason} for s in skipped],
    }


def _func_entry(func: ScoredFunction, max_: int | None) -> dict[str, object]:
    breakdown = get_cognitive_complexity_breakdown(func.funcdef)
    suggestions = suggest_refactors(func.funcdef, breakdown)
    return {
        "path": str(func.path),
        "lineno": func.lineno,
        "qualname": func.qualname,
        "complexity": func.score,
        "over": max_ is not None and func.score > max_,
        "breakdown": [c._asdict() for c in breakdown],
        "suggestions": [s._asdict() for s in suggestions],
    }


def to_json(report: dict[str, object]) -> str:
    return json.dumps(report, indent=2)
