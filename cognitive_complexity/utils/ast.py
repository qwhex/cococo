import ast
from collections.abc import Callable

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
    return any(
        _call_targets_name(node, funcdef.name)
        for node in ast.walk(funcdef)
        if isinstance(node, ast.Call)
    )


def _returns_name(stmt: ast.stmt, name: str) -> bool:
    return (
        isinstance(stmt, ast.Return)
        and isinstance(stmt.value, ast.Name)
        and stmt.value.id == name
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


def is_elif(node: ast.AST) -> bool:
    """True when an ``ast.If`` is the ``elif`` arm of an enclosing ``if``.

    Single source of truth shared by the label (:func:`describe_node`) and the
    scoring (:func:`process_control_flow_breaker`) so the two cannot drift.
    """
    return (
        isinstance(node, ast.If)
        and len(node.orelse) == 1
        and isinstance(node.orelse[0], ast.If)
    )


def describe_node(node: ast.AST) -> str:
    """Short human label for a scored construct, used in breakdowns."""
    if isinstance(node, ast.If):
        return 'elif' if is_elif(node) else 'if'
    if isinstance(node, ast.IfExp):
        return 'ternary'
    if isinstance(node, (ast.For, ast.AsyncFor)):
        return 'for'
    if isinstance(node, ast.While):
        return 'while'
    if isinstance(node, ast.ExceptHandler):
        return 'except'
    if isinstance(node, ast.Match):
        return 'match'
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
        return 'nested-func'
    if isinstance(node, ast.Lambda):
        return 'lambda'
    if isinstance(node, ast.BoolOp):
        return 'bool-op'
    if isinstance(node, ast.comprehension):
        return 'comprehension-if'
    return type(node).__name__


def process_child_nodes(
    node: ast.AST,
    increment_by: int,
    complexity_calculator: Callable[[ast.AST, int], int],
) -> int:
    child_complexity = 0
    child_nodes = ast.iter_child_nodes(node)
    for child_node in child_nodes:
        child_complexity += complexity_calculator(child_node, increment_by)
    return child_complexity


def process_control_flow_breaker(
    node: ast.If | ast.For | ast.AsyncFor | ast.While | ast.IfExp | ast.ExceptHandler | ast.Match,
    increment_by: int,
) -> tuple[int, int, bool]:
    if isinstance(node, ast.IfExp):
        # C if A else B; ternary operator equivalent
        increment = 0
        increment_by += 1
    elif is_elif(node):
        # node is an elif; the increment will be counted on the ast.If
        increment = 0
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
    control_flow_breakers = (
        ast.If,
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
