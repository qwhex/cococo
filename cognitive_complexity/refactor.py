"""Heuristic refactor suggestions derived from the complexity breakdown.

Clean-room: the region model, thresholds, and reduction estimates here are our
own. Each suggestion reads the same per-construct :class:`Contribution` data the
scorer emits, so its estimated drop stays consistent with the reported score,
and names one concrete, mechanical refactor. Designed to be actionable for a
human or an agent reading a failing ``--max`` gate.
"""

from __future__ import annotations

import ast
from typing import NamedTuple

from cognitive_complexity.api import Contribution
from cognitive_complexity.common_types import AnyFuncdef, is_funcdef

# Heuristic thresholds (ours, not part of Campbell's metric). Tuned to surface
# only refactors that meaningfully cut the score; adjust here, in one place.
_MIN_REDUCTION = 2  # ignore suggestions that barely move the score
_MAX_SUGGESTIONS = 3  # keep the report focused on the biggest wins
_EXTRACT_MIN_POINTS = 6  # a block heavy enough to pull into its own helper
_EXTRACT_MIN_LINES = 5
_MAX_COUPLING = 4  # max number of variables crossing the boundary before extraction is harmful
_DISPATCH_MIN_ARMS = 3  # elif arms before "split into a dispatch table"
_DISPATCH_MIN_CASES = 4  # match cases, ditto
_PREDICATE_MIN_POINTS = 2  # a boolean expression worth naming

_REGION_TYPES = (
    ast.If,
    ast.For,
    ast.AsyncFor,
    ast.While,
    ast.Try,
    ast.With,
    ast.AsyncWith,
    ast.Match,
)

_STEPS: dict[str, tuple[str, ...]] = {
    "guard_clause": (
        "Invert the condition and return/continue early when it fails.",
        "De-indent the main path one level.",
        "Repeat for any further nested guards.",
    ),
    "extract_helper": (
        "Move this block into a small named helper.",
        "Pass the values it reads as parameters.",
        "Return what the caller needs.",
    ),
    "split_dispatcher": (
        "Map each case to a named handler function.",
        "Replace the chain with a dispatch dict (or a thin delegating match).",
        "Keep this function a shallow orchestrator.",
    ),
    "extract_predicate": (
        "Move this boolean expression into a well-named predicate function.",
        "Call the predicate in the condition.",
        "Keep the control flow here focused on branching.",
    ),
}

_TITLES: dict[str, str] = {
    "guard_clause": "Flatten nested block with a guard clause",
    "extract_helper": "Extract this block into a helper function",
    "split_dispatcher": "Replace the branch ladder with a dispatch table",
    "extract_predicate": "Name this complex condition as a predicate",
}


class Suggestion(NamedTuple):
    """One concrete, mechanical refactor for a too-complex function.

    ``estimated_reduction`` is how many points the score should drop if applied;
    ``estimated_complexity_after`` is the function total minus that. ``kind`` is a
    stable machine id (see :data:`_TITLES`); ``autofixable`` flags the kinds the
    ``--fix`` rewriter can apply on its own.
    """

    kind: str
    title: str
    line_start: int
    line_end: int
    estimated_reduction: int
    estimated_complexity_after: int
    autofixable: bool
    steps: tuple[str, ...]


def suggest_refactors(funcdef: AnyFuncdef, breakdown: list[Contribution]) -> list[Suggestion]:
    """Up to a few high-value refactors for ``funcdef``, biggest reduction first."""
    total = sum(c.points for c in breakdown)
    candidates: list[Suggestion] = []
    candidates += _guard_suggestions(funcdef, breakdown, total)
    candidates += _predicate_suggestions(funcdef, breakdown, total)
    for region in _iter_regions(funcdef):
        candidates += _region_suggestions(funcdef, region, breakdown, total)
    return _select(candidates)


def _make(kind: str, start: int, end: int, reduction: int, total: int) -> Suggestion:
    return Suggestion(
        kind=kind,
        title=_TITLES[kind],
        line_start=start,
        line_end=end,
        estimated_reduction=reduction,
        estimated_complexity_after=max(0, total - reduction),
        autofixable=kind == "guard_clause",
        steps=_STEPS[kind],
    )


def _iter_regions(node: ast.AST) -> list[ast.stmt]:
    """Control-flow regions in the function, not descending into nested defs.

    Nested ``def``/``async def`` are independent units, so their inner control
    flow is left out of this function's region list.
    """
    regions: list[ast.stmt] = []
    for child in ast.iter_child_nodes(node):
        if is_funcdef(child):
            continue
        if isinstance(child, _REGION_TYPES):
            regions.append(child)
        regions.extend(_iter_regions(child))
    return regions


