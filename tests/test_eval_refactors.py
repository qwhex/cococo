"""Gate the refactor-suggestion eval set (evals/refactors/).

Each case is graded per axis (reduction / detection / behavior / precision). A
failing axis fails the build; an axis on a `known_gap` case is reported XFAIL and
does not. See evals/refactor_eval.py for the grader, and tests/test_refactor_eval.py
for what each verdict means.
"""

from __future__ import annotations

import pytest

from evals.refactor_eval import FAIL, XFAIL, Case, grade_case, load_cases

CASES = load_cases()


def test_eval_set_is_non_empty():
    assert CASES, "no eval cases found under evals/refactors/"


def test_every_positive_case_makes_a_claim_about_the_engine() -> None:
    """`detect = false` is only allowed when the case names the kind that must stay
    suppressed and says why — otherwise the case grades the corpus, not the engine.
    """
    opted_out = [c for c in CASES if not c.negative and not c.detect]
    unasserted = [c.id for c in opted_out if c.forbidden_kind is None]
    assert not unasserted, (
        "positive cases with detect=false must set forbidden_kind (the suppression they "
        f"assert) or known_gap=true with detect=true: {unasserted}"
    )
    unexplained = [c.id for c in opted_out if not c.notes.strip()]
    assert not unexplained, f"detect=false needs notes explaining the opt-out: {unexplained}"


@pytest.mark.parametrize("case", CASES, ids=lambda c: c.id)
def test_refactor_eval_case(case: Case) -> None:
    result = grade_case(case)
    assert result.axes, f"{case.id}: no axes graded"
    failures = {axis: detail for axis, (status, detail) in result.axes.items() if status == FAIL}
    assert not failures, f"{case.id}: " + "; ".join(f"{a}: {d}" for a, d in failures.items())
    # Surface documented gaps without failing the gate.
    for axis, (status, detail) in result.axes.items():
        if status == XFAIL:
            pytest.xfail(f"{case.id} {axis}: {detail}")
