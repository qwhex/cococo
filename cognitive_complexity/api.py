import ast

from typing import NamedTuple

from cognitive_complexity.common_types import AnyFuncdef
from cognitive_complexity.utils.ast import (
    describe_node, has_recursive_calls, is_decorator, process_child_nodes,
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
    structural cost is ``points - nesting``. For bool-ops and comprehension
    filters ``nesting`` is only ambient context (``nesting_counted`` false) and
    all of ``points`` is structural.
    """

    lineno: int
    label: str
    points: int
    nesting: int
    nesting_counted: bool


def get_cognitive_complexity(funcdef: AnyFuncdef) -> int:
    if is_decorator(funcdef):
        return get_cognitive_complexity(funcdef.body[0])  # type: ignore

    complexity = 0
    for node in funcdef.body:
        complexity += get_cognitive_complexity_for_node(node)
    if has_recursive_calls(funcdef):
        complexity += 1
    return complexity


def get_cognitive_complexity_for_node(
        node: ast.AST,
        increment_by: int = 0,
) -> int:
    increment_by, base_complexity, should_iter_children = process_node_itself(node, increment_by)

    child_complexity = 0
    if should_iter_children:
        child_complexity += process_child_nodes(
            node,
            increment_by,
            get_cognitive_complexity_for_node,
        )

    return base_complexity + child_complexity


def get_cognitive_complexity_breakdown(funcdef: AnyFuncdef) -> list[Contribution]:
    """Per-node breakdown of a function's cognitive complexity.

    Mirrors :func:`get_cognitive_complexity` but, instead of only the total,
    records every construct that contributed points and the nesting level in
    effect at that point. Recursive calls add a trailing synthetic entry, just
    as the scalar API adds ``+1`` for recursion. The ``points`` column sums to
    the total complexity.
    """
    if is_decorator(funcdef):
        return get_cognitive_complexity_breakdown(funcdef.body[0])  # type: ignore

    contributions: list[Contribution] = []
    for node in funcdef.body:
        _collect_breakdown(node, 0, funcdef.lineno, contributions)
    if has_recursive_calls(funcdef):
        contributions.append(Contribution(funcdef.lineno, 'recursion', 1, 0, False))
    return contributions


def _collect_breakdown(
    node: ast.AST,
    increment_by: int,
    parent_lineno: int,
    out: list[Contribution],
) -> None:
    nesting_before = increment_by
    increment_by, base_complexity, should_iter_children = process_node_itself(node, increment_by)
    # Some scored nodes (ast.comprehension) carry no line of their own; fall
    # back to the nearest ancestor that did.
    lineno = getattr(node, 'lineno', parent_lineno)

    if base_complexity:
        # Control-flow breakers bumped ``increment_by`` for their own body, so
        # the level *they* sit at is the pre-bump value and their nesting penalty
        # is baked into base_complexity. Bool-ops / comprehension filters don't
        # bump, so they sit at the ambient level with no nesting penalty.
        nesting_counted = increment_by != nesting_before
        node_nesting = increment_by - 1 if nesting_counted else nesting_before
        out.append(Contribution(
            lineno, describe_node(node), base_complexity, node_nesting, nesting_counted,
        ))

    if should_iter_children:
        for child in ast.iter_child_nodes(node):
            _collect_breakdown(child, increment_by, lineno, out)
