"""Grading semantics of the eval harness itself (``evals/refactor_eval.py``).

The cases here are synthetic and built in ``tmp_path`` so these specs pin what a
verdict *means* — and stay stable while the real corpus under ``evals/refactors/``
grows and its scores move. The corpus itself is gated by ``test_eval_refactors.py``.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

import evals.refactor_eval as refactor_eval
from evals.refactor_eval import FAIL, PASS, XFAIL, Case, grade_case, main

# Emits `guard_clause`; scores 6.
GUARD_BAD = """
def count(flag, items):
    if flag:
        total = 0
        for i in items:
            if i > 0:
                total += i
        return total
    return 0
"""

# The same behaviour with the guard peeled off; scores 4.
GUARD_GOOD = """
def count(flag, items):
    if not flag:
        return 0
    total = 0
    for i in items:
        if i > 0:
            total += i
    return total
"""

# Same entry name, a different answer for negative inputs.
GUARD_GOOD_BUGGY = GUARD_GOOD.replace("if i > 0:", "if i != 0:")

# A helper that is worse than the bad entry (21 > 6).
GUARD_GOOD_WITH_TANGLE = (
    GUARD_GOOD
    + """

def _tangle(a, b, c):
    for x in a:
        if x:
            for y in b:
                if y:
                    for z in c:
                        if z:
                            return z
    return None
"""
)

# `--fix` flattens the trailing guard here (6 -> 4); in GUARD_BAD it cannot (a
# `return total` follows the if, so the rewriter leaves it alone).
AUTOFIX_BAD = """
def f(flag, items):
    if flag:
        for i in items:
            if i:
                total = i
"""

AUTOFIX_GOOD = """
def f(flag, items):
    if not flag:
        return
    for i in items:
        if i:
            total = i
"""

# The AUTOFIX_BAD shape, tab-indented: the detector still advertises `--fix` (it never
# sees the source text), the rewriter still declines. The only way the two can disagree.
AUTOFIX_BAD_TABBED = AUTOFIX_BAD.replace("    ", "\t")

FLAT = """
def add(a, b):
    return a + b
