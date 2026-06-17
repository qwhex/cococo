"""cococo — code cognitive complexity, on the command line.

Scores every function and method in the given Python files/directories with
:func:`cognitive_complexity.api.get_cognitive_complexity` and prints them
worst-first. With ``--max`` it doubles as a gate: it exits non-zero when any
function exceeds the ceiling, reporting each offender with concrete refactor
suggestions.

Usage::

    cococo src/                  # list every function, worst first
    cococo src/ --max 20         # gate: fail (with suggestions) above 20
    cococo a.py b.py --min 10    # only show functions scoring >= 10
    cococo src/ --max 20 --json  # machine-readable report for a pipeline
    cococo src/ --fix            # apply safe guard-clause rewrites in place
    cococo src/ --nested fold    # pre-2.0.0 scoring (fold nested defs into parent)
    cococo src/ --max 20 --baseline .cococo.json   # ratchet: fail only on regressions
    cococo --explain a.py::Klass.method   # break down one function
    cococo --explain a.py:42              # ...by line number

Exit codes in gate mode: 0 = within ceiling, 1 = offenders found, 2 = the gate
could not be trusted (nothing scanned, a file skipped, or a --fix write failed).
A function can suppress itself from the gate with a ``# cococo: ignore`` comment
on its ``def`` line.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from cognitive_complexity.api import Contribution, get_cognitive_complexity_breakdown
from cognitive_complexity.autofix import atomic_write, fix_source
from cognitive_complexity.common_types import AnyFuncdef, ScoredFunction, SkippedFile
from cognitive_complexity.discovery import find_function, iter_python_files, parse_target, scan
from cognitive_complexity.refactor import suggest_refactors
from cognitive_complexity.report import build_report, func_key, is_over, to_json


class BaselineError(Exception):
    """The baseline file could not be trusted."""


def _format_breakdown(
    funcdef: AnyFuncdef,
    qualname: str,
    path: Path,
    breakdown: list[Contribution],
) -> str:
    total = sum(c.points for c in breakdown)
    lines = [f"{qualname}  ({path}:{funcdef.lineno})  cognitive complexity = {total}"]
    if not breakdown:
        lines.append("  (no scored constructs — flat function)")
        return "\n".join(lines)
    lines.append(f"  {'line':>6}  {'pts':>3}  {'nest':>4}  construct")
    for c in sorted(breakdown, key=lambda c: (c.lineno, -c.points)):
        indent = "  " * c.nesting
        if c.nesting_counted and c.nesting:
            note = f"(+{c.points - c.nesting} base, +{c.nesting} nesting)"
        else:
            note = f"(+{c.points})"
        lines.append(f"  {c.lineno:>6}  {c.points:>3}  {c.nesting:>4}  {indent}{c.label}  {note}")
    return "\n".join(lines)


def explain(target: str, fold_nested: bool = False) -> int:
    """Print a per-construct cognitive-complexity breakdown for one function."""
    path, qualname, lineno = parse_target(target)
    try:
        funcdef, qual = find_function(path, qualname, lineno, fold_nested)
    except (LookupError, OSError, UnicodeDecodeError, SyntaxError, RecursionError) as exc:
        print(f"cococo: {exc}", file=sys.stderr)
        return 1
    breakdown = get_cognitive_complexity_breakdown(funcdef, fold_nested)
    print(_format_breakdown(funcdef, qual, path, breakdown))
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="cococo", description=__doc__.splitlines()[0])
    parser.add_argument("paths", nargs="*", help="Python files or directories to scan")
    parser.add_argument(
        "--max",
        type=int,
        default=None,
        help="ceiling: exit non-zero and show only functions above it",
    )
    parser.add_argument(
        "--min", type=int, default=0, help="only list functions scoring at least this much"
    )
    parser.add_argument(
        "--explain",
        metavar="FILE::QUAL",
        default=None,
        help="break down one function: FILE.py::qualname, FILE.py:LINE, or FILE.py",
    )
    parser.add_argument(
        "--json",
        dest="as_json",
        action="store_true",
        help="emit a machine-readable JSON report to stdout (for pipelines)",
    )
    parser.add_argument(
        "--fix",
        action="store_true",
        help="apply safe guard-clause rewrites in place before reporting",
    )
    parser.add_argument(
        "--nested",
        choices=("unit", "fold"),
        default="unit",
        help="score named nested defs as their own units (default) or fold them "
        "into the enclosing function (pre-2.0.0 compatibility)",
    )
    parser.add_argument(
        "--baseline",
        metavar="FILE",
        default=None,
        help="ratchet: record current scores to FILE if missing, else fail only on "
        "functions that regress above their recorded score (requires --max)",
    )
    args = parser.parse_args(argv)
    fold_nested = args.nested == "fold"

    if args.explain is not None:
        return explain(args.explain, fold_nested)
    if not args.paths:
        parser.error("the following arguments are required: paths (or use --explain)")
    if args.baseline is not None and args.max is None:
        parser.error("--baseline requires --max (the ceiling for code not in the baseline)")

    fix_failures = _apply_fixes(args.paths) if args.fix else 0

    functions, skipped, scanned = scan(args.paths, fold_nested)
    baseline = None
    baseline_root = None
    if args.baseline:
        baseline_path = Path(args.baseline)
        baseline_root = baseline_path.parent
        if baseline_path.exists() or (functions and not skipped):
            try:
                baseline = _load_or_create_baseline(baseline_path, functions)
            except BaselineError as exc:
                print(f"cococo: {exc}", file=sys.stderr)
                return 2
    _warn_unused_ignores(functions, args.max)
    scan_code = _scan_exit_code(
        functions, skipped, scanned, args.max, args.as_json, args.min, baseline, baseline_root
    )
    # A failed --fix write, or a file skipped under a gate, is a hard failure (2)
    # regardless of whether the functions that *did* scan stayed within --max.
    if fix_failures or (skipped and args.max is not None):
        return 2
    return scan_code


def _load_or_create_baseline(path: Path, functions: list[ScoredFunction]) -> dict[str, int]:
    """Load the baseline at ``path``, or create it from current scores and pass.

    A missing file establishes the baseline (every current score recorded) so the
    first run grandfathers the whole codebase; later runs compare against it.
    """
    if path.exists():
        try:
            loaded = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise BaselineError(f"invalid baseline {path}: {exc}") from exc
        return _validate_baseline(path, loaded)
    baseline = {func_key(f, path.parent): f.score for f in functions}
    try:
        path.write_text(json.dumps(baseline, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    except OSError as exc:
        raise BaselineError(f"invalid baseline {path}: {exc}") from exc
    print(f"cococo: wrote baseline for {len(baseline)} function(s) to {path}", file=sys.stderr)
    return baseline


def _validate_baseline(path: Path, loaded: object) -> dict[str, int]:
    if not isinstance(loaded, dict) or any(
        not isinstance(key, str) or type(value) is not int for key, value in loaded.items()
    ):
        raise BaselineError(f"invalid baseline {path}: expected dict[str, int]")
    return loaded


def _warn_unused_ignores(functions: list[ScoredFunction], max_: int | None) -> None:
    """Warn about ``# cococo: ignore`` directives on functions already within the gate."""
    if max_ is None:
        return
    for f in functions:
        if f.ignored and f.score <= max_:
            print(
                f"cococo: unused '# cococo: ignore' on {f.qualname} "
                f"({f.path}:{f.lineno}) — score {f.score} is within {max_}",
                file=sys.stderr,
            )


