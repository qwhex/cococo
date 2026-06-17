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


# ── Exact estimate-value tests ────────────────────────────────────────────────

_FOUR_ARM_ELIF = """
def f(cmd):
    if cmd == "a":
        return 1
    elif cmd == "b":
        return 2
    elif cmd == "c":
        return 3
    elif cmd == "d":
        return 4
    elif cmd == "e":
        return 5
"""

_FOUR_CASE_MATCH = """
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
"""


def test_elif_dispatch_reduction_equals_arm_count():
    # _FOUR_ARM_ELIF has 4 elif arms; _dispatch_reduction returns arms (4).
    # The formula is: reduction == number of elif arms, not number of branches.
    [dispatch] = [s for s in _suggest(_FOUR_ARM_ELIF) if s.kind == "split_dispatcher"]
    assert dispatch.estimated_reduction == 4  # 4 elif arms, not 3 or 5


def test_match_dispatch_reduction_is_cases_minus_one():
    # _FOUR_CASE_MATCH has 4 cases; _dispatch_reduction returns cases - 1 = 3.
    [dispatch] = [s for s in _suggest(_FOUR_CASE_MATCH) if s.kind == "split_dispatcher"]
    assert dispatch.estimated_reduction == 3  # 4 cases - 1, not 4 or 2


def test_estimated_complexity_after_clamped_at_zero():
    # _FOUR_CASE_MATCH total complexity == 1 (one match contribution).
    # dispatch reduction == 3, which exceeds total, so max(0, 1-3) must be 0.
    [dispatch] = [s for s in _suggest(_FOUR_CASE_MATCH) if s.kind == "split_dispatcher"]
    assert dispatch.estimated_complexity_after == 0  # clamp: never negative


def test_complex_structural_match_does_not_suggest_dispatcher():
    # A match statement with 4 or more cases should not trigger split_dispatcher
    # if it relies on structural pattern matching (e.g. mapping patterns),
    # because they cannot be cleanly replaced by a dictionary dispatch table.
    suggestions = _suggest("""
    def process(event):
        match event:
            case {"type": "user", "id": int(uid)}:
                return uid
            case {"type": "post", "title": str(title)}:
                return title
            case {"type": "comment", "text": str(text)}:
                return text
            case {"type": "like", "user_id": int(uid)}:
                return uid
            case _:
                return 0
    """)
    assert "split_dispatcher" not in _kinds(suggestions)


def test_highly_coupled_block_does_not_suggest_extract_helper():
    # If extracting a block would require passing and returning too many variables
    # (Data Clump / Long Parameter List anti-patterns), the suggestion is suppressed.
    suggestions = _suggest("""
    def process(a, b, c, items):
        d = 0
        e = 0
        # Highly coupled region: mutates/reads 5 outer variables.
        for x in items:
            if x:
                a += 1
                b -= 1
                c *= 2
                d = a + b
                e = c + d
                if a > 10:
                    d += 1
        return a, b, c, d, e
    """)
    assert "extract_helper" not in _kinds(suggestions)
