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
    cococo --explain a.py::Klass.method   # break down one function
    cococo --explain a.py:42              # ...by line number
"""

from __future__ import annotations

import argparse
import ast
import sys
from collections.abc import Iterator
from pathlib import Path

from cognitive_complexity.api import (
    Contribution,
    get_cognitive_complexity,
    get_cognitive_complexity_breakdown,
)
from cognitive_complexity.autofix import fix_source
from cognitive_complexity.common_types import AnyFuncdef, ScoredFunction
from cognitive_complexity.refactor import suggest_refactors
from cognitive_complexity.report import build_report, to_json


def iter_python_files(paths: list[str]) -> Iterator[Path]:
    for raw in paths:
        path = Path(raw)
        if path.is_dir():
            yield from sorted(path.rglob("*.py"))
        elif path.suffix == ".py":
            yield path


def _collect(node: ast.AST, qualifier: str, out: list[tuple[AnyFuncdef, str]]) -> None:
    """Every function, method, and named nested function, each as its own unit.

    ``qualifier`` is the enclosing-name prefix threaded down the recursion: a
    class extends it with ``Klass.`` and a named def extends it with
    ``name.<locals>.`` before recursing, so nested defs report as
    ``outer.<locals>.inner`` and method-local defs keep the class
    (``Klass.method.<locals>.inner``). Nested functions are scored as their own
    units, not folded into the enclosing function (see ``api``).
    """
    for child in ast.iter_child_nodes(node):
        if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
            qualname = f"{qualifier}{child.name}"
            out.append((child, qualname))
            _collect(child, f"{qualname}.<locals>.", out)
        elif isinstance(child, ast.ClassDef):
            _collect(child, f"{qualifier}{child.name}.", out)
        else:
            _collect(child, qualifier, out)


def scored_functions(paths: list[str]) -> list[ScoredFunction]:
    """Score every function found under ``paths``, keeping its AST node."""
    results: list[ScoredFunction] = []
    for path in iter_python_files(paths):
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        except (SyntaxError, UnicodeDecodeError):
            continue
        funcs: list[tuple[AnyFuncdef, str]] = []
        _collect(tree, "", funcs)
        for funcdef, qualname in funcs:
            score = get_cognitive_complexity(funcdef)
            results.append(ScoredFunction(score, path, funcdef.lineno, qualname, funcdef))
    return results


def score_paths(paths: list[str]) -> list[tuple[int, Path, int, str]]:
    """Return (score, path, lineno, qualname) for every function found."""
    return [(f.score, f.path, f.lineno, f.qualname) for f in scored_functions(paths)]


def _parse_target(target: str) -> tuple[Path, str | None, int | None]:
    """Split ``file.py::qualname`` / ``file.py:lineno`` / ``file.py`` into parts.

    Returns ``(path, qualname, lineno)`` with exactly one of qualname/lineno set
    (or both ``None`` to mean "the only function in the file").
    """
    if "::" in target:
        raw, _, qual = target.partition("::")
        return Path(raw), qual, None
    head, sep, tail = target.rpartition(":")
    if sep and tail.isdigit() and head.endswith(".py"):
        return Path(head), None, int(tail)
    return Path(target), None, None


def _find_function(
    path: Path,
    qualname: str | None,
    lineno: int | None,
) -> tuple[AnyFuncdef, str]:
    """Locate one function in ``path`` by qualname or line number.

    With neither selector, the file must contain exactly one function.
    """
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    funcs: list[tuple[AnyFuncdef, str]] = []
    _collect(tree, "", funcs)
    if not funcs:
        raise LookupError(f"no functions found in {path}")
    if qualname is not None:
        matches = [f for f in funcs if f[1] == qualname]
        if not matches:
            known = ", ".join(sorted(q for _, q in funcs))
            raise LookupError(f"no function {qualname!r} in {path}; found: {known}")
        return matches[0]
    if lineno is not None:
        matches = [f for f in funcs if f[0].lineno == lineno]
        if not matches:
            raise LookupError(f"no function defined on line {lineno} of {path}")
        return matches[0]
    if len(funcs) != 1:
        known = ", ".join(sorted(q for _, q in funcs))
        raise LookupError(f"{path} has {len(funcs)} functions; name one (file.py::qual): {known}")
    return funcs[0]


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


def explain(target: str) -> int:
    """Print a per-construct cognitive-complexity breakdown for one function."""
    path, qualname, lineno = _parse_target(target)
    try:
        funcdef, qual = _find_function(path, qualname, lineno)
    except (LookupError, OSError, SyntaxError) as exc:
        print(f"cococo: {exc}", file=sys.stderr)
        return 1
    breakdown = get_cognitive_complexity_breakdown(funcdef)
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
    args = parser.parse_args(argv)

    if args.explain is not None:
        return explain(args.explain)
    if not args.paths:
        parser.error("the following arguments are required: paths (or use --explain)")

    if args.fix:
        _apply_fixes(args.paths)

    functions = scored_functions(args.paths)
    if not functions:
        print("cococo: no Python functions found", file=sys.stderr)
        return 0
    if args.as_json:
        return _report_json(functions, args.max, args.min)
    return _report(functions, args.max, args.min)


def _shown(functions: list[ScoredFunction], max_: int | None, min_: int) -> list[ScoredFunction]:
    threshold = max_ if max_ is not None else min_
    return sorted(
        (f for f in functions if f.score > threshold or (max_ is None and f.score >= min_)),
        key=lambda f: f.score,
        reverse=True,
    )


def _apply_fixes(paths: list[str]) -> None:
    """Rewrite safe guard-clause patterns in place, reporting a one-line summary."""
    changed = 0
    applied = 0
    for path in iter_python_files(paths):
        try:
            source = path.read_text(encoding="utf-8")
            new_source, count = fix_source(source)
        except (OSError, UnicodeDecodeError, SyntaxError):
            continue
        if count:
            path.write_text(new_source, encoding="utf-8")
            changed += 1
            applied += count
    print(
        f"cococo: applied {applied} guard-clause fix(es) across {changed} file(s)",
        file=sys.stderr,
    )


def _report(functions: list[ScoredFunction], max_: int | None, min_: int) -> int:
    """Print the scored functions and, when ``max_`` is set, gate on it."""
    for f in _shown(functions, max_, min_):
        print(f"{f.score:4d}  {f.path}:{f.lineno}  {f.qualname}")

    if max_ is None:
        return 0
    over = [f for f in functions if f.score > max_]
    if over:
        _print_gate_failure(over, max_)
        return 1
    print(f"cococo: all {len(functions)} functions within cognitive complexity {max_}")
    return 0


def _report_json(functions: list[ScoredFunction], max_: int | None, min_: int) -> int:
    report = build_report(_shown(functions, max_, min_), max_, min_)
    print(to_json(report))
    return 1 if max_ is not None and report["exceeded"] else 0


def _print_gate_failure(over: list[ScoredFunction], max_: int) -> None:
    print(
        f"\ncococo: {len(over)} function(s) exceed cognitive complexity {max_}",
        file=sys.stderr,
    )
    for f in sorted(over, key=lambda f: f.score, reverse=True):
        _print_suggestions(f, max_)


def _print_suggestions(f: ScoredFunction, max_: int) -> None:
    suggestions = suggest_refactors(f.funcdef, get_cognitive_complexity_breakdown(f.funcdef))
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
