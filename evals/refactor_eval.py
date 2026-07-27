"""Loader + grader for the refactor-suggestion eval set.

Each case is a directory under ``evals/refactors/`` with:

  - ``bad.py``   — the over-complex version (always present)
  - ``good.py``  — the refactored version (positives only; omitted for negatives)
  - ``case.toml``— the metadata/expectations (see ``Case``)

Grading is per-axis so the gate can pass on what the engine implements today and
expand as new suggestion kinds land:

  reduction  (positive) — the entry function's score drops by >= expected_min_reduction,
                          and no function in good.py exceeds the bad entry score
  detection  (positive) — suggest_refactors(bad entry) emits `kind`; graded unless the
                          case sets ``detect = false``
  behavior   (positive) — every `behavior` expr evaluates equal in bad.py and good.py
  precision  (any)      — ``forbidden_kind`` is absent from the suggestions and, when
                          ``silent``, nothing at all is emitted (the two compose)
  fix_claim  (any)      — implicit, never opted into: if any suggestion claims
                          ``autofixable``, ``fix_source`` must apply at least one fix

Every positive case must say something about the engine: either it asserts detection,
or it opts out with ``detect = false`` *and* names the ``forbidden_kind`` it expects to
stay suppressed (e.g. a delta below MIN_REDUCTION). A case marked ``known_gap``
documents a current engine limitation: its failing axes are reported as XFAIL and do
not fail the gate — and a ``known_gap`` case with nothing left failing fails loudly, so
the flag cannot outlive the gap.
"""

from __future__ import annotations

import ast
import sys
from dataclasses import dataclass, field
from pathlib import Path

from cognitive_complexity.common_types import AnyFuncdef, is_funcdef

# tomllib is stdlib from 3.11; tomli is the 3.10 backport (see requirements_dev.txt).
# Whichever interpreter runs, one of these branches is dead — hence a pragma on each.
if sys.version_info >= (3, 11):  # pragma: no cover
    import tomllib
else:  # pragma: no cover
    import tomli as tomllib

from cognitive_complexity.api import (
    get_cognitive_complexity,
    get_cognitive_complexity_breakdown,
)
from cognitive_complexity.autofix import fix_source
from cognitive_complexity.detectors import Suggestion, suggest_refactors

REFACTORS_DIR = Path(__file__).parent / "refactors"

PASS, FAIL, XFAIL = "PASS", "FAIL", "XFAIL"

Axes = dict[str, tuple[str, str]]


@dataclass(frozen=True)
class Case:
    id: str
    dir: Path
    kind: str
    entry: str
    negative: bool = False
    autofixable: bool = False
    expected_min_reduction: int = 1
    detect: bool = True
    silent: bool = False
    forbidden_kind: str | None = None
    known_gap: bool = False
    behavior: tuple[str, ...] = ()
    source: str = ""
    notes: str = ""


@dataclass
class CaseResult:
    case: Case
    axes: Axes = field(default_factory=dict)

    @property
    def failed(self) -> bool:
        return any(status == FAIL for status, _ in self.axes.values())


def load_cases(root: Path = REFACTORS_DIR) -> list[Case]:
    cases: list[Case] = []
    for case_toml in sorted(root.glob("*/case.toml")):
        data = tomllib.loads(case_toml.read_text(encoding="utf-8"))
        behavior = tuple(data.pop("behavior", []) or ())
        cases.append(
            Case(id=case_toml.parent.name, dir=case_toml.parent, behavior=behavior, **data)
        )
    return cases


def _funcs(src: str) -> dict[str, AnyFuncdef]:
    return {n.name: n for n in ast.walk(ast.parse(src)) if is_funcdef(n)}


def _score(funcdef: AnyFuncdef) -> int:
    return get_cognitive_complexity(funcdef)


def grade_case(case: Case) -> CaseResult:
    bad_src = (case.dir / "bad.py").read_text(encoding="utf-8")
    bad_entry = _funcs(bad_src)[case.entry]

    if case.negative:
        axes: Axes = {"precision": _grade_precision(case, bad_entry)}
    else:
        axes = _grade_positive(case, bad_entry, bad_src)
    axes["fix_claim"] = _grade_fix_claim(bad_entry, bad_src)

    return CaseResult(case, _apply_known_gap(axes) if case.known_gap else axes)


def _grade_positive(case: Case, bad_entry: AnyFuncdef, bad_src: str) -> Axes:
    good_src = (case.dir / "good.py").read_text(encoding="utf-8")
    axes: Axes = {"reduction": _grade_reduction(case, bad_entry, good_src)}
    if case.detect:
        axes["detection"] = _grade_detection(case, bad_entry)
    if case.silent or case.forbidden_kind is not None:
        axes["precision"] = _grade_precision(case, bad_entry)
    if case.autofixable:
        axes["autofix"] = _grade_autofix(case, bad_src)
    if case.behavior:
        axes["behavior"] = _grade_behavior(case, bad_src, good_src)
    return axes


def _apply_known_gap(axes: Axes) -> Axes:
    """Report the documented gap instead of failing on it — and expire the flag.

    A ``known_gap`` case whose axes all pass has outlived its gap; saying so as a
    FAIL is the strict-xfail equivalent (nothing else would ever prompt the flip).
    """
    graded: Axes = {
        axis: (XFAIL, f"known gap: {detail}") if status == FAIL else (status, detail)
        for axis, (status, detail) in axes.items()
    }
    if not any(status == XFAIL for status, _ in graded.values()):
        graded["known_gap"] = (FAIL, "known_gap set but every axis passes — clear the flag")
    return graded


