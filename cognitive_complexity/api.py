import ast
from typing import NamedTuple

from cognitive_complexity.common_types import AnyFuncdef
from cognitive_complexity.utils.ast import (
    describe_node,
    has_recursive_calls,
    process_node_itself,
)


class Contribution(NamedTuple):
    """One scored construct in a function's cognitive-complexity breakdown.

    ``lineno`` is the source line, ``label`` names the construct (e.g. ``if``,
    ``for``, ``bool-op``), and ``points`` is what this node alone added to the
    score, so the sum of every contribution's ``points`` equals the function's
    total complexity. ``nesting`` is the nesting depth in effect at this node.

    For control-flow breakers (if/for/while/except/match/ternary) the nesting
    penalty is *part of* ``points`` and ``nesting_counted`` is true, so the
    structural cost is ``points - nesting``. For ``elif``/``else``, bool-ops and
    comprehension filters ``nesting`` is only ambient context
    (``nesting_counted`` false) and all of ``points`` is structural.
    """

    lineno: int
    label: str
    points: int
    nesting: int
    nesting_counted: bool


def get_cognitive_complexity(funcdef: AnyFuncdef) -> int:
    """Total cognitive complexity: the sum of every scored construct's points."""
    return sum(c.points for c in get_cognitive_complexity_breakdown(funcdef))


def get_cognitive_complexity_breakdown(funcdef: AnyFuncdef) -> list[Contribution]:
    """Per-node breakdown of a function's cognitive complexity.

    Records every construct that contributed points and the nesting level in
    effect at that point. Recursive calls add a trailing synthetic entry. The
    ``points`` column sums to the total returned by
    :func:`get_cognitive_complexity`. Named nested functions are *not* folded in
    — they are scored as their own units (see :func:`_collect_breakdown`).
    """
    contributions: list[Contribution] = []
    for node in funcdef.body:
        _collect_breakdown(node, 0, funcdef.lineno, contributions)
    if has_recursive_calls(funcdef):
        contributions.append(Contribution(funcdef.lineno, "recursion", 1, 0, False))
    return contributions


def _collect_breakdown(
    node: ast.AST,
    increment_by: int,
    parent_lineno: int,
    out: list[Contribution],
) -> None:
    # A named nested function is its own reporting unit (discovered separately by
    # the CLI and scored from nesting level 0). It contributes nothing to the
    # enclosing function and the walk does not descend into it. Lambdas are
    # anonymous and still fold (handled by process_node_itself).
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
        return

    # `if`/`elif`/`else` chains need their body and orelse scored at different
    # nesting levels (the body nests one deeper; a trailing `elif` is a sibling
    # at the same level), which the uniform child walk below cannot express —
    # so they get their own handler.
    if isinstance(node, ast.If):
        _collect_if_breakdown(node, increment_by, out, is_elif_arm=False)
        return

    nesting_before = increment_by
    increment_by, base_complexity, should_iter_children = process_node_itself(node, increment_by)
    # Some scored nodes (ast.comprehension) carry no line of their own; fall
    # back to the nearest ancestor that did.
    lineno = getattr(node, "lineno", parent_lineno)

    if base_complexity:
        # Control-flow breakers bumped ``increment_by`` for their own body, so
        # the level they sit at is the pre-bump value and their nesting penalty
        # is baked into base_complexity. Bool-ops / comprehension filters don't
        # bump, so they sit at the ambient level with no nesting penalty.
        nesting_counted = increment_by != nesting_before
        node_nesting = increment_by - 1 if nesting_counted else nesting_before
        out.append(
            Contribution(
                lineno, describe_node(node), base_complexity, node_nesting, nesting_counted
            )
        )

    if should_iter_children:
        for child in ast.iter_child_nodes(node):
            _collect_breakdown(child, increment_by, lineno, out)


def _collect_if_breakdown(
    node: ast.If,
    increment_by: int,
    out: list[Contribution],
    *,
    is_elif_arm: bool,
) -> None:
    # B1: +1 for the `if`/`elif` itself. B3: a nesting penalty applies to a
    # leading `if` (the more deeply nested, the costlier) but not to `elif` or
    # `else`. B2: each branch body is scored one nesting level deeper.
    penalty = 0 if is_elif_arm else increment_by
    out.append(
        Contribution(
            node.lineno,
            describe_node(node, is_elif_arm=is_elif_arm),
            1 + penalty,
            increment_by,
            not is_elif_arm,
        )
    )
    body_level = increment_by + 1
    _collect_breakdown(node.test, increment_by, node.lineno, out)
    for stmt in node.body:
        _collect_breakdown(stmt, body_level, node.lineno, out)

    orelse = node.orelse
    if len(orelse) == 1 and isinstance(orelse[0], ast.If):
        # `elif`: a sibling at the same nesting level, not a nested `if`.
        _collect_if_breakdown(orelse[0], increment_by, out, is_elif_arm=True)
    elif orelse:
        # `else`: +1, no nesting penalty; its body is scored one level deeper.
        out.append(Contribution(orelse[0].lineno, "else", 1, increment_by, False))
        for stmt in orelse:
            _collect_breakdown(stmt, body_level, node.lineno, out)
