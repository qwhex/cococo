import ast
from typing import NamedTuple

from cognitive_complexity.common_types import AnyFuncdef, is_funcdef
from cognitive_complexity.utils.ast import (
    call_targets_name,
    decorator_inner,
    describe_node,
    flatten_bool_op,
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

    The AST has no node for an ``else:`` keyword, so an ``else`` contribution
    (from ``if``/``for``/``while`` alike) reports the line just after the branch
    above it — exact unless a comment or blank line sits in the gap.
    """

    lineno: int
    label: str
    points: int
    nesting: int
    nesting_counted: bool


def get_cognitive_complexity(funcdef: AnyFuncdef, fold_nested: bool = False) -> int:
    """Total cognitive complexity: the sum of every scored construct's points."""
    return sum(c.points for c in get_cognitive_complexity_breakdown(funcdef, fold_nested))


def get_cognitive_complexity_breakdown(
    funcdef: AnyFuncdef, fold_nested: bool = False
) -> list[Contribution]:
    """Per-node breakdown of a function's cognitive complexity.

    Records every construct that contributed points and the nesting level in
    effect at that point. Recursive calls add a trailing synthetic entry. The
    ``points`` column sums to the total returned by
    :func:`get_cognitive_complexity`. By default named nested functions are *not*
    folded in — they are scored as their own units. With ``fold_nested=True``
    (the pre-2.0.0 model) a nested def folds into its enclosing function as a
    nesting level, and a decorator/closure factory is scored by its inner
    function.
    """
    inner = decorator_inner(funcdef) if fold_nested else None
    if inner is not None:
        return get_cognitive_complexity_breakdown(inner, fold_nested)

    contributions: list[Contribution] = []
    # Detect direct recursion inline during this single walk instead of a second
    # ast.walk. In unit mode the walk visits exactly the function's own scope, so
    # ``rec_name`` is set and a self-call is found here. In fold mode the walk
    # descends into folded nested defs, whose calls are NOT the outer's recursion,
    # so inline detection is disabled and the own-scope-only ``has_recursive_calls``
    # is used instead.
    rec_name = None if fold_nested else funcdef.name
    rec_found = [False]
    for node in funcdef.body:
        _collect_breakdown(node, 0, funcdef.lineno, contributions, fold_nested, rec_name, rec_found)
    recursive = has_recursive_calls(funcdef) if fold_nested else rec_found[0]
    if recursive:
        contributions.append(Contribution(funcdef.lineno, "recursion", 1, 0, False))
    return contributions


def _mark_recursion(node: ast.AST, rec_name: str | None, rec_found: list[bool]) -> None:
    """Flag direct recursion when ``node`` is a call to ``rec_name`` (None disables)."""
    if rec_name is not None and isinstance(node, ast.Call) and call_targets_name(node, rec_name):
        rec_found[0] = True


def _else_lineno(body: list[ast.stmt]) -> int:
    """The ``else:`` line, taken as the line after the branch it follows."""
    last = body[-1]
    return (last.end_lineno or last.lineno) + 1


def _collect_loop_else(node: ast.AST, nesting: int, out: list[Contribution]) -> None:
    """A ``for``/``while`` ``else`` scores +1 like an if-else, on its own entry.

    The AST hangs it off the loop node, so the generic walk would otherwise fold
    its point into the loop's contribution and label it as part of the loop.
    """
    if isinstance(node, (ast.For, ast.AsyncFor, ast.While)) and node.orelse:
        out.append(Contribution(_else_lineno(node.body), "else", 1, nesting, False))


def _collect_breakdown(
    node: ast.AST,
    increment_by: int,
    parent_lineno: int,
    out: list[Contribution],
    fold_nested: bool,
    rec_name: str | None,
    rec_found: list[bool],
) -> None:
    _mark_recursion(node, rec_name, rec_found)
    # In unit mode a named nested function is its own reporting unit (discovered
    # separately by the CLI, scored from nesting 0): it contributes nothing here
    # and the walk does not descend into it. In fold mode it is left to
    # process_node_itself, which treats it as a nesting incrementer. Lambdas are
    # anonymous and always fold.
    if not fold_nested and is_funcdef(node):
        return

    # `if`/`elif`/`else` chains need their body and orelse scored at different
    # nesting levels (the body nests one deeper; a trailing `elif` is a sibling
    # at the same level), which the uniform child walk below cannot express —
    # so they get their own handler.
    if isinstance(node, ast.If):
        _collect_if_breakdown(
            node, increment_by, out, fold_nested, rec_name, rec_found, is_elif_arm=False
        )
        return

    # A boolean condition scores as one construct spanning its whole operator
    # tree, and its operands still have to be walked — the uniform child walk
    # would instead re-score each nested `and`/`or` as a separate entry.
    if isinstance(node, ast.BoolOp):
        _collect_bool_op_breakdown(node, increment_by, out, fold_nested, rec_name, rec_found)
        return

    nesting_before = increment_by
    increment_by, base_complexity, should_iter_children = process_node_itself(
        node, increment_by, fold_nested
    )
    # Some scored nodes (ast.comprehension) carry no line of their own; fall
    # back to the nearest ancestor that did.
    lineno = getattr(node, "lineno", parent_lineno)

    _append_node_contribution(node, lineno, base_complexity, nesting_before, increment_by, out)
    _collect_loop_else(node, nesting_before, out)

    if should_iter_children:
        for child in ast.iter_child_nodes(node):
            _collect_breakdown(child, increment_by, lineno, out, fold_nested, rec_name, rec_found)


def _append_node_contribution(
    node: ast.AST,
    lineno: int,
    points: int,
    nesting_before: int,
    increment_by: int,
    out: list[Contribution],
) -> None:
    """Record what ``node`` alone scored, at the nesting level it sits at.

    A control-flow breaker bumped ``increment_by`` for its own body, so the level
    it sits at is the pre-bump value and its nesting penalty is baked into
    ``points``. A comprehension filter doesn't bump, so it sits at the ambient
    level with no nesting penalty.
    """
    if not points:
        return
    nesting_counted = increment_by != nesting_before
    node_nesting = increment_by - 1 if nesting_counted else nesting_before
    out.append(Contribution(lineno, describe_node(node), points, node_nesting, nesting_counted))


def _collect_bool_op_breakdown(
    node: ast.BoolOp,
    increment_by: int,
    out: list[Contribution],
    fold_nested: bool,
    rec_name: str | None,
    rec_found: list[bool],
) -> None:
    """+1 per sequence of like logical operators, reported on the condition's line.

    Boolean operands carry no nesting penalty of their own, so the whole tree is
    one entry at the ambient level; everything else in the operands is walked.
    """
    points, operands = flatten_bool_op(node)
    out.append(Contribution(node.lineno, describe_node(node), points, increment_by, False))
    for operand in operands:
        _collect_breakdown(
            operand, increment_by, node.lineno, out, fold_nested, rec_name, rec_found
        )


def _collect_if_breakdown(
    node: ast.If,
    increment_by: int,
    out: list[Contribution],
    fold_nested: bool,
    rec_name: str | None,
    rec_found: list[bool],
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
    _collect_breakdown(node.test, increment_by, node.lineno, out, fold_nested, rec_name, rec_found)
    for stmt in node.body:
        _collect_breakdown(stmt, body_level, node.lineno, out, fold_nested, rec_name, rec_found)

    orelse = node.orelse
    if len(orelse) == 1 and isinstance(orelse[0], ast.If):
        # `elif`: a sibling at the same nesting level, not a nested `if`.
        _collect_if_breakdown(
            orelse[0], increment_by, out, fold_nested, rec_name, rec_found, is_elif_arm=True
        )
    elif orelse:
        # `else`: +1, no nesting penalty; its body is scored one level deeper.
        out.append(Contribution(_else_lineno(node.body), "else", 1, increment_by, False))
        for stmt in orelse:
            _collect_breakdown(stmt, body_level, node.lineno, out, fold_nested, rec_name, rec_found)
