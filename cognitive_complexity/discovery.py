"""Function discovery and scoring: path walking, AST traversal, qualname construction.

Library-level entry points for enumerating and scoring Python functions from
files and directories, without the CLI presentation layer.
"""

from __future__ import annotations

import ast
import io
import sys
import tokenize
from collections.abc import Iterator, Sequence
from fnmatch import fnmatch
from pathlib import Path

from cognitive_complexity.api import get_cognitive_complexity_breakdown
from cognitive_complexity.common_types import AnyFuncdef, ScoredFunction, SkippedFile, is_funcdef

_IGNORE_DIRECTIVE = "cococo: ignore"

# Directories a recursive scan never descends into. Hidden directories (a `.`
# prefix) are pruned too, which covers .venv/.git/.tox/.nox/.eggs and the
# assorted tool caches without naming each one.
_EXCLUDED_DIRS = frozenset(
    {"venv", "node_modules", "build", "dist", "__pycache__", "site-packages"}
)


def iter_python_files(paths: list[str], exclude: Sequence[str] = ()) -> Iterator[Path]:
    """Yield the ``.py`` files under ``paths``, worst-case a whole directory tree.

    Recursion prunes virtualenv/vendor/build/cache trees (and anything matching an
    ``exclude`` glob) *during* the walk, so a run at a repo root scores project
    source rather than installed dependencies — and ``--fix`` cannot rewrite them.
    A file named directly on the command line is always honoured: exclusions
    apply to what the walk discovers, not to what the user asked for by name.
    """
    patterns = tuple(exclude)
    for raw in paths:
        path = Path(raw)
        if path.is_dir():
            yield from sorted(_walk_python_files(path, patterns))
        elif path.suffix == ".py":
            yield path


def _walk_python_files(root: Path, patterns: tuple[str, ...]) -> Iterator[Path]:
    stack = [root]
    while stack:
        files, subdirs = _split_entries(stack.pop(), patterns)
        stack.extend(subdirs)
        yield from files


def _split_entries(directory: Path, patterns: tuple[str, ...]) -> tuple[list[Path], list[Path]]:
    """Split one directory into ``(.py files to score, subdirectories to descend)``.

    Symlinked directories are not followed — they can leave the scanned tree or
    form a cycle — matching the traversal ``rglob`` did before exclusions existed.
    """
    files: list[Path] = []
    subdirs: list[Path] = []
    for entry in directory.iterdir():
        if entry.is_dir():
            if not entry.is_symlink() and not _is_excluded_dir(entry, patterns):
                subdirs.append(entry)
        elif entry.suffix == ".py" and not _matches(entry, patterns):
            files.append(entry)
    return files, subdirs


def _is_excluded_dir(entry: Path, patterns: tuple[str, ...]) -> bool:
    return (
        entry.name.startswith(".")
        or entry.name in _EXCLUDED_DIRS
        or entry.name.endswith(".egg-info")
        or _matches(entry, patterns)
    )


def _matches(entry: Path, patterns: tuple[str, ...]) -> bool:
    return any(fnmatch(entry.name, p) or fnmatch(str(entry), p) for p in patterns)


def _collect(
    node: ast.AST,
    qualifier: str,
    out: list[tuple[AnyFuncdef, str]],
    fold_nested: bool = False,
) -> None:
    """Discover the functions to score under ``node``.

    ``qualifier`` is the enclosing-name prefix threaded down the recursion: a
    class extends it with ``Klass.`` and a named def extends it with
    ``name.<locals>.`` before recursing, so nested defs report as
    ``outer.<locals>.inner`` and method-local defs keep the class
    (``Klass.method.<locals>.inner``). By default nested functions are their own
    units (the recursion descends into them). In fold mode (pre-2.0.0 compat)
    nested defs are *not* listed separately — they fold into the enclosing
    function's score — so the recursion does not descend into them.
    """
    for child in ast.iter_child_nodes(node):
        if is_funcdef(child):
            qualname = f"{qualifier}{child.name}"
            out.append((child, qualname))
            if not fold_nested:
                _collect(child, f"{qualname}.<locals>.", out, fold_nested)
        elif isinstance(child, ast.ClassDef):
            _collect(child, f"{qualifier}{child.name}.", out, fold_nested)
        else:
            _collect(child, qualifier, out, fold_nested)


def scan(
    paths: list[str], fold_nested: bool = False, exclude: Sequence[str] = ()
) -> tuple[list[ScoredFunction], list[SkippedFile], int]:
    """Score every function under ``paths``; also return skipped files and scan count.

    A file that cannot be read, parsed, or scored is reported on stderr and
    recorded as skipped — never silently dropped — so the caller can fail a
    ``--max`` gate and the JSON report can expose coverage, rather than launder a
    partial scan as clean. ``files_scanned`` counts the files that parsed.
    """
    files = list(iter_python_files(paths, exclude))
    outcomes = [_score_or_skip(path, fold_nested) for path in files]
    results = [func for scored, _ in outcomes for func in scored]
    skipped = [info for _, info in outcomes if info is not None]
    return results, skipped, len(files) - len(skipped)