def _subtree_points(breakdown: list[Contribution], start: int, end: int) -> int:
    return sum(c.points for c in breakdown if start <= c.lineno <= end)


def _guard_suggestions(
    funcdef: AnyFuncdef, breakdown: list[Contribution], total: int
) -> list[Suggestion]:
    out: list[Suggestion] = []
    for node in _iter_regions(funcdef):
        if not isinstance(node, ast.If) or node.orelse or not node.body:
            continue
        body_start = node.body[0].lineno
        end = node.end_lineno or body_start
        saved = sum(
            1
            for c in breakdown
            if body_start <= c.lineno <= end and c.nesting_counted and c.lineno != node.lineno
        )
        if saved:
            out.append(_make("guard_clause", node.lineno, end, saved, total))
    return out


def _region_suggestions(
    funcdef: AnyFuncdef, region: ast.stmt, breakdown: list[Contribution], total: int
) -> list[Suggestion]:
    start = region.lineno
    end = region.end_lineno or start
    out: list[Suggestion] = []
    points = _subtree_points(breakdown, start, end)
    # ``points < total`` keeps us from advising "extract the whole function" when
    # one region spans the entire body; that region carries every point.
    big_enough = points >= _EXTRACT_MIN_POINTS and (end - start + 1) >= _EXTRACT_MIN_LINES
    if (
        big_enough
        and points < total
        and _is_extractable_region(region)
        and _analyze_coupling(funcdef, region) <= _MAX_COUPLING
    ):
        out.append(_make("extract_helper", start, end, points, total))
    dispatch = _dispatch_reduction(region)
    if dispatch:
        out.append(_make("split_dispatcher", start, end, dispatch, total))
    return out


def _is_extractable_region(region: ast.stmt) -> bool:
    """Whether a region is a reasonable candidate for a plain helper extraction."""
    if any(
        isinstance(node, (ast.Break, ast.Continue, ast.Return, ast.Yield, ast.YieldFrom))
        for node in ast.walk(region)
    ):
        return False
    return _attribute_mutation_count(region) <= _MAX_COUPLING


def _attribute_mutation_count(region: ast.stmt) -> int:
    attrs: set[str] = set()
    for node in ast.walk(region):
        for target in _mutation_targets(node):
            attrs.update(_stored_attribute_keys(target))
    return len(attrs)


def _mutation_targets(node: ast.AST) -> list[ast.AST]:
    if isinstance(node, ast.Assign):
        return list(node.targets)
    if isinstance(node, ast.AnnAssign | ast.AugAssign | ast.NamedExpr):
        return [node.target]
    return []


def _stored_attribute_keys(node: ast.AST) -> set[str]:
    if isinstance(node, ast.Attribute):
        return {ast.unparse(node)}
    if isinstance(node, ast.Tuple | ast.List):
        return {key for item in node.elts for key in _stored_attribute_keys(item)}
    return set()


def _analyze_coupling(funcdef: AnyFuncdef, region: ast.stmt) -> int:
    defined_before = {node.arg for node in ast.walk(funcdef.args) if isinstance(node, ast.arg)}
    used_after: set[str] = set()
    region_loads: set[str] = set()
    region_stores: set[str] = set()
    buckets = {
        "defined_before": defined_before,
        "used_after": used_after,
        "region_loads": region_loads,
        "region_stores": region_stores,
    }

    start = region.lineno
    end = region.end_lineno or start

    for node in ast.walk(funcdef):
        role = _name_coupling_role(node, start, end)
        if role is not None:
            bucket, name = role
            buckets[bucket].add(name)
        aug = _augmented_load_role(node, start, end)
        if aug is not None:
            buckets[aug[0]].add(aug[1])

    inputs = region_loads & defined_before
    outputs = region_stores & used_after
    return len(inputs) + len(outputs)


def _name_coupling_role(node: ast.AST, start: int, end: int) -> tuple[str, str] | None:
    if not isinstance(node, ast.Name):
        return None
    lineno = node.lineno
    if lineno < start and isinstance(node.ctx, ast.Store):
        return "defined_before", node.id
    if lineno > end and isinstance(node.ctx, ast.Load):
        return "used_after", node.id
    if start <= lineno <= end and isinstance(node.ctx, ast.Load):
        return "region_loads", node.id
    if start <= lineno <= end and isinstance(node.ctx, ast.Store):
        return "region_stores", node.id
    return None