def _scan_exit_code(
    functions: list[ScoredFunction],
    skipped: list[SkippedFile],
    scanned: int,
    max_: int | None,
    as_json: bool,
    min_: int,
    baseline: dict[str, int] | None,
    baseline_root: Path | None,
) -> int:
    if as_json:
        return _report_json(functions, skipped, scanned, max_, min_, baseline, baseline_root)
    if not functions:
        return _empty_scan_exit(max_)
    return _report(functions, max_, min_, baseline, baseline_root)


def _empty_scan_exit(max_: int | None) -> int:
    """No functions matched the paths (text mode). Stay honest in gate mode.

    A ``--max`` gate that scans zero functions (a typo'd path, a renamed dir, a
    glob that expanded to nothing) is a misconfiguration, not a pass: it returns
    a distinct code (2) so CI cannot go green on a gate that gated nothing.
    Without ``--max`` an empty scan is merely informational (exit 0). (The
    ``--json`` empty case is handled by :func:`_report_json`, which still emits a
    valid report.)
    """
    print("cococo: no Python functions found", file=sys.stderr)
    if max_ is not None:
        print("cococo: no functions scanned — check the paths given to the gate", file=sys.stderr)
        return 2
    return 0


def _shown(functions: list[ScoredFunction], max_: int | None, min_: int) -> list[ScoredFunction]:
    threshold = max_ if max_ is not None else min_
    return sorted(
        (f for f in functions if f.score > threshold or (max_ is None and f.score >= min_)),
        key=lambda f: f.score,
        reverse=True,
    )


