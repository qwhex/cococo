import ast

import pytest

from cognitive_complexity.api import get_cognitive_complexity, get_cognitive_complexity_breakdown
from cognitive_complexity.cli import explain, main
from cognitive_complexity.utils.ast import describe_node

NESTED = """
def f(a, b):
    for x in a:        # +1
        if x:          # +2
            for y in b:  # +3
                if y:    # +4
                    return y
"""

KLASS = """
class Klass:
    def method(self, a):
        if a and a:    # if +1, bool-op +1
            return 1

def solo(n):
    return n
"""

ASYNC = """
async def stream(items):
    async for x in items:    # +1
        if x:                # +2
            await sink(x)
"""

# A structurally rich function exercising try/except, match, ternary,
# comprehension filter, bool-op, and a while loop in its own scope.
RICH = """
def rich(data, n):
    try:
        for item in data:                          # +1
            if item > 0:                           # +2
                result = item if item < n else -item   # ternary +3
    except (ValueError, KeyError):                 # except +1
        return [x for x in data if x]              # comprehension-if +1

    v = n
    while v and v > 0:                             # while +1, bool-op +1
        v -= 1

    match n:                                       # match +1
        case 0:
            return 0
        case _:
            return v
"""


def _funcdef(src):
    return ast.parse(src.strip()).body[0]


def _write(tmp_path, name, src):
    path = tmp_path / name
    path.write_text(src)
    return path


# ---- node labelling ------------------------------------------------------


def test_describe_node_labels_every_construct_kind():
    cases = {
        "if a:\n    pass": "if",
        "x = a if b else c": "ternary",
        "for x in xs:\n    pass": "for",
        "while a:\n    pass": "while",
        "match a:\n    case _:\n        pass": "match",
        "f = lambda x: x": "lambda",
        "x = a and b": "bool-op",
    }
    for src, expected in cases.items():
        node = ast.parse(src).body[0]
        # Unwrap statements that hold the construct in a child position.
        if expected in {"ternary", "lambda", "bool-op"}:
            node = node.value  # type: ignore[attr-defined]
        assert describe_node(node) == expected
    # Whether an `if` is an `elif` is positional (is it the `else`-branch of
    # another `if`?), so the caller supplies it. The leading branch is "if"; the
    # arm in its orelse is "elif".
    chain = ast.parse("if a:\n    pass\nelif b:\n    pass").body[0]
    assert describe_node(chain) == "if"
    assert describe_node(chain.orelse[0], is_elif_arm=True) == "elif"
    # async for is labelled the same as for; except handler; comprehension.
    afor = ast.parse("async def f():\n    async for x in xs:\n        pass").body[0].body[0]
    assert describe_node(afor) == "for"
    handler = ast.parse("try:\n    pass\nexcept E:\n    pass").body[0].handlers[0]
    assert describe_node(handler) == "except"
    comp = ast.parse("[x for x in xs if x]").body[0].value.generators[0]
    assert describe_node(comp) == "comprehension-if"
    # Fallback for any other node kind: its AST class name.
    assert describe_node(ast.parse("x = 1").body[0]) == "Assign"


def test_elif_chain_labels_match_source_order():
    # An if/elif/elif chain is labelled in source order: the leading branch is
    # "if" and every following branch is "elif". (These used to read backwards
    # — leading branches mislabelled "elif" and the tail "if".)
    fd = _funcdef("""
    def f(a):
        if a == 1:
            return 1
        elif a == 2:
            return 2
        elif a == 3:
            return 3
    """)
    breakdown = get_cognitive_complexity_breakdown(fd)
    # Only the leading `if` carries a nesting penalty (B3); `elif` arms do not.
    assert [(c.label, c.points, c.nesting_counted) for c in breakdown] == [
        ("if", 1, True),
        ("elif", 1, False),
        ("elif", 1, False),
    ]
    assert sum(c.points for c in breakdown) == get_cognitive_complexity(fd) == 3


# ---- breakdown API -------------------------------------------------------


def test_breakdown_sums_to_total():
    fd = _funcdef(NESTED)
    breakdown = get_cognitive_complexity_breakdown(fd)
    assert sum(c.points for c in breakdown) == get_cognitive_complexity(fd)


def test_breakdown_reports_nesting_and_labels():
    fd = _funcdef(NESTED)
    breakdown = get_cognitive_complexity_breakdown(fd)
    assert [(c.label, c.points, c.nesting) for c in breakdown] == [
        ("for", 1, 0),
        ("if", 2, 1),
        ("for", 3, 2),
        ("if", 4, 3),
    ]


def test_breakdown_bool_op_has_no_nesting_penalty():
    # bool-op points are purely structural even when ambiently nested
    fd = _funcdef("""
    def f(a):
        if a:               # +1
            return a and a  # bool-op +1, nesting not counted
    """)
    breakdown = get_cognitive_complexity_breakdown(fd)
    boolop = next(c for c in breakdown if c.label == "bool-op")
    assert boolop.points == 1
    assert boolop.nesting_counted is False


