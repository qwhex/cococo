"""Safe, formatting-preserving guard-clause flattening for ``--fix``.

Only one transform, and only where it is provably behavior-preserving: an ``if``
with no ``else`` that is the *last* statement of a function body or loop body is
rewritten into an early ``return``/``continue`` guard, and its body de-indented
one level. Because the ``if`` is last, returning/continuing early when the
condition is false changes nothing. Anything that fails the strict preconditions
in :func:`is_flattenable_guard` is left exactly as it was.

That precondition is AST-only on purpose: the ``guard_clause`` detector calls it
(via :func:`flattenable_guard_ids`) to decide whether a suggestion may advertise
``[--fix]``, so the badge and the rewriter cannot drift apart. The one check that
needs the source text — tab indentation — stays here, and the guards it costs are
counted by :func:`refused_guards` so ``--fix`` can say why it did nothing.

Edits are made on the source text (not via ``ast.unparse``) so comments and
formatting in the untouched body survive.

Why hand-rolled text surgery and not a CST library (LibCST)? LibCST was
considered and rejected: its headline win — comment/whitespace preservation — is
already achieved here for the single transform that exists, and cococo declares
zero runtime dependencies by design (it is a low-level dependency of other
pipelines), a posture LibCST's native extension + ``pyyaml`` would break.
**Reopen trigger:** this calculus holds only because there is exactly one
provably-safe transform. When a *second* non-trivial rewrite is added, re-run the
LibCST bake-off — string surgery does not compose across transforms (each one
re-derives indent units, newline style, and segment boundaries), so at N>=2 the
decision flips to adopting a CST.
"""

from __future__ import annotations

import ast
import os
import stat
import tempfile
from collections.abc import Sequence
from pathlib import Path

from cognitive_complexity.common_types import AnyFuncdef, is_funcdef

# The transform is idempotent (a flattened guard is no longer the last statement
# of its block), so this only caps pathological input; it is never reached in
# practice.
_MAX_PASSES = 1000

_LOOP_TYPES = (ast.For, ast.AsyncFor, ast.While)
_BREAKER_TYPES = (
    ast.For,
    ast.AsyncFor,
    ast.While,
    ast.If,
    ast.IfExp,
    ast.ExceptHandler,
    ast.Match,
)


def fix_source(source: str) -> tuple[str, int]:
    """Apply every safe guard-clause flattening in ``source``.

    Returns the rewritten source and the number of guards applied. Raises
    ``SyntaxError`` if ``source`` does not parse.
    """
    fixes = 0
    for _ in range(_MAX_PASSES):
        tree = ast.parse(source)
        target = _find_guard(tree, source)
        if target is None:
            break
        node, keyword = target
        source = _apply_guard(source, node, keyword)
        fixes += 1
    return source, fixes


def refused_guards(source: str) -> int:
    """Flattenable guards this rewriter still declines, on source-text grounds.

    Only tab indentation lands here: every other precondition is AST-visible, so
    :func:`is_flattenable_guard` already keeps the ``[--fix]`` badge off those. Lets
    ``--fix`` explain a zero instead of reporting it silently.
    """
    if "\t" not in source:
        return 0
    return sum(1 for node, _ in _tail_guards(ast.parse(source)) if _indent_unit(node, source) <= 0)


def _find_guard(tree: ast.AST, source: str) -> tuple[ast.If, str] | None:
    candidates = [(n, kw) for n, kw in _tail_guards(tree) if _indent_unit(n, source) > 0]
    if not candidates:
        return None
    return min(candidates, key=lambda c: c[0].lineno)


def _tail_guards(tree: ast.AST) -> list[tuple[ast.If, str]]:
    """Every block-final ``if`` in ``tree`` that the AST-only precondition accepts."""
    guards: list[tuple[ast.If, str]] = []
    for block, keyword in _guarded_blocks(tree):
        last = block[-1] if block else None
        if isinstance(last, ast.If) and is_flattenable_guard(last):
            guards.append((last, keyword))
    return guards


