import ast

from cognitive_complexity.api import get_cognitive_complexity_breakdown
from cognitive_complexity.detectors import suggest_refactors


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


def test_mid_block_guard_is_advised_without_the_autofix_promise():
    # `if a:` is followed by `return total`, so inverting it into an early return
    # is not behaviour-preserving and `--fix` refuses it. The advice still stands;
    # the `[--fix]` badge must not.
    src = """
    def f(a, items):
        total = 0
        if a:
            for x in items:
                if x:
                    total += x
        return total
    """
    guard = next(s for s in _suggest(src) if s.kind == "guard_clause")
    assert guard.estimated_reduction >= 2
    assert guard.autofixable is False


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


def test_sequential_if_chain_suggests_dispatcher():
    suggestions = _suggest("""
    def f(x):
        if x == "a":
            return 1
        if x == "b":
            return 2
        if x == "c":
            return 3
        return 0
    """)
    dispatch = next(s for s in suggestions if s.kind == "split_dispatcher")
    # The run's breakdown points: three top-level ifs at 1 point each, all
    # removed by the table lookup.
    assert dispatch.estimated_reduction == 3


def test_short_sequential_if_chain_does_not_suggest_dispatcher():
    assert "split_dispatcher" not in _kinds(
        _suggest("""
    def f(x):
        if x == "a":
            return 1
        if x == "b":
            return 2
        return 0
    """)
    )


def test_sequential_dispatch_skips_colliding_keys():
    # 1, True, 1.0 collapse to one dict key — a table would silently merge arms.
    assert "split_dispatcher" not in _kinds(
        _suggest("""
    def f(x):
        if x == 1:
            return "a"
        if x == True:
            return "b"
        if x == 1.0:
            return "c"
        return "z"
    """)
    )


def test_sequential_dispatch_skips_non_terminal_arm():
    # An arm that assigns and falls through is not terminal — moving it to a dict
    # would drop the later log() side effect.
    assert "split_dispatcher" not in _kinds(
        _suggest("""
    def f(x):
        if x == "a":
            y = 1
        if x == "b":
            y = 2
        if x == "c":
            y = 3
        return y
    """)
    )


