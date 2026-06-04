"""cococo — code cognitive complexity, on the command line.

Scores every function and method in the given Python files/directories with
:func:`cognitive_complexity.api.get_cognitive_complexity` and prints them
worst-first. With ``--max`` it doubles as a gate: it exits non-zero (and prints
only the offenders) when any function exceeds the ceiling.

Usage::

    cococo src/                  # list every function, worst first
    cococo src/ --max 20         # gate: fail if any function exceeds 20
    cococo a.py b.py --min 10    # only show functions scoring >= 10
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

AnyFunc = ast.FunctionDef | ast.AsyncFunctionDef


def iter_python_files(paths: list[str]) -> Iterator[Path]:
    for raw in paths:
        path = Path(raw)
        if path.is_dir():
            yield from sorted(path.rglob("*.py"))
        elif path.suffix == ".py":
            yield path


def _collect(
    node: ast.AST, qualifier: str, inside_func: bool, out: list[tuple[AnyFunc, str]]
) -> None:
    """Top-level functions and methods; nested defs fold into their enclosing score."""
    for child in ast.iter_child_nodes(node):
        if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if not inside_func:
                out.append((child, f"{qualifier}{child.name}"))
        elif isinstance(child, ast.ClassDef):
            _collect(child, f"{qualifier}{child.name}.", False, out)
        else:
            _collect(child, qualifier, inside_func, out)


def score_paths(paths: list[str]) -> list[tuple[int, Path, int, str]]:
    """Return (score, path, lineno, qualname) for every function found."""
    results: list[tuple[int, Path, int, str]] = []
    for path in iter_python_files(paths):
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        except (SyntaxError, UnicodeDecodeError):
            continue
        funcs: list[tuple[AnyFunc, str]] = []
        _collect(tree, "", False, funcs)
        for funcdef, qualname in funcs:
            results.append((get_cognitive_complexity(funcdef), path, funcdef.lineno, qualname))
    return results


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
) -> tuple[AnyFunc, str]:
    """Locate one function in ``path`` by qualname or line number.

    With neither selector, the file must contain exactly one function.
    """
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    funcs: list[tuple[AnyFunc, str]] = []
    _collect(tree, "", False, funcs)
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
    funcdef: AnyFunc,
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
    args = parser.parse_args(argv)

    if args.explain is not None:
        return explain(args.explain)
    if not args.paths:
        parser.error("the following arguments are required: paths (or use --explain)")

    results = score_paths(args.paths)
    if not results:
        print("cococo: no Python functions found", file=sys.stderr)
        return 0
    return _report(results, args.max, args.min)


def _report(results: list[tuple[int, Path, int, str]], max_: int | None, min_: int) -> int:
    """Print the scored functions and, when ``max_`` is set, gate on it."""
    threshold = max_ if max_ is not None else min_
    shown = sorted(
        (r for r in results if r[0] > threshold or (max_ is None and r[0] >= min_)),
        reverse=True,
    )
    for score, path, lineno, qualname in shown:
        print(f"{score:4d}  {path}:{lineno}  {qualname}")

    if max_ is None:
        return 0
    over = [r for r in results if r[0] > max_]
    if over:
        print(
            f"\ncococo: {len(over)} function(s) exceed cognitive complexity {max_}",
            file=sys.stderr,
        )
        return 1
    print(f"cococo: all {len(results)} functions within cognitive complexity {max_}")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
