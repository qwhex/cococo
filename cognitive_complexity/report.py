"""Machine-readable JSON report, so cococo can sit in a pipeline.

Each shown function is emitted with its score, the per-construct breakdown, and
the refactor suggestions. The shape is stable and flat enough to filter with
``jq`` or feed to an agent.
"""

from __future__ import annotations

import json
from pathlib import Path

from cognitive_complexity.common_types import ScoredFunction, SkippedFile
from cognitive_complexity.refactor import suggest_refactors


def _path_key(path: Path, root: Path | None) -> str:
    if root is None:
        return str(path)
    resolved_path = path.resolve()
    resolved_root = root.resolve()
    try:
        return resolved_path.relative_to(resolved_root).as_posix()
    except ValueError:
        return resolved_path.as_posix()


def func_key(func: ScoredFunction, root: Path | None = None) -> str:
    """Stable identity for a function across runs, used as the baseline key."""
    return f"{_path_key(func.path, root)}::{func.qualname}"


def is_over(
    func: ScoredFunction,
    max_: int | None,
    baseline: dict[str, int] | None,
    baseline_root: Path | None = None,
) -> bool:
    """Whether ``func`` fails the gate: over ``--max``, not ignored, not grandfathered.

    With a ``baseline`` the effective ceiling for a recorded function is the
    higher of ``--max`` and its baseline score, so a known offender passes at its
    recorded score and fails only when it regresses above it; a function absent
    from the baseline is gated at ``--max`` like any new code.
    """
    if max_ is None or func.ignored:
        return False
    if baseline is None:
        ceiling = max_
    else:
        recorded = baseline.get(func_key(func, baseline_root), baseline.get(func_key(func), max_))
        ceiling = max(max_, recorded)
    return func.score > ceiling


def build_report(
    funcs: list[ScoredFunction],
    max_: int | None,
    min_: int,
    suggest_min: int,
    suggest: bool,
    skipped: list[SkippedFile],
    files_scanned: int,
    baseline: dict[str, int] | None = None,
    baseline_root: Path | None = None,
) -> dict[str, object]:
    """Assemble the JSON-able report for the already-filtered ``funcs``.

    ``files_scanned`` and ``skipped`` make scan coverage explicit so a consumer
    can tell a clean scan from a partial one: ``"exceeded": 0`` over a tree where
    files failed to parse is no longer indistinguishable from a genuinely clean
    tree. ``over``/``exceeded`` honor ``# cococo: ignore`` and the baseline.
    Suggestions are attached to functions scoring at least ``suggest_min``.
    """
    entries = [
        _func_entry(func, max_, suggest_min, suggest, baseline, baseline_root) for func in funcs
    ]
    return {
        "max": max_,
        "min": min_,
        "functions": entries,
        "exceeded": sum(1 for entry in entries if entry["over"]),
        "files_scanned": files_scanned,
        "skipped": [{"path": str(s.path), "reason": s.reason} for s in skipped],
    }


def _func_entry(
    func: ScoredFunction,
    max_: int | None,
    suggest_min: int,
    suggest: bool,
    baseline: dict[str, int] | None,
    baseline_root: Path | None,
) -> dict[str, object]:
    breakdown = func.breakdown
    emit = suggest and func.score >= suggest_min
    suggestions = suggest_refactors(func.funcdef, breakdown) if emit else []
    return {
        "path": str(func.path),
        "lineno": func.lineno,
        "qualname": func.qualname,
        "complexity": func.score,
        "over": is_over(func, max_, baseline, baseline_root),
        "breakdown": [c._asdict() for c in breakdown],
        "suggestions": [s._asdict() for s in suggestions],
    }


def to_json(report: dict[str, object]) -> str:
    return json.dumps(report, indent=2)
