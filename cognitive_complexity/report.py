"""Machine-readable JSON report, so cococo can sit in a pipeline.

Each shown function is emitted with its score, the per-construct breakdown, and
the refactor suggestions. The shape is stable and flat enough to filter with
``jq`` or feed to an agent.
"""

from __future__ import annotations

import json

from cognitive_complexity.api import get_cognitive_complexity_breakdown
from cognitive_complexity.common_types import ScoredFunction
from cognitive_complexity.refactor import suggest_refactors


def build_report(funcs: list[ScoredFunction], max_: int | None, min_: int) -> dict[str, object]:
    """Assemble the JSON-able report for the already-filtered ``funcs``."""
    entries = [_func_entry(func, max_) for func in funcs]
    return {
        "max": max_,
        "min": min_,
        "functions": entries,
        "exceeded": sum(1 for entry in entries if entry["over"]),
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
