import ast

from cognitive_complexity.common_types import AnyFuncdef


def _call_targets_name(call: ast.Call, name: str) -> bool:
    func = call.func
    if isinstance(func, ast.Name):
        return func.id == name
    if isinstance(func, ast.Attribute) and func.attr == name:
        # method recursion: self.name(...) / cls.name(...)
        return isinstance(func.value, ast.Name) and func.value.id in ("self", "cls")
    return False


def has_recursive_calls(funcdef: AnyFuncdef) -> bool:
    # Direct recursion only: a call by the function's own name, or a
    # self/cls method call to it. Indirect/mutual recursion (a -> b -> a) is
    # not detected; that needs a whole-program call graph, out of scope for a
    # per-function AST metric.
    return any(
        _call_targets_name(node, funcdef.name)
        for node in ast.walk(funcdef)
        if isinstance(node, ast.Call)
    )


def _returns_name(stmt: ast.stmt, name: str) -> bool:
    return (
        isinstance(stmt, ast.Return) and isinstance(stmt.value, ast.Name) and stmt.value.id == name
    )


def is_decorator(funcdef: AnyFuncdef) -> bool:
    # Defines a single inner function and returns *that function by name*.
    # A decorator and a value-returning closure factory are structurally
    # identical, so both are scored by their inner function. Returning anything
    # other than the inner function (e.g. a constant) is not this pattern.
    return (
        isinstance(funcdef, (ast.FunctionDef, ast.AsyncFunctionDef))
        and len(funcdef.body) == 2
        and isinstance(funcdef.body[0], (ast.FunctionDef, ast.AsyncFunctionDef))
        and _returns_name(funcdef.body[1], funcdef.body[0].name)
    )


# Static node-type -> label dispatch. ``ast.If`` is handled separately because
# its label depends on whether it is an elif arm, which is positional.
_NODE_LABELS: tuple[tuple[type[ast.AST] | tuple[type[ast.AST], ...], str], ...] = (
    (ast.IfExp, "ternary"),
    ((ast.For, ast.AsyncFor), "for"),
    (ast.While, "while"),
    (ast.ExceptHandler, "except"),
    (ast.Match, "match"),
    ((ast.FunctionDef, ast.AsyncFunctionDef), "nested-func"),
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
    incrementers_nodes = (
        ast.FunctionDef,
        ast.AsyncFunctionDef,
        ast.Lambda,
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
