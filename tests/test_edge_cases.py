"""Edge cases for modern Python constructs and the closure/recursion heuristics.

These pin behaviour that the original 1.3.0 algorithm got wrong or skipped:
async loops, match/case, the decorator/closure heuristic, method recursion,
and comprehension filters.
"""

import ast
import textwrap

from conftest import get_code_snippet_complexity

from cognitive_complexity.api import get_cognitive_complexity


def _funcdef(src):
    return ast.parse(textwrap.dedent(src).strip()).body[0]


# --------------------------------------------------------------------------
# Loops: async for counts like for
# --------------------------------------------------------------------------


def test_async_for_counts_like_for():
    sync = get_code_snippet_complexity("""
    def f(xs):
        for x in xs:   # +1
            if x:      # +2 (nesting)
                return x
    """)
    asynchronous = get_code_snippet_complexity("""
    async def f(xs):
        async for x in xs:   # +1
            if x:            # +2 (nesting)
                return x
    """)
    assert asynchronous == sync == 3


# --------------------------------------------------------------------------
# match/case is a single branching structure (+ nesting), regardless of arms
# --------------------------------------------------------------------------


def test_match_statement_is_one_branch():
    # The match itself is +1; the number of cases does not matter.
    assert (
        get_code_snippet_complexity("""
    def f(x):
        match x:
            case 1:
                return 1
            case 2:
                return 2
            case _:
                return 3
    """)
        == 1
    )


def test_match_adds_a_nesting_level():
    # match +1, then the nested if gets +2 (its own +1, plus +1 nesting).
    assert (
        get_code_snippet_complexity("""
    def f(x):
        match x:        # +1
            case 1:
                if x:   # +2 (nesting)
                    return 1
            case _:
                return 0
    """)
        == 3
    )


# --------------------------------------------------------------------------
# with / async with add nothing
# --------------------------------------------------------------------------


def test_async_with_adds_nothing():
    assert (
        get_code_snippet_complexity("""
    async def f(cm):
        async with cm as c:
            if c:   # +1
                return c
    """)
        == 1
    )


# --------------------------------------------------------------------------
# Decorator / closure heuristic
# --------------------------------------------------------------------------


def test_decorator_factory_own_score_excludes_inner():
    # A decorator's body is [inner def, return inner]; the inner is its own unit,
    # so the decorator's own score is 0. (No more `is_decorator` special case —
    # this is just the general "named nested defs aren't folded" rule.)
    assert (
        get_code_snippet_complexity("""
    def a_decorator(a, b):
        def inner(func):
            if condition:  # belongs to inner
                print(b)
            func()
        return inner
    """)
        == 0
    )


def test_factory_returning_constant_also_excludes_inner():
    # Whether the outer returns the inner function or a constant no longer
    # matters: the named nested def is always its own unit, so `f`'s own score
    # is 0 either way.
    assert (
        get_code_snippet_complexity("""
    def f(a):
        def g(x):
            if x:        # belongs to g
                return 1
        return 42
    """)
        == 0
    )


def test_fold_mode_factory_scores_the_same_with_and_without_a_docstring():
    # In fold mode a factory is scored as the inner function it returns. Adding a
    # docstring is a doc-only edit and must not change the score.
    factory = """
    def deco(fn):
        def inner(*a):
            for x in a:      # +1
                if x:        # +2
                    x -= 1
            return fn
        return inner
    """
    documented = factory.replace("def deco(fn):", 'def deco(fn):\n        """Doc."""')
    assert get_cognitive_complexity(_funcdef(factory), fold_nested=True) == 3
    assert get_cognitive_complexity(_funcdef(documented), fold_nested=True) == 3


def test_closure_factory_own_score_excludes_inner():
    # A value-returning closure factory: `make_adder`'s own score is 0, and
    # `add` is scored separately on its own merits.
    assert (
        get_code_snippet_complexity("""
    def make_adder(n):
        def add(x):
            if x:        # belongs to add
                return x + n
            return n
        return add
    """)
        == 0
    )


# --------------------------------------------------------------------------
# Recursion
# --------------------------------------------------------------------------


def test_method_recursion_via_self_is_counted():
    assert (
        get_code_snippet_complexity("""
    def f(self, a):
        return self.f(a - 1)   # +1 recursion
    """)
        == 1
    )


def test_unrelated_method_call_is_not_recursion():
    assert (
        get_code_snippet_complexity("""
    def f(self, a):
        return other.f(a - 1)  # different receiver, not recursion
    """)
        == 0
    )


def test_outer_name_called_only_inside_nested_def_is_not_outer_recursion():
    # `f` is referenced only from inside `g`. Under Option A (nested defs are
    # independent units) that call belongs to g's unit, not f's — so f is NOT
    # recursive and scores 0. Previously the recursion check walked into g and
    # miscounted it as f's recursion (+1).
    assert (
        get_code_snippet_complexity("""
    def f(a):
        def g():
            return f()   # calls the OUTER name, from inside a nested def
        return g
    """)
        == 0
    )


