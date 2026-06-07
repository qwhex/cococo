import ast
import textwrap

import pytest

from cognitive_complexity.api import get_cognitive_complexity
from cognitive_complexity.autofix import fix_source


def _score(src: str) -> int:
    return get_cognitive_complexity(ast.parse(src.strip()).body[0])


def test_flattens_trailing_if_in_function_body():
    before = textwrap.dedent("""
        def f(x, items):
            setup()
            if x:
                for item in items:
                    if item.ok:
                        handle(item)
        """).strip()
    after, count = fix_source(before)
    assert count == 1
    assert "if not (x):" in after
    assert "    return\n" in after
    # The body moved up one level and the score dropped.
    assert _score(after) < _score(before)
    # Result is valid Python.
    ast.parse(after)


def test_flattens_trailing_if_in_loop_body_with_continue():
    before = textwrap.dedent("""
        def f(items):
            for item in items:
                if item.ok:
                    for sub in item.subs:
                        if sub:
                            emit(sub)
        """).strip()
    after, count = fix_source(before)
    assert count == 1
    assert "continue" in after
    ast.parse(after)


def test_unwraps_a_not_condition_instead_of_double_negating():
    before = textwrap.dedent("""
        def f(x, items):
            if not x:
                for i in items:
                    if i:
                        go(i)
        """).strip()
    after, _ = fix_source(before)
    assert "if x:" in after
    assert "not (not x)" not in after


def test_is_idempotent():
    before = textwrap.dedent("""
        def f(x, items):
            if x:
                for i in items:
                    if i:
                        go(i)
        """).strip()
    once, first = fix_source(before)
    twice, second = fix_source(once)
    assert first == 1
    assert second == 0
    assert once == twice


def test_does_not_touch_if_with_else():
    before = textwrap.dedent("""
        def f(x, items):
            if x:
                for i in items:
                    if i:
                        go(i)
            else:
                bail()
        """).strip()
    after, count = fix_source(before)
    assert count == 0
    assert after == before


def test_does_not_touch_if_that_is_not_last_statement():
    # Returning early here would skip cleanup(); must be left alone.
    before = textwrap.dedent("""
        def f(x, items):
            if x:
                for i in items:
                    if i:
                        go(i)
            cleanup()
        """).strip()
    after, count = fix_source(before)
    assert count == 0
    assert after == before


def test_does_not_touch_flat_if_with_no_nested_savings():
    before = textwrap.dedent("""
        def f(x):
            if x:
                do_one_thing()
        """).strip()
    after, count = fix_source(before)
    assert count == 0
    assert after == before


def test_does_not_touch_single_line_if():
    before = textwrap.dedent("""
        def f(x, items):
            if x: go()
        """).strip()
    after, count = fix_source(before)
    assert count == 0
    assert after == before


def test_does_not_touch_tab_indented_code():
    before = "def f(x, items):\n\tif x:\n\t\tfor i in items:\n\t\t\tif i:\n\t\t\t\tgo(i)\n"
    after, count = fix_source(before)
    assert count == 0
    assert after == before


def test_preserves_comments_in_the_flattened_body():
    before = textwrap.dedent("""
        def f(x, items):
            if x:
                # important note
                for i in items:
                    if i:
                        go(i)
        """).strip()
    after, _ = fix_source(before)
    assert "# important note" in after


def test_does_not_touch_multi_line_condition():
    before = textwrap.dedent("""
        def f(a, b, items):
            if (a and
                    b):
                for i in items:
                    if i:
                        go(i)
        """).strip()
    after, count = fix_source(before)
    assert count == 0
    assert after == before


def test_behavior_is_preserved_across_inputs():
    # The `if` is the last statement, so flattening to an early return is a
    # behavior-preserving transform. Observe the effect via the `out` argument.
    src = textwrap.dedent("""
        def collect(x, items, out):
            if x:
                for i in items:
                    if i % 2:
                        out.append(i)
        """).strip()
    fixed, count = fix_source(src)
    assert count == 1
    ns_before: dict[str, object] = {}
    ns_after: dict[str, object] = {}
    exec(src, ns_before)  # noqa: S102 - trusted test fixtures
    exec(fixed, ns_after)  # noqa: S102
    for x in (True, False):
        for items in ([1, 2, 3, 4], [], [2, 4]):
            before_out: list[int] = []
            after_out: list[int] = []
            ns_before["collect"](x, items, before_out)
            ns_after["collect"](x, items, after_out)
            assert before_out == after_out


def test_raises_on_unparseable_source():
    with pytest.raises(SyntaxError):
        fix_source("def f(:\n    pass")
