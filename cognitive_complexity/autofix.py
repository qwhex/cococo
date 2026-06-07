"""Safe, formatting-preserving guard-clause flattening for ``--fix``.

Only one transform, and only where it is provably behavior-preserving: an ``if``
with no ``else`` that is the *last* statement of a function body or loop body is
rewritten into an early ``return``/``continue`` guard, and its body de-indented
one level. Because the ``if`` is last, returning/continuing early when the
condition is false changes nothing. Anything that fails the strict preconditions
in :func:`_is_safe_guard` is left exactly as it was.

Edits are made on the source text (not via ``ast.unparse``) so comments and
formatting in the untouched body survive.
"""

from __future__ import annotations

import ast

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


def _find_guard(tree: ast.AST, source: str) -> tuple[ast.If, str] | None:
    candidates: list[tuple[ast.If, str]] = []
    for block, keyword in _guarded_blocks(tree):
        last = block[-1] if block else None
        if isinstance(last, ast.If) and _is_safe_guard(last, source):
            candidates.append((last, keyword))
    if not candidates:
        return None
    return min(candidates, key=lambda c: c[0].lineno)


def _guarded_blocks(tree: ast.AST) -> list[tuple[list[ast.stmt], str]]:
    blocks: list[tuple[list[ast.stmt], str]] = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            blocks.append((node.body, "return"))
        elif isinstance(node, _LOOP_TYPES):
            blocks.append((node.body, "continue"))
    return blocks


def _is_safe_guard(node: ast.If, source: str) -> bool:
    if node.orelse or not node.body:
        return False
    body_first = node.body[0]
    if body_first.lineno <= node.lineno:  # single-line `if x: ...`
        return False
    if node.test.lineno != (node.test.end_lineno or node.test.lineno):  # multi-line test
        return False
    if not _has_nested_breaker(node.body):  # flattening would save nothing
        return False
    return _indent_unit(node, source) > 0


def _has_nested_breaker(body: list[ast.stmt]) -> bool:
    return any(isinstance(inner, _BREAKER_TYPES) for stmt in body for inner in ast.walk(stmt))


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


def _inverted_condition(test: ast.expr, source: str) -> str:
    if isinstance(test, ast.UnaryOp) and isinstance(test.op, ast.Not):
        inner = ast.get_source_segment(source, test.operand)
        if inner is not None:
            return inner
    segment = ast.get_source_segment(source, test)
    return f"not ({segment})"