def test_recursion_inside_a_bool_operand_is_found_in_both_nesting_modes():
    # A self-call hidden in a boolean operand is still recursion, and the two
    # nesting modes must agree on it — the same source always scores the same.
    fd = _funcdef("""
    def walk(node, depth):
        return depth > 0 and walk(node, depth - 1)   # bool-op +1, recursion +1
    """)
    assert get_cognitive_complexity(fd) == 2
    assert get_cognitive_complexity(fd, fold_nested=True) == 2


# --------------------------------------------------------------------------
# Boolean operands are walked: constructs inside them are scored
# --------------------------------------------------------------------------


def test_ternary_inside_a_bool_operand_is_scored():
    assert (
        get_code_snippet_complexity("""
    def f(a, b, c, d):
        return a and (b if c else d)   # bool-op +1, ternary +1
    """)
        == 2
    )


def test_comprehension_filters_inside_a_bool_operand_are_scored():
    assert (
        get_code_snippet_complexity("""
    def f(flag, xs):
        return flag and [x for x in xs if x > 0 if x < 9]   # bool-op +1, filters +2
    """)
        == 3
    )


def test_bool_op_inside_a_lambda_operand_scores_at_the_lambda_nesting():
    # The lambda adds a nesting level, so the `if` in its body costs +2 — it is
    # scored even though the lambda sits inside a boolean operand.
    assert (
        get_code_snippet_complexity("""
    def f(a, y, z):
        return a and (lambda w: 1 if w else 0)   # bool-op +1, ternary +2 (in lambda)
    """)
        == 3
    )


# --------------------------------------------------------------------------
# Comprehension filters are decision points
# --------------------------------------------------------------------------


def test_comprehension_filters_are_counted():
    assert (
        get_code_snippet_complexity("""
    def f(xs):
        return [x for x in xs if x > 0 if x < 10]   # +2 (two filters)
    """)
        == 2
    )


def test_comprehension_without_filter_is_zero():
    assert (
        get_code_snippet_complexity("""
    def f(xs):
        return [x for x in xs]
    """)
        == 0
    )


def test_dict_comp_single_filter_is_counted():
    # Dict comprehension: one `if` filter = +1 (same ast.comprehension node as list comp)
    assert (
        get_code_snippet_complexity("""
    def f(items):
        return {k: v for k, v in items if k}   # +1
    """)
        == 1
    )


def test_set_comp_single_filter_is_counted():
    # Set comprehension: one `if` filter = +1
    assert (
        get_code_snippet_complexity("""
    def f(xs):
        return {x for x in xs if x}   # +1
    """)
        == 1
    )


def test_genexp_single_filter_is_counted():
    # Generator expression: one `if` filter = +1
    assert (
        get_code_snippet_complexity("""
    def f(xs):
        return sum(x for x in xs if x)   # +1
    """)
        == 1
    )


def test_dict_comp_multiple_filters_are_all_counted():
    # Two `if` filters on one ast.comprehension node = +2
    assert (
        get_code_snippet_complexity("""
    def f(items):
        return {k: v for k, v in items if k if v}   # +2 (two filters)
    """)
        == 2
    )


def test_nested_comprehension_each_filter_counted_independently():
    # Two ast.comprehension nodes, each with one `if` filter = +1 + +1 = 2
    assert (
        get_code_snippet_complexity("""
    def f(xss):
        return [x for xs in xss if xs for x in xs if x]   # +2 (one filter per clause)
    """)
        == 2
    )


# --------------------------------------------------------------------------
# if/elif chains: each branch's body nests; the elif itself does not
# --------------------------------------------------------------------------


def test_structure_nested_in_a_branch_with_an_elif_still_nests():
    # The `if a` body is one level deep, so the nested `if b` scores +2, even
    # though `if a` is chained to an `elif`. Regression: this used to drop the
    # nesting level and score 3.
    assert (
        get_code_snippet_complexity("""
    def f(a, b, c):
        if a:           # +1
            if b:       # +2 (nested in the if-body)
                x = 1
        elif c:         # +1 (sibling, no nesting penalty)
            y = 1
    """)
        == 4
    )


def test_elif_does_not_add_a_nesting_penalty_inside_a_loop():
    # `if a` inside the loop is +2 (nesting 1); the chained `elif b` is +1 — an
    # elif gets a structural increment but no nesting penalty.
    assert (
        get_code_snippet_complexity("""
    def f(a, b):
        for x in a:     # +1
            if a:       # +2
                y = 1
            elif b:     # +1
                z = 1
    """)
        == 4
    )


# --------------------------------------------------------------------------
# Trivial guards
# --------------------------------------------------------------------------


def test_empty_function_is_zero():
    assert (
        get_code_snippet_complexity("""
    def f():
        pass
    """)
        == 0
    )
