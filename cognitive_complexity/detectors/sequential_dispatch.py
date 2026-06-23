"""Detector: a run of sequential ``if subject == const: return`` siblings → dispatch table.

The existing ``split_dispatcher`` only recognises ``elif`` ladders and ``match``;
this catches the same refactor written as separate top-level ``if`` statements.
Emits the same ``split_dispatcher`` kind (it is the same refactor).

Soundness guards (per the spec's hardened C1):
- the subject is side-effect-free (``Name``/``Attribute``/``Subscript`` only — never a
  ``Call``), so collapsing N comparisons to one lookup can't change call counts;
- every arm is truly terminal (its body ends in ``return``/``raise``); a fall-through
  arm would lose later side effects;
- keys are hashable literals and distinct under dict normalisation (``1``/``True``/``1.0``
  collide), so the dict can't silently merge arms.
"""

from __future__ import annotations

import ast

from cognitive_complexity.common_types import AnyFuncdef, is_funcdef
from cognitive_complexity.detectors.base import (
    DISPATCH_MIN_ARMS,
    DetectorContext,
    Suggestion,
    make_suggestion,
    simple_equality_test,
)

KIND = "split_dispatcher"
TITLE = "Replace the branch ladder with a dispatch table"
AUTOFIXABLE = False
STEPS = (
    "Map each constant to its handler/value in a module-level dict.",
    "Replace the if-chain with a single `TABLE.get(subject, default)` lookup.",
    "Keep this function a shallow orchestrator.",
)


def detect(ctx: DetectorContext) -> list[Suggestion]:
    out: list[Suggestion] = []
    for block in _statement_blocks(ctx.funcdef):
        out += _runs_in_block(block, ctx.total)
    return out


def _statement_blocks(funcdef: AnyFuncdef) -> list[list[ast.stmt]]:
    """Every statement-list block under ``funcdef``, not descending into nested defs."""
    blocks: list[list[ast.stmt]] = []

    def visit(block: list[ast.stmt]) -> None:
        blocks.append(block)
        for stmt in block:
            if is_funcdef(stmt):
                continue
            for sub in _sub_blocks(stmt):
                visit(sub)

    visit(funcdef.body)
    return blocks


def _sub_blocks(stmt: ast.stmt) -> list[list[ast.stmt]]:
    out: list[list[ast.stmt]] = []
    for field in ("body", "orelse", "finalbody"):
        block = getattr(stmt, field, None)
        if isinstance(block, list) and block and isinstance(block[0], ast.stmt):
            out.append(block)
    out.extend(handler.body for handler in getattr(stmt, "handlers", []))
    out.extend(case.body for case in getattr(stmt, "cases", []))
    return out


def _runs_in_block(block: list[ast.stmt], total: int) -> list[Suggestion]:
    out: list[Suggestion] = []
    i = 0
    while i < len(block):
        arm = _dispatch_arm(block[i])
        if arm is None:
            i += 1
            continue
        end, keys = _extend_run(block, i, arm[0])
        if (end - i) >= DISPATCH_MIN_ARMS and len(set(keys)) == len(keys):
            out.append(_run_suggestion(block, i, end, total))
        i = end
    return out


def _extend_run(block: list[ast.stmt], start: int, subject: str) -> tuple[int, list[object]]:
    """Extend a run of same-subject dispatch arms from ``start``; return (end, keys)."""
    keys: list[object] = []
    j = start
    while j < len(block):
        arm = _dispatch_arm(block[j])
        if arm is None or arm[0] != subject:
            break
        keys.append(arm[1])
        j += 1
    return j, keys


def _run_suggestion(block: list[ast.stmt], start: int, end: int, total: int) -> Suggestion:
    last = block[end - 1]
    return make_suggestion(
        kind=KIND,
        title=TITLE,
        steps=STEPS,
        autofixable=AUTOFIXABLE,
        start=block[start].lineno,
        end=last.end_lineno or last.lineno,
        reduction=(end - start) - 1,
        total=total,
    )


def _dispatch_arm(stmt: ast.stmt) -> tuple[str, object] | None:
    """``(subject, key)`` if ``stmt`` is ``if subject == const: <terminal>``, else None."""
    if not isinstance(stmt, ast.If) or stmt.orelse:
        return None
    if not isinstance(stmt.body[-1], (ast.Return, ast.Raise)):
        return None
    return simple_equality_test(stmt.test)
