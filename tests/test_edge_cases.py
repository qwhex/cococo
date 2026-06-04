"""Edge cases for modern Python constructs and the closure/recursion heuristics.

These pin behaviour that the original 1.3.0 algorithm got wrong or skipped:
async loops, match/case, the decorator/closure heuristic, method recursion,
and comprehension filters.
"""

from conftest import get_code_snippet_complexity

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


def test_decorator_is_scored_by_inner_function():
    # body is [inner def, return inner]; scored by inner at nesting 0.
    assert (
        get_code_snippet_complexity("""
    def a_decorator(a, b):
        def inner(func):
            if condition:  # +1
                print(b)
            func()
        return inner
    """)
        == 1
    )


def test_inner_def_returning_constant_is_not_a_decorator():
    # Returns a constant, not the inner function, so the inner def is a real
    # nested function: def (+1 nesting) then `if x` at nesting 1 (+2) -> 2.
    assert (
        get_code_snippet_complexity("""
    def f(a):
        def g(x):
            if x:        # +2 (nested function body)
                return 1
        return 42
    """)
        == 2
    )


def test_closure_factory_is_indistinguishable_from_decorator():
    # A value-returning closure factory is structurally identical to a
    # decorator (returns its inner function by name), so it is scored the
    # same way -- by the inner function. Documented limitation.
    assert (
        get_code_snippet_complexity("""
    def make_adder(n):
        def add(x):
            if x:        # +1
                return x + n
            return n
        return add
    """)
        == 1
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