def _guarded_blocks(tree: ast.AST) -> list[tuple[list[ast.stmt], str]]:
    blocks: list[tuple[list[ast.stmt], str]] = []
    for node in ast.walk(tree):
        if is_funcdef(node):
            blocks.append((node.body, "return"))
        elif isinstance(node, _LOOP_TYPES):
            blocks.append((node.body, "continue"))
    return blocks


def flattenable_guard_ids(funcdef: AnyFuncdef, regions: Sequence[ast.stmt]) -> set[int]:
    """``id()`` of every ``if`` in ``funcdef`` that ``--fix`` would rewrite.

    Position matters as much as shape: an ``if`` is only safely invertible when it
    ends its block, so the blocks are ``funcdef``'s own body plus the body of each
    loop in ``regions`` (the detector's precomputed region list — no second walk).
    Nested defs are separate units and are scored, and fixed, on their own.
    """
    blocks = [funcdef.body, *(r.body for r in regions if isinstance(r, _LOOP_TYPES))]
    ids: set[int] = set()
    for block in blocks:
        last = block[-1]
        if isinstance(last, ast.If) and is_flattenable_guard(last):
            ids.add(id(last))
    return ids


def is_flattenable_guard(node: ast.If) -> bool:
    """The AST-only half of the precondition, shared with the ``guard_clause`` detector.

    Says nothing about position (see :func:`flattenable_guard_ids`) or indentation
    (see :func:`refused_guards`) — only that the ``if`` itself has the shape the
    rewrite needs.
    """
    if node.orelse or not node.body:
        return False
    if node.body[0].lineno <= node.lineno:  # single-line `if x: ...`
        return False
    if node.test.lineno != (node.test.end_lineno or node.test.lineno):  # multi-line test
        return False
    if not _has_nested_breaker(node.body):  # flattening would save nothing
        return False
    return not _has_multiline_string(node.body)  # blind dedent would corrupt string content


def _has_nested_breaker(body: list[ast.stmt]) -> bool:
    return any(isinstance(inner, _BREAKER_TYPES) for stmt in body for inner in ast.walk(stmt))


def _has_multiline_string(body: list[ast.stmt]) -> bool:
    """True if any string / f-string literal in the body spans multiple lines.

    Dedenting such a body line-by-line (``_dedent``) would strip leading spaces
    that are *content* of the literal, silently changing its value — so the
    guard is left untouched rather than risk corrupting source.
    """
    return any(
        isinstance(inner, (ast.Constant, ast.JoinedStr)) and inner.lineno != inner.end_lineno
        for stmt in body
        for inner in ast.walk(stmt)
    )


def _leading_ws(line: str) -> str:
    return line[: len(line) - len(line.lstrip())]


def _indent_unit(node: ast.If, source: str) -> int:
    """Spaces the body sits below the ``if``; 0 if either uses tab indentation."""
    lines = source.splitlines()
    if_ws = _leading_ws(lines[node.lineno - 1])
    body_ws = _leading_ws(lines[node.body[0].lineno - 1])
    if "\t" in if_ws or "\t" in body_ws:
        return 0
    return len(body_ws) - len(if_ws)


def _apply_guard(source: str, node: ast.If, keyword: str) -> str:
    lines = source.splitlines(keepends=True)
    header_idx = node.lineno - 1
    end = node.end_lineno or node.lineno
    header = lines[header_idx]
    newline = "\r\n" if header.endswith("\r\n") else "\n"
    if_indent = _leading_ws(header)
    unit = _indent_unit(node, source)
    body_indent = if_indent + " " * unit
    condition = _inverted_condition(node.test, source)
    new_header = f"{if_indent}if {condition}:{newline}{body_indent}{keyword}{newline}"

    out = lines[:header_idx]
    out.append(new_header)
    out.extend(_dedent(lines[i], unit) for i in range(header_idx + 1, end))
    out.extend(lines[end:])
    return "".join(out)


def _dedent(line: str, unit: int) -> str:
    return line[unit:] if line[:unit] == " " * unit else line