def test_sequential_dispatch_skips_side_effecting_subject():
    # decode(x) is a Call — collapsing would change the number of calls.
    assert "split_dispatcher" not in _kinds(
        _suggest("""
    def f(x):
        if decode(x) == "a":
            return 1
        if decode(x) == "b":
            return 2
        if decode(x) == "c":
            return 3
        return 0
    """)
    )


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
    # A nested match costs 1 + its nesting level, so it clears the noise floor;
    # the estimate is exactly what the breakdown charges for the match.
    src = """
    def f(cmds):
        for cmd in cmds:
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
    funcdef = ast.parse(src.strip()).body[0]
    breakdown = get_cognitive_complexity_breakdown(funcdef)
    total = sum(c.points for c in breakdown)
    [dispatch] = [s for s in suggest_refactors(funcdef, breakdown) if s.kind == "split_dispatcher"]
    match_points = sum(
        c.points for c in breakdown if dispatch.line_start <= c.lineno <= dispatch.line_end
    )
    assert dispatch.estimated_reduction == match_points
    assert dispatch.estimated_complexity_after == total - dispatch.estimated_reduction


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
    # Four separate hotspots (three nested blocks and a dispatch ladder) offer
    # more than three refactors; the report keeps only the top three by reduction.
    suggestions = _suggest("""
    def f(cmd, items, others, rest):
        if items:
            for x in items:
                if x.ok:
                    for y in x.kids:
                        emit(y)
        if cmd == "a":
            log(1)
        elif cmd == "b":
            log(2)
        elif cmd == "c":
            log(3)
        elif cmd == "d":
            log(4)
        for z in others:
            if z.ok:
                for w in z.kids:
                    if w:
                        emit(w)
        while rest:
            if rest.ok:
                for q in rest.kids:
                    if q:
                        emit(q)
    """)
    assert len(suggestions) == 3
    reductions = [s.estimated_reduction for s in suggestions]
    assert reductions == sorted(reductions, reverse=True)


def test_scattered_guards_fall_back_to_decompose_by_span():
    # No region is extractable and no dispatch/predicate pattern matches, but the
    # function is complex — the fallback points at the heaviest span.
    suggestions = _suggest("""
    def handle(req):
        log(req)
        if req.token is None:
            raise Unauthorized()
        if req.user is None:
            raise NotFound()
        if req.banned:
            raise Forbidden()
        if not req.payload:
            raise BadRequest()
        if req.expired:
            raise Expired()
        return commit(req)
    """)
    assert _kinds(suggestions) == {"decompose_by_span"}


def test_fallback_silent_when_a_named_refactor_fires():
    # When extract_helper (or any named detector) fires, the fallback must not.
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
    assert "decompose_by_span" not in _kinds(suggestions)


def test_fallback_silent_on_simple_function():
    # A small function with no pattern and little complexity gets no fallback.
    assert (
        _suggest("""
    def f(a):
        if a:
            return 1
        return 0
    """)
        == []
    )


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


def test_elif_dispatch_reduction_is_the_ladder_points():
    # The ladder's payoff is what it actually costs per the breakdown (the `if`
    # plus one point per `elif` arm), never a raw count of AST arms.
    funcdef = ast.parse(_FOUR_ARM_ELIF.strip()).body[0]
    breakdown = get_cognitive_complexity_breakdown(funcdef)
    total = sum(c.points for c in breakdown)
    [dispatch] = [s for s in suggest_refactors(funcdef, breakdown) if s.kind == "split_dispatcher"]
    ladder_points = sum(
        c.points for c in breakdown if dispatch.line_start <= c.lineno <= dispatch.line_end
    )
    assert dispatch.estimated_reduction == ladder_points
    assert dispatch.estimated_complexity_after == total - dispatch.estimated_reduction


def test_flat_match_dispatch_is_below_the_noise_floor():
    # The scorer charges a `match` +1 in total however many cases it has, so a
    # flat 4-case match cannot be worth MIN_REDUCTION points — nothing is offered.
    assert "split_dispatcher" not in _kinds(_suggest(_FOUR_CASE_MATCH))


def test_overlapping_suggestions_share_one_reduction_budget():
    # Every estimate is computed against the untouched total, so suggestions that
    # cover the same lines cannot all be applied — their claims used to sum past
    # the function's own complexity.
    src = """
    def f(a, b, items):
        if a:
            if b:
                for i in items:
                    if i > 0:
                        for j in i:
                            if j:
                                print(j)
    """
    funcdef = ast.parse(src.strip()).body[0]
    breakdown = get_cognitive_complexity_breakdown(funcdef)
    total = sum(c.points for c in breakdown)
    suggestions = suggest_refactors(funcdef, breakdown)
    assert sum(s.estimated_reduction for s in suggestions) <= total


def test_guard_and_merge_on_the_same_shell_are_not_both_offered():
    # Inverting `if a:` into an early return and merging it into `if a and b:` are
    # mutually exclusive rewrites of one `if a: if b:` shell; only the bigger win
    # is reported.
    kinds = _kinds(
        _suggest("""
    def f(a, b, items):
        for x in items:
            for y in x:
                if a:
                    if b:
                        for z in y:
                            if z:
                                print(z)
    """)
    )
    assert not {"guard_clause", "merge_nested_if"} <= kinds


def test_recursive_function_is_not_told_to_extract_its_whole_body():
    # The recursion point is charged to the `def` line, outside every body span —
    # the fallback must still not propose extracting the entire body (a rename).
    src = """
    def walk(n, acc):
        if n <= 0:
            return acc
        for c in n.kids:
            if c.ok:
                acc += 1
        while acc > 100:
            acc -= walk(n.parent, acc)
        return acc if acc else walk(n.next, 0)
    """
    funcdef = ast.parse(src.strip()).body[0]
    body = funcdef.body
    whole_body = (body[0].lineno, body[-1].end_lineno)
    suggestions = suggest_refactors(funcdef, get_cognitive_complexity_breakdown(funcdef))
    assert all((s.line_start, s.line_end) != whole_body for s in suggestions)


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


def test_attribute_heavy_region_counts_distinct_attributes():
    # A region that reassigns many distinct attributes is treated like a data
    # clump (high mutation surface), so plain helper extraction is suppressed
    # even though the block is big enough to otherwise qualify. This exercises
    # plain, attribute-target, and tuple-target assignment handling.
    suggestions = _suggest("""
    def f(obj, items):
        if obj.flag:
            note()
        for x in items:
            if x > 0:
                obj.a = x
                obj.b, obj.c = x, x
                if x > 5:
                    obj.d = x
                    if x > 10:
                        obj.e = x + 1
        return obj
    """)
    assert "extract_helper" not in _kinds(suggestions)


def test_equality_chain_with_mixed_subjects_is_not_a_dispatcher():
    # The arms compare different subjects (a vs b), so the chain is not a clean
    # single-subject dispatch and no split_dispatcher is offered.
    assert "split_dispatcher" not in _kinds(
        _suggest("""
    def f(a, b):
        if a == 1:
            return 1
        elif b == 2:
            return 2
        elif a == 3:
            return 3
        elif a == 4:
            return 4
    """)
    )


def test_dispatcher_recognizes_constant_on_left():
    # `"a" == cmd` is the same equality as `cmd == "a"`; the chain still reads as
    # a single-subject dispatch on `cmd`.
    assert "split_dispatcher" in _kinds(
        _suggest("""
    def f(cmd):
        if "a" == cmd:
            return 1
        elif "b" == cmd:
            return 2
        elif "c" == cmd:
            return 3
        elif "d" == cmd:
            return 4
    """)
    )


def test_chain_comparing_two_names_is_not_a_dispatcher():
    # `x == y` has no constant key on either side, so it is not a dispatchable arm.
    assert "split_dispatcher" not in _kinds(
        _suggest("""
    def f(x, y):
        if x == 1:
            return 1
        elif x == y:
            return 2
        elif x == 3:
            return 3
        elif x == 4:
            return 4
    """)
    )


def test_match_with_guard_is_not_a_dispatcher():
    # A guard makes a case structural (not a plain value lookup), so the match is
    # not offered for dispatch-table refactoring.
    assert "split_dispatcher" not in _kinds(
        _suggest("""
    def f(cmd):
        match cmd:
            case "a" if cmd:
                return 1
            case "b":
                return 2
            case "c":
                return 3
            case "d":
                return 4
    """)
    )


# ── merge_nested_if tests ─────────────────────────────────────────────────────


def test_merge_nested_if_suggested_for_double_if():
    suggestions = _suggest("""
    def f(a, b, c):
        for x in c:
            if a:
                if b:
                    do(x)
    """)
    merge = next((s for s in suggestions if s.kind == "merge_nested_if"), None)
    assert merge is not None
    assert merge.autofixable is False
    assert merge.estimated_reduction >= 1


def test_merge_nested_if_not_suggested_when_outer_has_else():
    assert "merge_nested_if" not in _kinds(
        _suggest("""
    def f(a, b):
        if a:
            if b:
                return "both"
        else:
            return "no a"
    """)
    )


def test_merge_nested_if_not_suggested_when_inner_has_else():
    assert "merge_nested_if" not in _kinds(
        _suggest("""
    def f(a, b, c):
        for x in c:
            if a:
                if b:
                    return "both"
                else:
                    return "a only"
    """)
    )


def test_match_with_or_patterns_is_still_a_dispatcher():
    # `case "a" | "b"` is a simple OR of value patterns, so the match still reads
    # as a value dispatch and the suggestion stands (nested, to clear the floor).
    assert "split_dispatcher" in _kinds(
        _suggest("""
    def f(cmds):
        for cmd in cmds:
            match cmd:
                case "a" | "b":
                    return 1
                case "c":
                    return 2
                case "d":
                    return 3
                case "e":
                    return 4
    """)
    )


# ── flatten_else_after_return tests ───────────────────────────────────────────


def test_flatten_else_suggested_when_if_body_terminates_and_else_is_nested():
    # An if that always returns, followed by an else with nested constructs:
    # the detector fires because the else is redundant and removing it de-nests.
    suggestions = _suggest("""
    def process(items, flag):
        if flag:
            return None
        else:
            for item in items:
                if item.active:
                    handle(item)
            return len(items)
    """)
    match = next((s for s in suggestions if s.kind == "flatten_else_after_return"), None)
    assert match is not None
    assert match.autofixable is False
    assert match.estimated_reduction >= 2


def test_flatten_else_not_suggested_for_elif():
    # When the orelse is a single If node (an elif chain), the detector must
    # stay silent — an elif is structural, not a redundant else.
    assert "flatten_else_after_return" not in _kinds(
        _suggest("""
    def f(n):
        if n > 0:
            return 1
        elif n == 0:
            return 0
        else:
            for x in range(10):
                if x:
                    do(x)
            return -1
    """)
    )


def test_flatten_else_not_suggested_when_if_body_does_not_always_terminate():
    # The outer if body falls through when strict is False — the else is NOT
    # redundant.  Dropping it would silently change behaviour.
    assert "flatten_else_after_return" not in _kinds(
        _suggest("""
    def check(n, strict):
        if n < 0:
            if strict:
                return -1
        else:
            for x in range(10):
                if x > 5:
                    process(x)
            return 1
    """)
    )


def test_flatten_else_suggested_when_if_body_ends_in_exhaustive_inner_if():
    # The if body ends with an inner if/else where both branches return —
    # every path terminates, so the outer else is still redundant.
    suggestions = _suggest("""
    def f(n, items):
        if n > 0:
            if n > 10:
                return "big"
            else:
                return "small"
        else:
            for item in items:
                if item:
                    handle(item)
            return "nonpositive"
    """)
    match = next((s for s in suggestions if s.kind == "flatten_else_after_return"), None)
    assert match is not None
    assert match.estimated_reduction >= 2