def test_breakdown_reports_a_compound_condition_as_one_bool_op():
    # Three sequences of like operators (`and`, `and`, `or`), all at the same
    # nesting level in one condition: one entry worth 3, not three of 1.
    fd = _funcdef("""
    def f(a, b, c, d):
        if (a and b) or (c and d):
            return 1
    """)
    breakdown = get_cognitive_complexity_breakdown(fd)
    assert [(c.lineno, c.label, c.points) for c in breakdown] == [
        (2, "if", 1),
        (2, "bool-op", 3),
    ]


def test_breakdown_scores_each_bool_op_node_at_its_own_nesting():
    # The `or` lives inside a lambda, one nesting level below the outer `and`.
    # Each ast.BoolOp is one entry worth 1 point, attributed where it sits.
    fd = _funcdef("""
    def f(a, y, z):
        return a and (lambda: y or z)
    """)
    breakdown = get_cognitive_complexity_breakdown(fd)
    assert [(c.label, c.points, c.nesting) for c in breakdown] == [
        ("bool-op", 1, 0),
        ("bool-op", 1, 1),
    ]


def test_breakdown_else_reports_the_else_keyword_line():
    fd = _funcdef("""
    def g(a):
        if a:
            x = 1
        else:
            x = 2
        return x
    """)
    [else_c] = [c for c in get_cognitive_complexity_breakdown(fd) if c.label == "else"]
    assert (else_c.lineno, else_c.points) == (4, 1)  # line 4 is `else:`, not line 5


def test_breakdown_gives_loop_else_its_own_contribution():
    # A `for ... else` used to report a single `for` worth 2 points, hiding the
    # else's +1 behind the loop's label and line.
    fd = _funcdef("""
    def loops(xs):
        for x in xs:
            pass
        else:
            pass
    """)
    breakdown = get_cognitive_complexity_breakdown(fd)
    assert [(c.lineno, c.label, c.points) for c in breakdown] == [
        (2, "for", 1),
        (4, "else", 1),
    ]
    assert sum(c.points for c in breakdown) == get_cognitive_complexity(fd) == 2


def test_breakdown_excludes_nested_defs_from_the_parent():
    # Named nested defs are not folded into the enclosing function's breakdown:
    # `a_decorator`'s own breakdown is empty (define inner, return inner), and
    # the `if condition` belongs to `inner`, scored as its own unit.
    fd = _funcdef("""
    def a_decorator(a, b):
        def inner(func):
            if condition:
                print(b)
            func()
        return inner
    """)
    breakdown = get_cognitive_complexity_breakdown(fd)
    assert breakdown == []
    assert sum(c.points for c in breakdown) == get_cognitive_complexity(fd) == 0


def test_breakdown_counts_recursion():
    fd = _funcdef("""
    def f(n):
        return f(n - 1)
    """)
    breakdown = get_cognitive_complexity_breakdown(fd)
    assert any(c.label == "recursion" and c.points == 1 for c in breakdown)


def test_breakdown_empty_for_flat_function():
    fd = _funcdef("""
    def g(a):
        return a
    """)
    assert get_cognitive_complexity_breakdown(fd) == []


# ---- async coverage ------------------------------------------------------


def test_breakdown_handles_async_def_and_async_for():
    # The real-world heavy hitters are all `async def`; prove the breakdown
    # scores `async for` (and the `async def` body) just like the sync forms.
    fd = _funcdef(ASYNC)
    assert isinstance(fd, ast.AsyncFunctionDef)
    breakdown = get_cognitive_complexity_breakdown(fd)
    assert [(c.label, c.points, c.nesting) for c in breakdown] == [
        ("for", 1, 0),  # `async for` is labelled the same as `for`
        ("if", 2, 1),
    ]
    assert sum(c.points for c in breakdown) == get_cognitive_complexity(fd)


def test_explain_async_function_through_cli(tmp_path, capsys):
    p = _write(tmp_path, "a.py", ASYNC)
    assert main(["--explain", f"{p}::stream"]) == 0
    out = capsys.readouterr().out
    assert "cognitive complexity = 3" in out
    assert "for" in out and "if" in out


# ---- structurally-rich invariant -----------------------------------------


def test_rich_function_breakdown_sums_to_total():
    # Strong invariant: across a mix of try/except, match, ternary,
    # comprehension, bool-op, and a nested def, the per-construct points must
    # still sum exactly to the scalar total.
    fd = _funcdef(RICH)
    breakdown = get_cognitive_complexity_breakdown(fd)
    assert sum(c.points for c in breakdown) == get_cognitive_complexity(fd)
    # Every documented construct kind shows up at least once.
    labels = {c.label for c in breakdown}
    assert {
        "for",
        "if",
        "ternary",
        "except",
        "comprehension-if",
        "while",
        "bool-op",
        "match",
    } <= labels


# ---- documented quirks (characterization) --------------------------------


