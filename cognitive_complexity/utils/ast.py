import ast
from collections.abc import Iterator

from cognitive_complexity.common_types import AnyFuncdef, is_funcdef


def call_targets_name(call: ast.Call, name: str) -> bool:
    func = call.func
    if isinstance(func, ast.Name):
        return func.id == name
    if isinstance(func, ast.Attribute) and func.attr == name:
        # method recursion: self.name(...) / cls.name(...)
        return isinstance(func.value, ast.Name) and func.value.id in ("self", "cls")
    return False


def _returns_name(stmt: ast.stmt, name: str) -> bool:
    return (
        isinstance(stmt, ast.Return) and isinstance(stmt.value, ast.Name) and stmt.value.id == name
    )


def decorator_inner(funcdef: AnyFuncdef) -> AnyFuncdef | None:
    """The single inner function a decorator/closure factory returns, else ``None``.

    A function that defines exactly one inner function and returns *that function
    by name* is structurally a decorator (or value-returning closure factory); in
    fold mode it is scored as that inner function (pre-2.0.0 compat). Returning
    the node — rather than a bool — lets callers use the narrowed inner directly,
    so they need not re-index and re-type ``funcdef.body[0]``.
    """
    body = _without_docstring(funcdef.body)
    if len(body) != 2:
        return None
    inner = body[0]
    if is_funcdef(inner) and _returns_name(body[1], inner.name):
        return inner
    return None


def _without_docstring(body: list[ast.stmt]) -> list[ast.stmt]:
    """``body`` minus a leading docstring, so documenting a function can't reshape it."""
    first = body[0]  # a funcdef body is never empty
    is_docstring = (
        isinstance(first, ast.Expr)
        and isinstance(first.value, ast.Constant)
        and isinstance(first.value.value, str)
    )
    return body[1:] if is_docstring else body


def _walk_own_scope(funcdef: AnyFuncdef) -> Iterator[ast.AST]:
    """Yield every node in ``funcdef``'s own scope, not descending into nested defs.

    Named nested ``def``/``async def`` are independent scoring units (Option A),
    so a call living inside one belongs to that unit, not to ``funcdef``. Walking
    the whole subtree (``ast.walk``) would miscount a call to ``funcdef``'s name
    made from inside a nested def as the outer function's recursion. The walk is
    iterative (an explicit stack) so a deeply nested expression can't blow the
    interpreter's recursion limit just while we look for recursion.
    """
    stack: list[ast.AST] = list(ast.iter_child_nodes(funcdef))
    while stack:
        node = stack.pop()
        yield node
        if not is_funcdef(node):
            stack.extend(ast.iter_child_nodes(node))


def has_recursive_calls(funcdef: AnyFuncdef) -> bool:
    # Direct recursion only: a call by the function's own name, or a
    # self/cls method call to it. Indirect/mutual recursion (a -> b -> a) is
    # not detected; that needs a whole-program call graph, out of scope for a
    # per-function AST metric. The walk stays within funcdef's own scope so a
    # call to its name from inside a nested def is not miscounted here.
    return any(
        call_targets_name(node, funcdef.name)
        for node in _walk_own_scope(funcdef)
        if isinstance(node, ast.Call)
    )


# Static node-type -> label dispatch. ``ast.If`` is handled separately because
# its label depends on whether it is an elif arm, which is positional. Named
# nested ``def``s are not here: they are scored as their own reporting units, not
# as a construct of the enclosing function (see ``api._collect_breakdown``).
_NODE_LABELS: tuple[tuple[type[ast.AST] | tuple[type[ast.AST], ...], str], ...] = (
    (ast.IfExp, "ternary"),
    ((ast.For, ast.AsyncFor), "for"),
    (ast.While, "while"),
    (ast.ExceptHandler, "except"),
    (ast.Match, "match"),
    (ast.Lambda, "lambda"),
    (ast.BoolOp, "bool-op"),
    (ast.comprehension, "comprehension-if"),
)


def describe_node(node: ast.AST, *, is_elif_arm: bool = False) -> str:
    """Short human label for a scored construct, used in breakdowns.

    Whether an ``ast.If`` is an ``elif`` depends on its position (is it the
    ``else`` branch of another ``if``?), which the node cannot know on its own,
    so the caller supplies ``is_elif_arm``.
    """
    if isinstance(node, ast.If):
        return "elif" if is_elif_arm else "if"
    for types, label in _NODE_LABELS:
        if isinstance(node, types):
            return label
    return type(node).__name__


def process_control_flow_breaker(increment_by: int) -> tuple[int, int, bool]:
    """A ternary/loop/except/match: +1 plus the nesting penalty, and it opens a level.

    A match/switch is a single structural increment regardless of the number of
    cases (Sonar treats a switch as one branch). A loop's ``else`` is scored
    separately by ``api._collect_loop_else`` so it gets its own breakdown entry.
    ``ast.If`` never reaches here: ``api._collect_if_breakdown`` handles it, so
    that if/elif/else chains can score body and orelse at different levels.
    """
    increment_by += 1
    return increment_by, increment_by, True


def flatten_bool_op(node: ast.BoolOp) -> tuple[int, list[ast.AST]]:
    """The boolean expression at ``node``: how many ``BoolOp``s, and its operands.

    ``and``/``or``/``not`` chain into one condition at one nesting level, so the
    expression scores as a single construct worth +1 per sequence of like
    operators (Campbell B1) — ``(a and b) or (c and d)`` is 3, and a ``not`` is
    transparent rather than a boundary. The returned operands are everything
    else, in source order; they still need walking, since an operand can hold a
    ternary, a comprehension, a lambda or a recursive call.
    """
    count = 0
    operands: list[ast.AST] = []
    stack: list[ast.AST] = [node]
    while stack:
        current = stack.pop()
        if isinstance(current, ast.BoolOp):
            count += 1
            stack.extend(reversed(current.values))
        elif isinstance(current, ast.UnaryOp) and isinstance(current.op, ast.Not):
            stack.append(current.operand)
        else:
            operands.append(current)
    return count, operands


def process_node_itself(
    node: ast.AST,
    increment_by: int,
    fold_nested: bool = False,
) -> tuple[int, int, bool]:
    # `ast.If` and `ast.BoolOp` are intercepted by api._collect_if_breakdown /
    # api._collect_bool_op_breakdown before reaching here.
    control_flow_breakers = (
        ast.For,
        ast.AsyncFor,
        ast.While,
        ast.IfExp,
        ast.ExceptHandler,
        ast.Match,
    )
    # Lambdas always add a nesting level and fold in. In the default unit mode
    # named nested `def`s are scored as their own units and never reach here; in
    # fold mode (pre-2.0.0 compat) they too add a nesting level and fold in.
    incrementers_nodes: tuple[type[ast.AST], ...] = (
        (ast.Lambda, ast.FunctionDef, ast.AsyncFunctionDef) if fold_nested else (ast.Lambda,)
    )

    if isinstance(node, control_flow_breakers):
        return process_control_flow_breaker(increment_by)
    elif isinstance(node, incrementers_nodes):
        increment_by += 1
        return increment_by, 0, True
    elif isinstance(node, ast.comprehension):
        # each filter condition in a comprehension is a decision point
        return increment_by, len(node.ifs), True
    return increment_by, 0, True
