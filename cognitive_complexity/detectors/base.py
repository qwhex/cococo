"""Shared toolkit for refactor detectors.

A *detector* is a pure function ``detect(funcdef, breakdown, total) -> list[Suggestion]``
that names one kind of mechanical refactor. Each lives in its own module under
``detectors/`` and is registered once in ``detectors/__init__.py`` — so detectors
can be written independently (e.g. in parallel) without touching a shared file.

This module is the toolkit they build on: the :class:`Suggestion` shape, the tuned
thresholds, :func:`make_suggestion`, and the AST helpers (region traversal, coupling
analysis, dispatch/equality matching) reused across detectors. Estimates stay tied
to the same :class:`Contribution` data the scorer emits.
"""

from __future__ import annotations

import ast
from collections.abc import Callable
from dataclasses import dataclass
from typing import NamedTuple

from cognitive_complexity.api import Contribution
from cognitive_complexity.common_types import AnyFuncdef, is_funcdef

# Heuristic thresholds (ours, not part of Campbell's metric). Tuned to surface
# only refactors that meaningfully cut the score; adjust here, in one place.
MIN_REDUCTION = 2  # ignore suggestions that barely move the score
MAX_SUGGESTIONS = 3  # keep the report focused on the biggest wins
EXTRACT_MIN_POINTS = 6  # a block heavy enough to pull into its own helper
EXTRACT_MIN_LINES = 5
MAX_COUPLING = 4  # max variables crossing the boundary before extraction is harmful
DISPATCH_MIN_ARMS = 3  # elif arms before "split into a dispatch table"
DISPATCH_MIN_CASES = 4  # match cases, ditto
PREDICATE_MIN_POINTS = 2  # a boolean expression worth naming

REGION_TYPES = (
    ast.If,
    ast.For,
    ast.AsyncFor,
    ast.While,
    ast.Try,
    ast.With,
    ast.AsyncWith,
    ast.Match,
)


class Suggestion(NamedTuple):
    """One concrete, mechanical refactor for a too-complex function.

    ``estimated_reduction`` is how many points the score should drop if applied;
    ``estimated_complexity_after`` is the function total minus that. ``kind`` is a
    stable machine id; ``autofixable`` flags the kinds the ``--fix`` rewriter can
    apply on its own.
    """

    kind: str
    title: str
    line_start: int
    line_end: int
    estimated_reduction: int
    estimated_complexity_after: int
    autofixable: bool
    steps: tuple[str, ...]


@dataclass(frozen=True)
class DetectorContext:
    """Everything a detector needs, with shared work precomputed once.

    ``regions`` (the control-flow region list) is walked a single time here rather
    than re-walked inside every detector — so adding detectors does not multiply
    the per-function cost. Detectors read this; they never re-derive it.
    """

    funcdef: AnyFuncdef
    breakdown: list[Contribution]
    total: int
    regions: list[ast.stmt]


# A detector turns the shared context into suggestions.
Detector = Callable[["DetectorContext"], list[Suggestion]]


def make_suggestion(
    *,
    kind: str,
    title: str,
    steps: tuple[str, ...],
    autofixable: bool,
    start: int,
    end: int,
    reduction: int,
    total: int,
) -> Suggestion:
    """Build a :class:`Suggestion`; the detector owns its kind/title/steps/autofixable."""
    return Suggestion(
        kind=kind,
        title=title,
        line_start=start,
        line_end=end,
        estimated_reduction=reduction,
        estimated_complexity_after=max(0, total - reduction),
        autofixable=autofixable,
        steps=steps,
    )


# --- region traversal ----------------------------------------------------------


def iter_regions(node: ast.AST) -> list[ast.stmt]:
    """Control-flow regions in the function, not descending into nested defs.

    Nested ``def``/``async def`` are independent units, so their inner control
    flow is left out of this function's region list.
    """
    regions: list[ast.stmt] = []
    for child in ast.iter_child_nodes(node):
        if is_funcdef(child):
            continue
        if isinstance(child, REGION_TYPES):
            regions.append(child)
        regions.extend(iter_regions(child))
    return regions


def subtree_points(breakdown: list[Contribution], start: int, end: int) -> int:
    return sum(c.points for c in breakdown if start <= c.lineno <= end)


# --- extraction safety: coupling + mutation ------------------------------------


def is_extractable_region(region: ast.stmt) -> bool:
    """Whether a region is a reasonable candidate for a plain helper extraction."""
    if any(
        isinstance(node, (ast.Break, ast.Continue, ast.Return, ast.Yield, ast.YieldFrom))
        for node in ast.walk(region)
    ):
        return False
    return _attribute_mutation_count(region) <= MAX_COUPLING


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


def analyze_coupling(funcdef: AnyFuncdef, region: ast.stmt) -> int:
    """Count variables crossing the region boundary (inputs + outputs)."""
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


# --- dispatch / equality-chain / match matching --------------------------------


def dispatch_reduction(region: ast.stmt) -> int:
    """Points a dispatch-table refactor would remove from ``region`` (0 if N/A)."""
    if isinstance(region, ast.If):
        arms = elif_arms(region) if is_simple_equality_chain(region) else 0
        return arms if arms >= DISPATCH_MIN_ARMS else 0
    if isinstance(region, ast.Match):
        if _has_structural_patterns(region):
            return 0
        cases = len(region.cases)
        return cases - 1 if cases >= DISPATCH_MIN_CASES else 0
    return 0


def is_simple_equality_chain(node: ast.If) -> bool:
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
    left = dispatch_subject(test.left)
    right = dispatch_subject(test.comparators[0])
    left_key = dispatch_key(test.left)
    right_key = dispatch_key(test.comparators[0])
    if left is not None and right_key is not None:
        return left, right_key
    if right is not None and left_key is not None:
        return right, left_key
    return None


def dispatch_subject(node: ast.AST) -> str | None:
    if isinstance(node, ast.Name | ast.Attribute | ast.Subscript):
        return ast.unparse(node)
    return None


def dispatch_key(node: ast.AST) -> object | None:
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


def elif_arms(node: ast.If) -> int:
    arms = 0
    current = node
    while len(current.orelse) == 1 and isinstance(current.orelse[0], ast.If):
        arms += 1
        current = current.orelse[0]
    return arms


def predicate_unsafe_lines(funcdef: AnyFuncdef) -> set[int]:
    """Lines whose boolean expression can't be safely lifted (contains ``:=``)."""
    return {
        node.lineno
        for node in ast.walk(funcdef)
        if isinstance(node, ast.BoolOp)
        and any(isinstance(child, ast.NamedExpr) for child in ast.walk(node))
    }