def _grade_reduction(case: Case, bad_entry: AnyFuncdef, good_src: str) -> tuple[str, str]:
    bad_score = _score(bad_entry)
    good_funcs = _funcs(good_src)
    if case.entry not in good_funcs:
        return FAIL, f"entry {case.entry!r} missing from good.py"
    good_score = _score(good_funcs[case.entry])
    good_max = max(_score(f) for f in good_funcs.values())
    delta = bad_score - good_score
    detail = f"{case.entry} {bad_score}->{good_score} (-{delta}, need >={case.expected_min_reduction}); good_max={good_max}"
    if delta < case.expected_min_reduction:
        return FAIL, detail
    if good_max > bad_score:
        return FAIL, detail + " [a good fn is worse than bad entry]"
    return PASS, detail


def _suggest(bad_entry: AnyFuncdef) -> list[Suggestion]:
    return suggest_refactors(bad_entry, get_cognitive_complexity_breakdown(bad_entry))


def _grade_detection(case: Case, bad_entry: AnyFuncdef) -> tuple[str, str]:
    kinds = [s.kind for s in _suggest(bad_entry)]
    if case.kind in kinds:
        return PASS, f"emitted {case.kind}"
    return FAIL, f"expected {case.kind}, got {kinds or 'nothing'}"


def _grade_autofix(case: Case, bad_src: str) -> tuple[str, str]:
    """`--fix` actually rewrites the source and the entry's score drops."""
    fixed_src, count = fix_source(bad_src)
    if count < 1:
        return FAIL, "fix_source applied no change"
    bad_score = _score(_funcs(bad_src)[case.entry])
    fixed_score = _score(_funcs(fixed_src)[case.entry])
    delta = bad_score - fixed_score
    detail = f"--fix {case.entry} {bad_score}->{fixed_score} (-{delta}, {count} guard(s))"
    return (PASS if delta >= case.expected_min_reduction else FAIL), detail


def _grade_fix_claim(bad_entry: AnyFuncdef, bad_src: str) -> tuple[str, str]:
    """The converse of the opt-in ``autofix`` axis, asserted on every case.

    ``autofix`` grades cases that *should* be rewritten; this one grades the promise
    itself, so a ``[--fix]`` badge the rewriter declines cannot hide in a case that
    never opted in. It is why no case has to remember to ask for it.
    """
    claimed = sorted({s.kind for s in _suggest(bad_entry) if s.autofixable})
    if not claimed:
        return PASS, "no autofixable claim"
    _fixed, count = fix_source(bad_src)
    if count:
        return PASS, f"{claimed} honoured by --fix ({count} guard(s))"
    return FAIL, f"{claimed} claimed autofixable but --fix applied nothing"


def _grade_precision(case: Case, bad_entry: AnyFuncdef) -> tuple[str, str]:
    """``silent`` and ``forbidden_kind`` are independent, and both are checked."""
    kinds = [s.kind for s in _suggest(bad_entry)]
    if case.silent and kinds:
        return FAIL, f"expected total silence, emitted {kinds}"
    if case.forbidden_kind is not None:
        if case.forbidden_kind in kinds:
            return FAIL, f"{case.forbidden_kind} wrongly emitted (got {kinds})"
        return PASS, f"{case.forbidden_kind} correctly absent"
    if kinds:
        return FAIL, f"expected silence, emitted {kinds}"
    return PASS, "silent"


def _grade_behavior(case: Case, bad_src: str, good_src: str) -> tuple[str, str]:
    bad_ns: dict[str, object] = {}
    good_ns: dict[str, object] = {}
    exec(compile(bad_src, "<bad>", "exec"), bad_ns)  # noqa: S102 - eval set runs trusted local code
    exec(compile(good_src, "<good>", "exec"), good_ns)  # noqa: S102
    for expr in case.behavior:
        b = eval(expr, bad_ns)  # noqa: S307 - trusted local eval-set expressions
        g = eval(expr, good_ns)  # noqa: S307
        if b != g:
            return FAIL, f"{expr}: bad={b!r} good={g!r}"
    return PASS, f"{len(case.behavior)} input(s) match"


def _safe_grade(case: Case) -> CaseResult:
    try:
        return grade_case(case)
    except Exception as exc:  # the CLI table should survive one broken case
        r = CaseResult(case)
        r.axes["load"] = (FAIL, f"{type(exc).__name__}: {exc}")
        return r


def main() -> int:
    cases = load_cases()
    results = [_safe_grade(c) for c in cases]
    width = max((len(c.id) for c in cases), default=4)
    n_fail = 0
    for r in results:
        for axis, (status, detail) in r.axes.items():
            mark = {PASS: "ok ", FAIL: "XX ", XFAIL: "xf "}[status]
            print(f"  {mark}{status:5s} {r.case.id:{width}s}  {axis:9s}  {detail}")
        if r.failed:
            n_fail += 1
    print(f"\n{len(cases)} cases | {len(cases) - n_fail} ok, {n_fail} failing")
    return 1 if n_fail else 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
