"""Gate the refactor-suggestion eval set (evals/refactors/).

Each case is graded per axis (reduction / detection / behavior / precision). A
failing axis fails the build; an axis on a `known_gap` case is reported XFAIL and
does not. See evals/refactor_eval.py for the grader.
"""

from __future__ import annotations

import pytest

from evals.refactor_eval import FAIL, XFAIL, Case, grade_case, load_cases

CASES = load_cases()


def test_eval_set_is_non_empty():
    assert CASES, "no eval cases found under evals/refactors/"


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