def _score_or_skip(
    path: Path, fold_nested: bool
) -> tuple[list[ScoredFunction], SkippedFile | None]:
    """Score one file, or report+record it as skipped on any unscoreable failure.

    Returns ``(scored, None)`` on success or ``([], SkippedFile)`` on failure.
    Catches read/parse errors and ``RecursionError`` from a pathologically deep
    AST (a crafted subscript chain, a huge ``elif`` ladder) so one bad file is
    skipped loudly rather than aborting the whole run.
    """
    try:
        return _score_file(path, fold_nested), None
    except (OSError, UnicodeDecodeError, SyntaxError, RecursionError) as exc:
        reason = f"{type(exc).__name__}: {exc}"
        print(f"cococo: skipped {path}: {reason}", file=sys.stderr)
        return [], SkippedFile(path, reason)


def detect_encoding(path: Path) -> str:
    """The codec CPython itself would use for ``path`` (PEP 263 cookie, or BOM).

    Raises ``SyntaxError`` for an unknown codec name, the same way the interpreter
    rejects a bogus coding declaration.
    """
    with path.open("rb") as raw:
        return tokenize.detect_encoding(raw.readline)[0]


def read_source(path: Path, encoding: str | None = None) -> str:
    """Read ``path`` the way CPython reads a module: its own codec, newlines verbatim.

    ``utf-8-sig`` (a BOM file) decodes with the mark stripped, a ``coding:``
    declaration is honoured, and ``newline=""`` keeps ``\\r\\n`` intact so a
    rewrite touches only the lines it means to. Pass ``encoding`` to reuse an
    already-detected codec (a re-read, or a write-back in the same codec).
    """
    with path.open(encoding=encoding or detect_encoding(path), newline="") as handle:
        return handle.read()


def _parse_file(path: Path) -> tuple[str, ast.Module]:
    """Read and parse ``path``, returning ``(source, tree)``.

    The single read+parse site shared by the scanner and ``--explain``; it raises
    ``OSError`` / ``UnicodeDecodeError`` / ``SyntaxError`` for the caller to map
    to a skip or a clean message — one policy, not three drifting copies. The
    source text comes back too so the scanner can read ``# cococo: ignore``
    directives (comments are not in the AST).
    """
    source = read_source(path)
    return source, ast.parse(source, filename=str(path))


def _ignored_lines(source: str) -> set[int]:
    """Line numbers carrying a ``# cococo: ignore`` comment.

    ``source`` has already parsed cleanly (the caller parsed it first), so
    tokenizing it raises nothing; only real comment tokens are matched, so the
    directive text appearing inside a string literal does not count.
    """
    return {
        tok.start[0]
        for tok in tokenize.generate_tokens(io.StringIO(source).readline)
        if tok.type == tokenize.COMMENT and _IGNORE_DIRECTIVE in tok.string
    }


def _score_file(path: Path, fold_nested: bool) -> list[ScoredFunction]:
    """Parse and score every function in one file (raises on read/parse/score failure)."""
    source, tree = _parse_file(path)
    ignore = _ignored_lines(source)
    funcs: list[tuple[AnyFuncdef, str]] = []
    _collect(tree, "", funcs, fold_nested)
    return [_score_one(funcdef, qualname, path, fold_nested, ignore) for funcdef, qualname in funcs]


def _score_one(
    funcdef: AnyFuncdef, qualname: str, path: Path, fold_nested: bool, ignore: set[int]
) -> ScoredFunction:
    # Compute the breakdown once and carry it on the result; the JSON report and
    # gate-suggestion paths read ``.breakdown`` instead of re-walking the tree
    # (the scalar score is just its points sum).
    breakdown = get_cognitive_complexity_breakdown(funcdef, fold_nested)
    score = sum(c.points for c in breakdown)
    return ScoredFunction(
        score, path, funcdef.lineno, qualname, funcdef, breakdown, funcdef.lineno in ignore
    )


def scored_functions(paths: list[str], fold_nested: bool = False) -> list[ScoredFunction]:
    """Score every function found under ``paths``, keeping its AST node."""
    return scan(paths, fold_nested)[0]


def parse_target(target: str) -> tuple[Path, str | None, int | None]:
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


def find_function(
    path: Path,
    qualname: str | None,
    lineno: int | None,
    fold_nested: bool = False,
) -> tuple[AnyFuncdef, str]:
    """Locate one function in ``path`` by qualname or line number.

    With neither selector, the file must contain exactly one function.
    """
    _, tree = _parse_file(path)
    funcs: list[tuple[AnyFuncdef, str]] = []
    _collect(tree, "", funcs, fold_nested)
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