def _apply_fixes(paths: list[str]) -> int:
    """Rewrite safe guard-clause patterns in place; return the write-failure count.

    Each changed file is written atomically (a crash can't truncate the
    original), and both read/parse errors and write errors are recorded-and-
    skipped so one bad file never aborts the batch. Per-file outcomes go to
    stderr; the returned count lets the caller fail the exit code when a write
    did not land.
    """
    changed = 0
    applied = 0
    failed = 0
    for path in iter_python_files(paths):
        try:
            source = path.read_text(encoding="utf-8")
            new_source, count = fix_source(source)
        except (OSError, UnicodeDecodeError, SyntaxError, RecursionError):
            continue
        if not count:
            continue
        try:
            atomic_write(path, new_source)
        except OSError as exc:
            print(f"cococo: FAILED to write {path}: {exc}", file=sys.stderr)
            failed += 1
            continue
        print(f"cococo: fixed {path} ({count} guard(s))", file=sys.stderr)
        changed += 1
        applied += count
    print(
        f"cococo: applied {applied} guard-clause fix(es) across {changed} file(s)",
        file=sys.stderr,
    )
    return failed


def _report(
    functions: list[ScoredFunction],
    max_: int | None,
    min_: int,
    baseline: dict[str, int] | None,
    baseline_root: Path | None,
) -> int:
    """Print the scored functions and, when ``max_`` is set, gate on it."""
    for f in _shown(functions, max_, min_):
        print(f"{f.score:4d}  {f.path}:{f.lineno}  {f.qualname}")

    if max_ is None:
        return 0
    over = [f for f in functions if is_over(f, max_, baseline, baseline_root)]
    if over:
        _print_gate_failure(over, max_)
        return 1
    print(f"cococo: all {len(functions)} functions within cognitive complexity {max_}")
    return 0


def _report_json(
    functions: list[ScoredFunction],
    skipped: list[SkippedFile],
    scanned: int,
    max_: int | None,
    min_: int,
    baseline: dict[str, int] | None,
    baseline_root: Path | None,
) -> int:
    report = build_report(
        _shown(functions, max_, min_),
        max_,
        min_,
        skipped,
        scanned,
        baseline,
        baseline_root,
    )
    print(to_json(report))
    if not functions and max_ is not None:
        return 2  # gate scanned nothing — fail loud even in JSON mode
    return 1 if max_ is not None and report["exceeded"] else 0


def _print_gate_failure(over: list[ScoredFunction], max_: int) -> None:
    print(
        f"\ncococo: {len(over)} function(s) exceed cognitive complexity {max_}",
        file=sys.stderr,
    )
    for f in sorted(over, key=lambda f: f.score, reverse=True):
        _print_suggestions(f, max_)


def _print_suggestions(f: ScoredFunction, max_: int) -> None:
    suggestions = suggest_refactors(f.funcdef, f.breakdown)
    print(f"  {f.path}:{f.lineno} {f.qualname} = {f.score} (>{max_})", file=sys.stderr)
    if not suggestions:
        print("    (no mechanical refactor found; split it by responsibility)", file=sys.stderr)
        return
    for s in suggestions:
        fix = " [--fix]" if s.autofixable else ""
        print(
            f"    - {s.title} "
            f"(lines {s.line_start}-{s.line_end}, ~-{s.estimated_reduction} "
            f"-> {s.estimated_complexity_after}){fix}",
            file=sys.stderr,
        )


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
