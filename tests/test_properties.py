"""Property-based tests for the cognitive-complexity algorithm.

The centerpiece is an exact oracle: for a function built only from nestable
control structures with no ``else`` and no boolean operators, every control
node contributes ``depth + 1`` (Sonar's nesting rule). We generate arbitrary
such trees and assert the library matches the closed-form total. The simpler
linear/triangular properties are kept as readable, targeted documentation.
"""

import hypothesis.strategies as st
from conftest import get_code_snippet_complexity
from hypothesis import given, settings

# A node is either the leaf "leaf" or a (kind, children) control block.
_KINDS = st.sampled_from(["if", "for", "while"])
_leaf = st.just("leaf")
_node = st.recursive(
    _leaf,
    lambda children: st.tuples(_KINDS, st.lists(children, min_size=1, max_size=3)),
    max_leaves=20,
)
_body = st.lists(_node, max_size=5)


def _render(nodes: list, indent: int) -> list[str]:
    pad = "    " * indent
    lines: list[str] = []
    for node in nodes:
        if node == "leaf":
            lines.append(f"{pad}x = 1")
            continue
        kind, children = node
        header = {"if": "if a:", "for": "for i in r:", "while": "while a:"}[kind]
        lines.append(f"{pad}{header}")
        lines.extend(_render(children, indent + 1))
    return lines or [f"{pad}pass"]


def _to_source(nodes: list) -> str:
    return "def f(a, r):\n" + "\n".join(_render(nodes, 1))


def _expected(nodes: list, depth: int = 0) -> int:
    """Closed-form complexity: each control node contributes depth + 1."""
    total = 0
    for node in nodes:
        if node == "leaf":
            continue
        _, children = node
        total += depth + 1
        total += _expected(children, depth + 1)
    return total


@given(_body)
@settings(max_examples=300)
def test_matches_closed_form_for_plain_nesting(nodes):
    assert get_code_snippet_complexity(_to_source(nodes)) == _expected(nodes)


@given(_body)
def test_complexity_is_non_negative(nodes):
    assert get_code_snippet_complexity(_to_source(nodes)) >= 0


@given(_body)
def test_scoring_is_deterministic(nodes):
    src = _to_source(nodes)
    assert get_code_snippet_complexity(src) == get_code_snippet_complexity(src)


@given(st.integers(min_value=0, max_value=20))
def test_flat_ifs_sum_linearly(n):
    lines = ["def f(a):"]
    for _ in range(n):
        lines.append("    if a:")
        lines.append("        x = 1")
    lines.append("    return 0")
    assert get_code_snippet_complexity("\n".join(lines)) == n


@given(st.integers(min_value=1, max_value=20))
def test_nested_ifs_are_triangular(n):
    # Nesting penalty: depth d contributes d+1, so total is 1+2+...+n.
    lines = ["def f(a):"]
    lines.extend("    " * (depth + 1) + "if a:" for depth in range(n))
    lines.append("    " * (n + 1) + "x = 1")
    assert get_code_snippet_complexity("\n".join(lines)) == n * (n + 1) // 2
