import ast

from cognitive_complexity.api import get_cognitive_complexity_breakdown
from cognitive_complexity.refactor import suggest_refactors


def _suggest(src: str):
    funcdef = ast.parse(src.strip()).body[0]
    breakdown = get_cognitive_complexity_breakdown(funcdef)
    return suggest_refactors(funcdef, breakdown)


def _kinds(suggestions) -> set[str]:
    return {s.kind for s in suggestions}


def test_flat_function_has_no_suggestions():
    assert (
        _suggest("""
    def f(a):
        return a + 1
    """)
        == []
    )


def test_nested_if_chain_suggests_guard_clause():
    src = """
    def f(a, items):
        if a:
            for x in items:
                if x.ok:
                    handle(x)
    """
    funcdef = ast.parse(src.strip()).body[0]
    total = sum(c.points for c in get_cognitive_complexity_breakdown(funcdef))
    guard = next(s for s in _suggest(src) if s.kind == "guard_clause")
    assert guard.autofixable is True
    assert guard.estimated_reduction >= 2
    # The after-estimate is exactly the function total minus the reduction.
    assert guard.estimated_complexity_after == total - guard.estimated_reduction


def test_guard_not_suggested_when_no_nested_savings():
    # A single `if` with a flat body saves nothing by flattening.
    assert "guard_clause" not in _kinds(
        _suggest("""
    def f(a):
        if a:
            do_one_thing()
    """)
    )


def test_big_block_suggests_extract_helper():
    suggestions = _suggest("""
    def f(a, b, items):
        result = 0
        for x in items:
            if x > 0:
                if x % 2:
                    result += x
                for y in range(x):
                    if y:
                        result -= y
        return result
    """)
    extract = next(s for s in suggestions if s.kind == "extract_helper")
    assert extract.autofixable is False
    assert extract.estimated_reduction >= 6


def test_long_elif_chain_suggests_dispatcher():
    suggestions = _suggest("""
    def f(cmd):
        if cmd == "a":
            return 1
        elif cmd == "b":
            return 2
        elif cmd == "c":
            return 3
        elif cmd == "d":
            return 4
    """)
    dispatch = next(s for s in suggestions if s.kind == "split_dispatcher")
    assert dispatch.estimated_reduction >= 3


def test_short_elif_chain_does_not_suggest_dispatcher():
    assert "split_dispatcher" not in _kinds(
        _suggest("""
    def f(cmd):
        if cmd == "a":
            return 1
        elif cmd == "b":
            return 2
    """)
    )


def test_match_with_many_cases_suggests_dispatcher():
    suggestions = _suggest("""
    def f(cmd):
        match cmd:
            case "a":
                return 1
            case "b":
                return 2
            case "c":
                return 3
            case "d":
                return 4
    """)
    assert "split_dispatcher" in _kinds(suggestions)


def test_small_match_does_not_suggest_dispatcher():
    assert "split_dispatcher" not in _kinds(
        _suggest("""
    def f(cmd):
        match cmd:
            case "a":
                return 1
            case _:
                return 0
    """)
    )


def test_complex_condition_suggests_extract_predicate():
    suggestions = _suggest("""
    def f(a, b, c, d):
        if (a and b) or (c and d):
            return 1
        return 0
    """)
    predicate = next(s for s in suggestions if s.kind == "extract_predicate")
    assert predicate.autofixable is False
    assert predicate.estimated_reduction >= 2


def test_suggestions_are_capped_and_sorted_by_reduction():
    # This function offers more than three distinct refactors (guard, extract,
    # dispatcher, predicate); the report keeps only the top three by reduction.
    suggestions = _suggest("""
    def f(cmd, a, b, c, d, items):
        if (a and b) or (c and d):
            for x in items:
                if x.ok:
                    for y in x.kids:
                        if y:
                            emit(y)
        if cmd == "a":
            return 1
        elif cmd == "b":
            return 2
        elif cmd == "c":
            return 3
        elif cmd == "d":
            return 4
    """)
    assert len(suggestions) == 3
    reductions = [s.estimated_reduction for s in suggestions]
    assert reductions == sorted(reductions, reverse=True)


def test_nested_functions_are_not_walked_as_regions():
    # The inner def's control flow is its own unit; the outer function's region
    # walk ignores it, so a trivial factory yields no region-based suggestions.
    suggestions = _suggest("""
    def outer(a):
        def inner(b):
            if b:
                for x in b:
                    if x:
                        return x
        return inner
    """)
    assert suggestions == []