def _augmented_load_role(node: ast.AST, start: int, end: int) -> tuple[str, str] | None:
    """An augmented assignment (``x += 1``) also READS its target.

    Python gives an ``AugAssign`` target ``Store`` context, so the implicit load is
    invisible to :func:`_name_coupling_role`. Without this, an in-region accumulator
    counts as an output only, under-counting coupling and letting unsafe
    extractions through.
    """
    if not (isinstance(node, ast.AugAssign) and isinstance(node.target, ast.Name)):
        return None
    lineno = node.target.lineno
    if start <= lineno <= end:
        return "region_loads", node.target.id
    if lineno > end:
        return "used_after", node.target.id
    return None


def _dispatch_reduction(region: ast.stmt) -> int:
    if isinstance(region, ast.If):
        arms = _elif_arms(region) if _is_simple_equality_chain(region) else 0
        return arms if arms >= _DISPATCH_MIN_ARMS else 0
    if isinstance(region, ast.Match):
        if _has_structural_patterns(region):
            return 0
        cases = len(region.cases)
        return cases - 1 if cases >= _DISPATCH_MIN_CASES else 0
    return 0


def _is_simple_equality_chain(node: ast.If) -> bool:
    tests = _if_chain_tests(node)
    subject: str | None = None
    for test in tests:
        parsed = _simple_equality_test(test)
        if parsed is None:
            return False
        current_subject, _key = parsed
        if subject is None:
            subject = current_subject
        elif current_subject != subject:
            return False
    return subject is not None


def _if_chain_tests(node: ast.If) -> list[ast.expr]:
    tests = [node.test]
    current = node
    while len(current.orelse) == 1 and isinstance(current.orelse[0], ast.If):
        current = current.orelse[0]
        tests.append(current.test)
    return tests


def _simple_equality_test(test: ast.expr) -> tuple[str, object] | None:
    if not (
        isinstance(test, ast.Compare)
        and len(test.ops) == 1
        and isinstance(test.ops[0], ast.Eq)
        and len(test.comparators) == 1
    ):
        return None
    left = _dispatch_subject(test.left)
    right = _dispatch_subject(test.comparators[0])
    left_key = _dispatch_key(test.left)
    right_key = _dispatch_key(test.comparators[0])
    if left is not None and right_key is not None:
        return left, right_key
    if right is not None and left_key is not None:
        return right, left_key
    return None


def _dispatch_subject(node: ast.AST) -> str | None:
    if isinstance(node, ast.Name | ast.Attribute | ast.Subscript):
        return ast.unparse(node)
    return None


def _dispatch_key(node: ast.AST) -> object | None:
    if isinstance(node, ast.Constant) and isinstance(
        node.value, (str, int, float, bool, bytes, type(None))
    ):
        return node.value
    return None


def _has_structural_patterns(node: ast.Match) -> bool:
    for case in node.cases:
        if case.guard is not None:
            return True
        if not _is_simple_pattern(case.pattern):
            return True
    return False


def _is_simple_pattern(pattern: ast.pattern) -> bool:
    if isinstance(pattern, (ast.MatchValue, ast.MatchSingleton)):
        return True
    if isinstance(pattern, ast.MatchAs) and pattern.pattern is None:
        return True
    if isinstance(pattern, ast.MatchOr):
        return all(_is_simple_pattern(p) for p in pattern.patterns)
    return False


def _elif_arms(node: ast.If) -> int:
    arms = 0
    current = node
    while len(current.orelse) == 1 and isinstance(current.orelse[0], ast.If):
        arms += 1
        current = current.orelse[0]
    return arms


def _predicate_suggestions(
    funcdef: AnyFuncdef, breakdown: list[Contribution], total: int
) -> list[Suggestion]:
    unsafe_lines = _predicate_unsafe_lines(funcdef)
    return [
        _make("extract_predicate", c.lineno, c.lineno, c.points, total)
        for c in breakdown
        if c.label == "bool-op"
        and c.points >= _PREDICATE_MIN_POINTS
        and c.lineno not in unsafe_lines
    ]


def _predicate_unsafe_lines(funcdef: AnyFuncdef) -> set[int]:
    return {
        node.lineno
        for node in ast.walk(funcdef)
        if isinstance(node, ast.BoolOp)
        and any(isinstance(child, ast.NamedExpr) for child in ast.walk(node))
    }


def _select(candidates: list[Suggestion]) -> list[Suggestion]:
    good = [c for c in candidates if c.estimated_reduction >= _MIN_REDUCTION]
    good.sort(key=lambda c: (-c.estimated_reduction, c.line_start))
    out: list[Suggestion] = []
    for candidate in good:
        if any(_contains(s, candidate) for s in out):
            continue
        out.append(candidate)
        if len(out) == _MAX_SUGGESTIONS:
            break
    return out


def _contains(outer: Suggestion, inner: Suggestion) -> bool:
    return (
        outer.kind == inner.kind
        and outer.line_start <= inner.line_start
        and outer.line_end >= inner.line_end
    )