"""


def _case(tmp_path: Path, bad: str, good: str | None = None, **meta: Any) -> Case:
    case_id = str(meta.pop("id", "synthetic"))
    case_dir = tmp_path / case_id
    case_dir.mkdir(exist_ok=True)
    (case_dir / "bad.py").write_text(bad, encoding="utf-8")
    if good is not None:
        (case_dir / "good.py").write_text(good, encoding="utf-8")
    meta.setdefault("kind", "guard_clause")
    meta.setdefault("entry", "count")
    return Case(id=case_id, dir=case_dir, **meta)


def _ok_case(tmp_path: Path, **meta: Any) -> Case:
    return _case(tmp_path, GUARD_BAD, GUARD_GOOD, **meta)


# --- detection: asserted unless the case says otherwise ------------------------


def test_detection_is_graded_without_being_asked_for(tmp_path: Path) -> None:
    """A positive case that never mentions `detect` still checks the engine."""
    case = _ok_case(tmp_path, kind="split_dispatcher")
    axes = grade_case(case).axes
    assert axes["reduction"][0] == PASS
    assert axes["detection"][0] == FAIL


def test_detection_passes_when_the_engine_emits_the_kind(tmp_path: Path) -> None:
    assert grade_case(_ok_case(tmp_path)).axes["detection"][0] == PASS


def test_opting_out_of_detection_swaps_in_a_suppression_assertion(tmp_path: Path) -> None:
    """`detect = false` + `forbidden_kind` = "must stay below the noise floor"."""
    case = _ok_case(tmp_path, detect=False, forbidden_kind="split_dispatcher")
    axes = grade_case(case).axes
    assert "detection" not in axes
    assert axes["precision"][0] == PASS


def test_a_suppressed_kind_that_starts_firing_fails_the_case(tmp_path: Path) -> None:
    """The point of the swap: a scoring change that lifts a case above the noise
    floor turns the silent tolerance into a red build, not a green one."""
    case = _ok_case(tmp_path, detect=False, forbidden_kind="guard_clause")
    assert grade_case(case).axes["precision"][0] == FAIL


# --- known_gap: visible, and self-expiring -------------------------------------


def test_known_gap_downgrades_a_failing_axis_to_xfail(tmp_path: Path) -> None:
    result = grade_case(_ok_case(tmp_path, kind="split_dispatcher", known_gap=True))
    assert result.axes["detection"][0] == XFAIL
    assert not result.failed


def test_known_gap_that_no_longer_fails_anything_is_a_stale_flag(tmp_path: Path) -> None:
    result = grade_case(_ok_case(tmp_path, known_gap=True))
    assert result.failed
    assert result.axes["known_gap"][0] == FAIL


# --- precision: `silent` and `forbidden_kind` compose --------------------------


def test_silent_demands_total_silence_alongside_a_forbidden_kind(tmp_path: Path) -> None:
    """Both assertions run: the case forbids split_dispatcher *and* demands
    silence, so the guard_clause the engine does emit fails it."""
    case = _case(tmp_path, GUARD_BAD, negative=True, silent=True, forbidden_kind="split_dispatcher")
    assert grade_case(case).axes["precision"][0] == FAIL


def test_forbidden_kind_alone_tolerates_other_kinds(tmp_path: Path) -> None:
    case = _case(tmp_path, GUARD_BAD, negative=True, forbidden_kind="split_dispatcher")
    assert grade_case(case).axes["precision"][0] == PASS


def test_forbidden_kind_fails_when_that_kind_is_emitted(tmp_path: Path) -> None:
    case = _case(tmp_path, GUARD_BAD, negative=True, forbidden_kind="guard_clause")
    assert grade_case(case).axes["precision"][0] == FAIL


def test_a_negative_with_no_expectations_at_all_demands_silence(tmp_path: Path) -> None:
    quiet = _case(tmp_path, FLAT, entry="add", negative=True, kind="none")
    noisy = _case(tmp_path, GUARD_BAD, id="noisy", negative=True, kind="none")
    assert grade_case(quiet).axes["precision"][0] == PASS
    assert grade_case(noisy).axes["precision"][0] == FAIL


# --- reduction -----------------------------------------------------------------


def test_reduction_fails_when_good_py_lacks_the_entry(tmp_path: Path) -> None:
    case = _case(tmp_path, GUARD_BAD, FLAT)
    assert grade_case(case).axes["reduction"][0] == FAIL


def test_reduction_fails_when_the_score_moves_less_than_promised(tmp_path: Path) -> None:
    case = _ok_case(tmp_path, expected_min_reduction=5)
    assert grade_case(case).axes["reduction"][0] == FAIL


def test_reduction_fails_when_the_refactor_leaves_a_worse_function(tmp_path: Path) -> None:
    """The entry got simpler but a helper is now harder than the original."""
    case = _case(tmp_path, GUARD_BAD, GUARD_GOOD_WITH_TANGLE)
    status, detail = grade_case(case).axes["reduction"]
    assert status == FAIL
    assert "worse than bad entry" in detail


# --- behavior / autofix ---------------------------------------------------------


def test_behavior_axis_catches_a_changed_result(tmp_path: Path) -> None:
    exprs = ["count(True, [1, -2, 3])", "count(False, [1])"]
    kept = _case(tmp_path, GUARD_BAD, GUARD_GOOD, behavior=tuple(exprs))
    changed = _case(tmp_path, GUARD_BAD, GUARD_GOOD_BUGGY, id="changed", behavior=tuple(exprs))
    assert grade_case(kept).axes["behavior"][0] == PASS
    assert grade_case(changed).axes["behavior"][0] == FAIL


def test_fix_claim_axis_is_graded_on_every_case_without_being_asked_for(tmp_path: Path) -> None:
    """The converse of the opt-in `autofix` axis: no case may advertise `--fix` and
    get nothing. It is implicit, so a badge the rewriter refuses cannot hide in a
    case that never opted in."""
    honoured = _case(tmp_path, AUTOFIX_BAD, AUTOFIX_GOOD, entry="f", id="honoured")
    unclaimed = _ok_case(tmp_path, id="unclaimed")
    assert grade_case(honoured).axes["fix_claim"][0] == PASS
    status, detail = grade_case(unclaimed).axes["fix_claim"]
    assert status == PASS
    assert "no autofixable claim" in detail


def test_fix_claim_axis_fails_a_badge_the_rewriter_declines(tmp_path: Path) -> None:
    case = _case(tmp_path, AUTOFIX_BAD_TABBED, AUTOFIX_GOOD, entry="f")
    status, detail = grade_case(case).axes["fix_claim"]
    assert status == FAIL
    assert "guard_clause" in detail


def test_autofix_axis_grades_what_fix_source_actually_did(tmp_path: Path) -> None:
    fixable = _case(tmp_path, AUTOFIX_BAD, AUTOFIX_GOOD, entry="f", autofixable=True)
    unfixable = _ok_case(tmp_path, id="unfixable", autofixable=True)
    assert grade_case(fixable).axes["autofix"][0] == PASS
    status, detail = grade_case(unfixable).axes["autofix"]
    assert status == FAIL
    assert "no change" in detail


# --- the CLI table --------------------------------------------------------------


def test_main_tabulates_every_axis_and_survives_a_broken_case(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    cases = [
        _ok_case(tmp_path, id="passing"),
        _ok_case(tmp_path, id="failing", kind="split_dispatcher"),
        _ok_case(tmp_path, id="gap", kind="split_dispatcher", known_gap=True),
        _ok_case(tmp_path, id="broken", entry="not_in_bad_py"),
    ]
    monkeypatch.setattr(refactor_eval, "load_cases", lambda: cases)

    assert main() == 1

    out = capsys.readouterr().out
    assert "xf " in out, "a known gap must be visible in the table"
    assert "KeyError" in out, "a case that cannot even load is reported, not swallowed"
    assert "4 cases | 2 ok, 2 failing" in out


def test_main_is_green_when_every_case_passes(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(refactor_eval, "load_cases", lambda: [_ok_case(tmp_path)])
    assert main() == 0
    assert "1 cases | 1 ok, 0 failing" in capsys.readouterr().out
