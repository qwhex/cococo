from __future__ import annotations

import ast
from pathlib import Path
from typing import TYPE_CHECKING, NamedTuple, TypeGuard

if TYPE_CHECKING:
    from cognitive_complexity.api import Contribution

AnyFuncdef = ast.FunctionDef | ast.AsyncFunctionDef


def is_funcdef(node: ast.AST) -> TypeGuard[AnyFuncdef]:
    """True if ``node`` is a (possibly async) function definition.

    One definition of "scorable function unit" for every tree-walker; the
    ``TypeGuard`` return preserves type narrowing at the call sites (e.g. reading
    ``node.name``) under strict mypy.
    """
    return isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))


class ScoredFunction(NamedTuple):
    """A scored function plus the node it was scored from (for breakdowns/fixes).

    ``breakdown`` is the per-construct scoring computed once at discovery time;
    ``score`` is its points sum. Carrying it avoids a second walk in the JSON
    report and gate-suggestion paths. ``ignored`` is true when the function's
    ``def`` line carries a ``# cococo: ignore`` directive, which excludes it from
    the ``--max`` gate.
    """

    score: int
    path: Path
    lineno: int
    qualname: str
    funcdef: AnyFuncdef
    breakdown: list[Contribution]
    ignored: bool = False


class SkippedFile(NamedTuple):
    """A file the scanner could not read, parse, or score, with the reason why."""

    path: Path
    reason: str
