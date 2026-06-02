"""cococo — code cognitive complexity, on the command line.

Scores every function and method in the given Python files/directories with
:func:`cognitive_complexity.api.get_cognitive_complexity` and prints them
worst-first. With ``--max`` it doubles as a gate: it exits non-zero (and prints
only the offenders) when any function exceeds the ceiling.

Usage::

    cococo src/                  # list every function, worst first
    cococo src/ --max 20         # gate: fail if any function exceeds 20
    cococo a.py b.py --min 10    # only show functions scoring >= 10
"""
from __future__ import annotations

import argparse
import ast
import sys
from collections.abc import Iterator
from pathlib import Path

from cognitive_complexity.api import get_cognitive_complexity

AnyFunc = ast.FunctionDef | ast.AsyncFunctionDef


def iter_python_files(paths: list[str]) -> Iterator[Path]:
    for raw in paths:
        path = Path(raw)
        if path.is_dir():
            yield from sorted(path.rglob("*.py"))
        elif path.suffix == ".py":
            yield path


def _collect(node: ast.AST, qualifier: str, inside_func: bool, out: list[tuple[AnyFunc, str]]) -> None:
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


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="cococo", description=__doc__.splitlines()[0])
    parser.add_argument("paths", nargs="+", help="Python files or directories to scan")
    parser.add_argument("--max", type=int, default=None,
                        help="ceiling: exit non-zero and show only functions above it")
    parser.add_argument("--min", type=int, default=0,
                        help="only list functions scoring at least this much")
    args = parser.parse_args(argv)

    results = score_paths(args.paths)
    if not results:
        print("cococo: no Python functions found", file=sys.stderr)
        return 0

    threshold = args.max if args.max is not None else args.min
    shown = sorted((r for r in results if r[0] > threshold or (args.max is None and r[0] >= args.min)),
                   reverse=True)
    for score, path, lineno, qualname in shown:
        print(f"{score:4d}  {path}:{lineno}  {qualname}")

    if args.max is not None:
        over = [r for r in results if r[0] > args.max]
        if over:
            print(f"\ncococo: {len(over)} function(s) exceed cognitive complexity {args.max}",
                  file=sys.stderr)
            return 1
        print(f"cococo: all {len(results)} functions within cognitive complexity {args.max}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