# Membership/identity comparisons whose negation is *guaranteed* to be another
# comparison by the language spec: ``x not in y`` is defined as ``not (x in y)``
# and ``x is not y`` as ``not (x is y)``. Ordering and equality operators are
# deliberately absent — ``not (x < y)`` differs from ``x >= y`` for NaN, and a
# class may define ``__eq__``/``__ne__`` inconsistently — so those keep the safe
# ``not (...)`` wrapper rather than risk a behaviour change.
_NEGATED_CMP: dict[type[ast.cmpop], str] = {
    ast.In: "not in",
    ast.NotIn: "in",
    ast.Is: "is not",
    ast.IsNot: "is",
}

# ``not X`` reassociates when ``X`` binds looser than ``not`` (``not a and b`` is
# ``(not a) and b``), so these constructs need the wrapping parens; calls, names,
# and attributes bind tighter and the parens would be redundant noise a formatter
# strips. ``Compare`` is included because the membership/identity cases that *can*
# be inverted cleanly are flipped earlier (in :func:`_flip_comparison`) and never
# reach here — only the ones kept as ``not (...)`` for safety (ordering, equality,
# chained) fall through, and ``not k in a in b`` without parens would still trip
# the very ``E713`` lint we are trying to avoid.
_NEEDS_PARENS = (ast.BoolOp, ast.IfExp, ast.Lambda, ast.NamedExpr, ast.Compare)


def _inverted_condition(test: ast.expr, source: str) -> str:
    if isinstance(test, ast.UnaryOp) and isinstance(test.op, ast.Not):
        inner = ast.get_source_segment(source, test.operand)
        if inner is not None:
            return inner
    flipped = _flip_comparison(test, source)
    if flipped is not None:
        return flipped
    segment = ast.get_source_segment(source, test)
    if isinstance(test, _NEEDS_PARENS):
        return f"not ({segment})"
    return f"not {segment}"


def _flip_comparison(test: ast.expr, source: str) -> str | None:
    """Negate a single membership/identity comparison by flipping its operator.

    Returns ``None`` for anything that is not a one-operator ``in``/``is``
    comparison — chained comparisons (``a in b in c``), other operators, and
    non-comparisons fall back to the ``not (...)`` wrapper in the caller.
    """
    if not isinstance(test, ast.Compare) or len(test.ops) != 1:
        return None
    operator = _NEGATED_CMP.get(type(test.ops[0]))
    if operator is None:
        return None
    # Operands of a freshly-parsed comparison always carry position info, so
    # get_source_segment never returns None here — same assumption the caller
    # makes for the whole-test segment.
    left = ast.get_source_segment(source, test.left)
    right = ast.get_source_segment(source, test.comparators[0])
    return f"{left} {operator} {right}"


def atomic_write(path: Path, data: str, encoding: str = "utf-8") -> None:
    """Write ``data`` to ``path`` atomically, preserving its file mode.

    Writes to a temp file in the same directory, fsyncs it, then ``os.replace``s
    it over ``path`` — atomic within a filesystem, so a crash mid-write leaves
    the previous file intact rather than truncated/half-written, and a failed
    write leaves no partial file at all. The temp file is removed if anything
    fails (including on interrupt). ``newline=""`` keeps the data's line endings
    byte-for-byte (the transform may emit ``\\r\\n``); ``encoding`` should be the
    codec the source was read with, so a PEP 263 / BOM file is written back as
    itself. A destination that does not exist yet keeps the temp file's mode.

    The replace targets ``path`` itself: callers must not pass a symlink they
    want to keep (see ``cli._fix_one_file``, which skips them).
    """
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    tmp_file = Path(tmp)
    try:
        with os.fdopen(fd, "w", encoding=encoding, newline="") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        if path.exists():
            tmp_file.chmod(stat.S_IMODE(path.stat().st_mode))
        tmp_file.replace(path)
    except BaseException:
        tmp_file.unlink(missing_ok=True)
        raise