def test_quirk_comprehension_filters_inherit_ancestor_lineno():
    # DOCUMENTED QUIRK (b): an `ast.comprehension` node carries no line of its
    # own, so its if-filter contribution inherits the nearest ancestor's line
    # number (here the `return` on line 2). Pins current behaviour; not a bug.
    fd = _funcdef("""
    def f(xs):
        return [x for x in xs if x > 0 if x < 10]
    """)
    breakdown = get_cognitive_complexity_breakdown(fd)
    [comp] = [c for c in breakdown if c.label == "comprehension-if"]
    assert comp.points == 2  # two if-filters, each a decision point
    assert comp.lineno == 2  # borrowed from the enclosing `return`
    assert comp.nesting_counted is False
    assert sum(c.points for c in breakdown) == get_cognitive_complexity(fd)


# ---- CLI explain: target forms ------------------------------------------


def test_explain_prints_total_and_breakdown(tmp_path, capsys):
    p = _write(tmp_path, "m.py", NESTED)
    assert explain(f"{p}::f") == 0
    out = capsys.readouterr().out
    assert "cognitive complexity = 10" in out
    assert "for" in out and "if" in out


def test_main_explain_flag(tmp_path, capsys):
    p = _write(tmp_path, "m.py", NESTED)
    assert main(["--explain", f"{p}::f"]) == 0
    assert "cognitive complexity = 10" in capsys.readouterr().out


def test_explain_by_line_number(tmp_path, capsys):
    # `FILE.py:LINE` form selects the function defined on that line.
    p = _write(tmp_path, "m.py", KLASS)
    assert main(["--explain", f"{p}:3"]) == 0  # `def method` is on line 3
    out = capsys.readouterr().out
    assert "Klass.method" in out
    assert "cognitive complexity = 2" in out  # if +1, bool-op +1


def test_explain_bare_single_function_file(tmp_path, capsys):
    # `FILE.py` with no selector works only when the file has exactly one func.
    p = _write(tmp_path, "one.py", "def only(n):\n    return n if n else 0\n")
    assert main(["--explain", str(p)]) == 0
    out = capsys.readouterr().out
    assert "only" in out
    assert "cognitive complexity = 1" in out  # one ternary


def test_explain_bare_multi_function_file_errors(tmp_path, capsys):
    # KLASS has two functions; the bare form must refuse and name them.
    p = _write(tmp_path, "m.py", KLASS)
    assert main(["--explain", str(p)]) == 2
    err = capsys.readouterr().err
    assert "Klass.method" in err and "solo" in err


def test_explain_flat_function_reports_no_constructs(tmp_path, capsys):
    p = _write(tmp_path, "flat.py", "def g(a):\n    return a\n")
    assert main(["--explain", str(p)]) == 0
    out = capsys.readouterr().out
    assert "cognitive complexity = 0" in out
    assert "flat function" in out


# ---- CLI explain: malformed input → clean stderr, exit 2 (setup failure) ---
# 1 stays reserved for "a function is over the ceiling", so a script driving
# cococo can tell a real violation from a target it could not resolve.


def test_explain_missing_function_exits_nonzero(tmp_path, capsys):
    p = _write(tmp_path, "m.py", KLASS)
    assert explain(f"{p}::missing") == 2
    err = capsys.readouterr().err
    assert "missing" in err
    assert err.startswith("cococo:")


def test_explain_file_not_found(capsys):
    assert main(["--explain", "/no/such/file.py::f"]) == 2
    err = capsys.readouterr().err
    assert err.startswith("cococo:")
    assert "Traceback" not in err


def test_explain_syntax_error_file(tmp_path, capsys):
    p = _write(tmp_path, "bad.py", "def f(:\n    pass\n")
    assert main(["--explain", f"{p}::f"]) == 2
    err = capsys.readouterr().err
    assert err.startswith("cococo:")
    assert "syntax" in err.lower()
    assert "Traceback" not in err


def test_explain_non_integer_line(tmp_path, capsys):
    # `FILE.py:notanumber` isn't a line selector; it falls through to a bare
    # path that doesn't exist — still a clean nonzero exit, not a traceback.
    p = _write(tmp_path, "ok.py", "def f():\n    return 1\n")
    assert main(["--explain", f"{p}:notanumber"]) == 2
    err = capsys.readouterr().err
    assert err.startswith("cococo:")
    assert "Traceback" not in err


def test_explain_empty_qualname(tmp_path, capsys):
    # `FILE.py::` parses to an empty qualname that matches nothing.
    p = _write(tmp_path, "ok.py", "def f():\n    return 1\n")
    assert main(["--explain", f"{p}::"]) == 2
    err = capsys.readouterr().err
    assert err.startswith("cococo:")
    assert "Traceback" not in err


def test_explain_file_without_functions_exits_nonzero(tmp_path, capsys):
    p = _write(tmp_path, "novars.py", "VALUE = 1\n")
    assert main(["--explain", str(p)]) == 2
    err = capsys.readouterr().err
    assert err.startswith("cococo:")
    assert "no functions found" in err


def test_explain_wrong_line_number_exits_nonzero(tmp_path, capsys):
    # `FILE.py:LINE` pointing at a line with no function definition.
    p = _write(tmp_path, "m.py", "def f():\n    return 1\n")
    assert main(["--explain", f"{p}:99"]) == 2
    err = capsys.readouterr().err
    assert err.startswith("cococo:")
    assert "line 99" in err


def test_main_requires_paths_without_explain(capsys):
    with pytest.raises(SystemExit):
        main([])
