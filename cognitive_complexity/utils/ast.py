import ast
from collections.abc import Iterator

from cognitive_complexity.common_types import AnyFuncdef


def _call_targets_name(call: ast.Call, name: str) -> bool:
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
    if len(funcdef.body) != 2:
        return None
    inner = funcdef.body[0]
    if isinstance(inner, (ast.FunctionDef, ast.AsyncFunctionDef)) and _returns_name(
        funcdef.body[1], inner.name
    ):
        return inner
    return None


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
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            stack.extend(ast.iter_child_nodes(node))


def has_recursive_calls(funcdef: AnyFuncdef) -> bool:
    # Direct recursion only: a call by the function's own name, or a
    # self/cls method call to it. Indirect/mutual recursion (a -> b -> a) is
    # not detected; that needs a whole-program call graph, out of scope for a
    # per-function AST metric. The walk stays within funcdef's own scope so a
    # call to its name from inside a nested def is not miscounted here.
    return any(
        _call_targets_name(node, funcdef.name)
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


def process_control_flow_breaker(
    node: ast.For | ast.AsyncFor | ast.While | ast.IfExp | ast.ExceptHandler | ast.Match,
    increment_by: int,
) -> tuple[int, int, bool]:
    # `ast.If` is handled by api._collect_if_breakdown, not here, so that
    # if/elif/else chains can score body and orelse at different nesting levels.
    if isinstance(node, ast.IfExp):
        # C if A else B; ternary operator equivalent
        increment = 0
        increment_by += 1
    elif isinstance(node, ast.ExceptHandler):
        # +1 for the catch/except-handler
        increment = 0
        increment_by += 1
    elif isinstance(node, ast.Match):
        # a match/switch is a single structural increment plus a nesting level,
        # regardless of the number of cases (Sonar treats switch as one branch)
        increment = 0
        increment_by += 1
    elif node.orelse:
        # +1 for the else and add a nesting level
        increment = 1
        increment_by += 1
    else:
        # no 'else' to count, just add a nesting level
        increment = 0
        increment_by += 1
    return increment_by, max(1, increment_by) + increment, True


def process_node_itself(
    node: ast.AST,
    increment_by: int,
    fold_nested: bool = False,
) -> tuple[int, int, bool]:
    # `ast.If` is intercepted by api._collect_if_breakdown before reaching here.
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
        return process_control_flow_breaker(node, increment_by)
    elif isinstance(node, incrementers_nodes):
        increment_by += 1
        return increment_by, 0, True
    elif isinstance(node, ast.BoolOp):
        inner_boolops_amount = len([n for n in ast.walk(node) if isinstance(n, ast.BoolOp)])
        base_complexity = inner_boolops_amount
        return increment_by, base_complexity, False
    elif isinstance(node, ast.comprehension):
        # each filter condition in a comprehension is a decision point
        return increment_by, len(node.ifs), True
    return increment_by, 0, True
