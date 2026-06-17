import ast
import json
from pathlib import Path

import pytest

from cognitive_complexity.cli import main
from cognitive_complexity.discovery import scored_functions

# A function scoring 10 (over a --max of 5), with the ignore directive on the def line.
IGNORED_OVER = (
    "def f(a, b):  # cococo: ignore\n"
    "    for x in a:\n"
    "        if x:\n"
    "            for y in b:\n"
    "                if y:\n"
    "                    return y\n"
)

NESTED = """
def f(a, b):
    for x in a:        # +1
        if x:          # +2
            for y in b:  # +3
                if y:    # +4
                    return y
"""

FLAT = """
def g(a):
    return a
"""


def _write(tmp_path, name, src):
    path = tmp_path / name
    path.write_text(src)
    return path


def test_score_paths_finds_functions(tmp_path):
    _write(tmp_path, "m.py", NESTED + FLAT)
    scores = {f.qualname: f.score for f in scored_functions([str(tmp_path)])}
    assert scores["f"] == 10
    assert scores["g"] == 0


def test_score_paths_accepts_a_bare_file_and_module_level_statements(tmp_path):
    # A `.py` path is scored directly (not only directories), and module-level
    # statements that aren't defs/classes are walked past without error.
    p = _write(tmp_path, "m.py", "import os\nVALUE = 1\n" + NESTED)
    scores = {f.qualname: f.score for f in scored_functions([str(p)])}
    assert scores == {"f": 10}


def test_score_paths_skips_unparseable_files(tmp_path):
    _write(tmp_path, "good.py", FLAT)
    _write(tmp_path, "bad.py", "def f(:\n    pass\n")
    quals = {f.qualname for f in scored_functions([str(tmp_path)])}
    assert quals == {"g"}


def test_main_gate_fails_when_over_max(tmp_path, capsys):
    _write(tmp_path, "m.py", NESTED)
    assert main([str(tmp_path), "--max", "5"]) == 1
    assert "exceed cognitive complexity 5" in capsys.readouterr().err


def test_main_gate_passes_when_within_max(tmp_path):
    _write(tmp_path, "m.py", FLAT)
    assert main([str(tmp_path), "--max", "5"]) == 0


def test_main_empty_returns_zero(tmp_path):
    assert main([str(tmp_path)]) == 0


def test_gate_fails_loud_on_empty_scan(tmp_path, capsys):
    # A --max gate that scans zero functions is a misconfiguration, not a pass.
    assert main([str(tmp_path), "--max", "10"]) == 2
    assert "no functions scanned" in capsys.readouterr().err


def test_gate_fails_on_nonexistent_path(tmp_path, capsys):
    assert main([str(tmp_path / "missing"), "--max", "10"]) == 2
    assert "no functions scanned" in capsys.readouterr().err


def test_json_empty_scan_emits_valid_report(tmp_path, capsys):
    assert main([str(tmp_path), "--json"]) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["functions"] == []
    assert report["exceeded"] == 0


def test_json_empty_scan_under_gate_fails_but_still_emits_report(tmp_path, capsys):
    assert main([str(tmp_path), "--max", "10", "--json"]) == 2
    assert json.loads(capsys.readouterr().out)["functions"] == []


def test_gate_fails_when_a_file_is_skipped(tmp_path, capsys):
    # A good file under the ceiling plus an unparseable file: the gate must NOT
    # pass — the skipped file could hide an over-complexity function.
    _write(tmp_path, "good.py", FLAT)
    _write(tmp_path, "bad.py", "def f(:\n    pass\n")
    assert main([str(tmp_path), "--max", "10"]) == 2
    assert "skipped" in capsys.readouterr().err


def test_skipped_file_is_reported_even_without_a_gate(tmp_path, capsys):
    _write(tmp_path, "good.py", FLAT)
    _write(tmp_path, "bad.py", "def f(:\n    pass\n")
    assert main([str(tmp_path)]) == 0  # no gate → informational only
    assert "skipped" in capsys.readouterr().err


def test_deeply_nested_file_is_skipped_not_crash(tmp_path, capsys):
    # A crafted deep-AST file (a ~2000-deep subscript) overflows the scorer's
    # recursion; it must skip that one file (loud, gate-failing) rather than
    # abort the whole scan with an uncaught RecursionError.
    _write(tmp_path, "deep.py", "def f():\n    return a" + "[0]" * 2000 + "\n")
    _write(tmp_path, "ok.py", FLAT)
    assert main([str(tmp_path), "--max", "10"]) == 2
    err = capsys.readouterr().err
    assert "skipped" in err
    assert "RecursionError" in err


# --- e9c5: # cococo: ignore directive + --baseline ratchet ---


def test_inline_ignore_excludes_function_from_gate(tmp_path):
    _write(tmp_path, "m.py", IGNORED_OVER)  # f scores 10 (>5) but is ignored
    assert main([str(tmp_path), "--max", "5"]) == 0


def test_unused_ignore_directive_is_warned(tmp_path, capsys):
    _write(tmp_path, "m.py", "def g(a):  # cococo: ignore\n    return a\n")  # score 0
    assert main([str(tmp_path), "--max", "5"]) == 0
    assert "unused '# cococo: ignore'" in capsys.readouterr().err


def test_json_marks_ignored_function_not_over(tmp_path, capsys):
    _write(tmp_path, "m.py", IGNORED_OVER)
    assert main([str(tmp_path), "--max", "5", "--json"]) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["exceeded"] == 0
    assert next(e for e in report["functions"] if e["qualname"] == "f")["over"] is False


def test_ignore_directive_inside_a_string_is_not_honored(tmp_path):
    # The directive must be a real comment, not string content on the def line.
    src = (
        'def f(a, b="# cococo: ignore"):\n'
        "    for x in a:\n"
        "        if x:\n"
        "            for y in b:\n"
        "                if y:\n"
        "                    return y\n"
    )
    _write(tmp_path, "m.py", src)
    assert main([str(tmp_path), "--max", "5"]) == 1  # not ignored → gate fails


def test_baseline_missing_is_created_and_passes(tmp_path, capsys):
    _write(tmp_path, "m.py", NESTED)  # f scores 10
    bl = tmp_path / "baseline.json"
    assert main([str(tmp_path), "--max", "5", "--baseline", str(bl)]) == 0
    assert "wrote baseline" in capsys.readouterr().err
    assert any(k.endswith("::f") for k in json.loads(bl.read_text()))


def test_baseline_missing_is_not_created_when_scan_skips_file(tmp_path, capsys):
    _write(tmp_path, "good.py", FLAT)
    _write(tmp_path, "bad.py", "def f(:\n    pass\n")
    bl = tmp_path / "baseline.json"

    assert main([str(tmp_path), "--max", "5", "--baseline", str(bl)]) == 2

    err = capsys.readouterr().err
    assert "skipped" in err
    assert "wrote baseline" not in err
    assert not bl.exists()


def test_baseline_grandfathers_recorded_offender(tmp_path):
    _write(tmp_path, "m.py", NESTED)
    bl = tmp_path / "baseline.json"
    bl.write_text(json.dumps({f"{tmp_path / 'm.py'}::f": 10}))  # recorded at current score
    assert main([str(tmp_path), "--max", "5", "--baseline", str(bl)]) == 0


def test_malformed_baseline_returns_untrusted_exit(tmp_path, capsys):
    _write(tmp_path, "m.py", FLAT)
    bl = tmp_path / "baseline.json"
    bl.write_text("not json")

    assert main([str(tmp_path), "--max", "5", "--baseline", str(bl)]) == 2

    err = capsys.readouterr().err.lower()
    assert "baseline" in err
    assert "invalid" in err


def test_invalid_baseline_shape_returns_untrusted_exit(tmp_path, capsys):
    _write(tmp_path, "m.py", FLAT)
    bl = tmp_path / "baseline.json"
    bl.write_text(json.dumps({f"{tmp_path / 'm.py'}::g": "0"}))

    assert main([str(tmp_path), "--max", "5", "--baseline", str(bl)]) == 2

    err = capsys.readouterr().err.lower()
    assert "baseline" in err
    assert "dict[str, int]" in err


def test_unreadable_baseline_returns_untrusted_exit(tmp_path, capsys, monkeypatch):
    _write(tmp_path, "m.py", FLAT)
    bl = tmp_path / "baseline.json"
    bl.write_text("{}")
    original_read_text = Path.read_text

    def fail_baseline_read(self: Path, *args: object, **kwargs: object) -> str:
        if self == bl:
            raise OSError("permission denied")
        return original_read_text(self, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", fail_baseline_read)

    assert main([str(tmp_path), "--max", "5", "--baseline", str(bl)]) == 2

    err = capsys.readouterr().err.lower()
    assert "baseline" in err
    assert "permission denied" in err


def test_baseline_keys_match_relative_and_absolute_invocations(tmp_path, monkeypatch):
    src = tmp_path / "src"
    src.mkdir()
    _write(src, "m.py", NESTED)
    bl = tmp_path / "baseline.json"

    monkeypatch.chdir(tmp_path)
    assert main(["src", "--max", "5", "--baseline", "baseline.json"]) == 0
    assert "src/m.py::f" in json.loads(bl.read_text())
    assert main([str(src), "--max", "5", "--baseline", str(bl)]) == 0


def test_baseline_fails_when_function_regresses_above_recorded(tmp_path):
    _write(tmp_path, "m.py", NESTED)  # f now scores 10
    bl = tmp_path / "baseline.json"
    bl.write_text(json.dumps({f"{tmp_path / 'm.py'}::f": 7}))  # recorded lower → regression
    assert main([str(tmp_path), "--max", "5", "--baseline", str(bl)]) == 1


def test_baseline_requires_max(tmp_path):
    with pytest.raises(SystemExit):
        main([str(tmp_path), "--baseline", str(tmp_path / "b.json")])


def test_baseline_write_failure_is_reported_as_error(tmp_path, capsys):
    # Baseline path under a non-existent directory: the create write fails, which
    # surfaces as a BaselineError (exit code 2), not a crash.
    _write(tmp_path, "m.py", NESTED)
    bl = tmp_path / "no_such_dir" / "baseline.json"
    assert main([str(tmp_path), "--max", "5", "--baseline", str(bl)]) == 2
    assert "baseline" in capsys.readouterr().err.lower()


def test_baseline_key_falls_back_to_absolute_when_file_outside_baseline_dir(tmp_path):
    # Scanned file lives outside the baseline's directory, so it can't be made
    # relative to it; the key falls back to the absolute (posix) path.
    src = tmp_path / "src"
    src.mkdir()
    _write(src, "m.py", NESTED)
    other = tmp_path / "other"
    other.mkdir()
    bl = other / "baseline.json"
    assert main([str(src), "--max", "5", "--baseline", str(bl)]) == 0
    key = next(iter(json.loads(bl.read_text())))
    assert key.startswith("/") and key.endswith("m.py::f")


def test_main_lists_all_functions_worst_first(tmp_path, capsys):
    # Plain listing mode (no --max): every function is printed, worst first.
    _write(tmp_path, "m.py", NESTED + FLAT)
    assert main([str(tmp_path)]) == 0
    quals = [line.split()[-1] for line in capsys.readouterr().out.splitlines() if line]
    assert quals == ["f", "g"]  # f (10) ranks above g (0)


# --- refactor suggestions, JSON output, and --fix (added with the refactor feature) ---

NO_SUGGESTION = """
def busy(a, b, c, d, e, f):
    if a:
        x = 1
    if b:
        x = 2
    if c:
        x = 3
    if d:
        x = 4
    if e:
        x = 5
    if f:
        x = 6
"""

FIXABLE = """
def f(x, items):
    setup()
    if x:
        for item in items:
            if item.ok:
                handle(item)
"""


def _suggestion_kinds_from_cli(tmp_path, capsys, src):
    path = _write(tmp_path, "m.py", src)
    assert main([str(path), "--json", "--min", "0"]) == 0
    report = json.loads(capsys.readouterr().out)
    [func] = report["functions"]
    return {suggestion["kind"] for suggestion in func["suggestions"]}


def test_gate_failure_prints_actionable_suggestions(tmp_path, capsys):
    _write(tmp_path, "m.py", NESTED)
    assert main([str(tmp_path), "--max", "5"]) == 1
    err = capsys.readouterr().err
    assert "guard clause" in err.lower()
    assert "[--fix]" in err  # the guard-clause suggestion is auto-fixable


def test_gate_failure_handles_functions_with_no_mechanical_fix(tmp_path, capsys):
    _write(tmp_path, "m.py", NO_SUGGESTION)
    assert main([str(tmp_path), "--max", "5"]) == 1
    assert "no mechanical refactor found" in capsys.readouterr().err


def test_json_output_is_valid_and_structured(tmp_path, capsys):
    _write(tmp_path, "m.py", NESTED)
    assert main([str(tmp_path), "--max", "5", "--json"]) == 1
    report = json.loads(capsys.readouterr().out)
    assert report["max"] == 5
    assert report["exceeded"] == 1
    func = report["functions"][0]
    assert func["qualname"] == "f"
    assert func["over"] is True
    assert func["breakdown"]
    assert any(s["kind"] == "guard_clause" for s in func["suggestions"])


def test_json_output_without_max_exits_zero(tmp_path, capsys):
    _write(tmp_path, "m.py", FLAT)
    assert main([str(tmp_path), "--json"]) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["max"] is None
    assert report["exceeded"] == 0


def test_json_report_includes_scan_coverage(tmp_path, capsys):
    # A pipeline must be able to tell a clean scan from a partial one.
    _write(tmp_path, "good.py", NESTED)
    _write(tmp_path, "bad.py", "def f(:\n    pass\n")
    assert main([str(tmp_path), "--json"]) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["files_scanned"] == 1
    assert len(report["skipped"]) == 1
    assert report["skipped"][0]["path"].endswith("bad.py")
    assert "SyntaxError" in report["skipped"][0]["reason"]


def test_cli_does_not_suggest_predicate_for_walrus_condition(tmp_path, capsys):
    kinds = _suggestion_kinds_from_cli(
        tmp_path,
        capsys,
        """
def f(pattern, text):
    if (m := pattern.match(text)) and (m.group(1) or m.group(2)):
        return m.group(1)
    return None
""",
    )

    assert "extract_predicate" not in kinds


def test_cli_does_not_suggest_dispatcher_for_ordered_predicates(tmp_path, capsys):
    kinds = _suggestion_kinds_from_cli(
        tmp_path,
        capsys,
        """
def classify(x):
    if x < 0:
        return "negative"
    elif x == 0:
        return "zero"
    elif x < 10:
        return "small"
    elif x < 100:
        return "medium"
    else:
        return "large"
""",
    )

    assert "split_dispatcher" not in kinds


def test_cli_does_not_suggest_dispatcher_for_side_effect_conditions(tmp_path, capsys):
    kinds = _suggestion_kinds_from_cli(
        tmp_path,
        capsys,
        """
def route(req):
    if req.consume("admin"):
        return admin(req)
    elif req.consume("user"):
        return user(req)
    elif req.consume("guest"):
        return guest(req)
    elif req.consume("anon"):
        return anon(req)
    return reject(req)
""",
    )

    assert "split_dispatcher" not in kinds


def test_cli_does_not_suggest_extract_helper_for_loop_control_flow(tmp_path, capsys):
    kinds = _suggestion_kinds_from_cli(
        tmp_path,
        capsys,
        """
def scan(rows, verbose, debug):
    if verbose and debug:
        log("scan")
    found = []
    for row in rows:
        if row.skip:
            continue
        if row.stop:
            break
        for cell in row.cells:
            if cell.ok:
                found.append(cell)
    return found
""",
    )

    assert "extract_helper" not in kinds


def test_cli_does_not_suggest_extract_helper_for_generator_region(tmp_path, capsys):
    kinds = _suggestion_kinds_from_cli(
        tmp_path,
        capsys,
        """
def stream(rows, verbose, debug):
    if verbose and debug:
        log("stream")
    for row in rows:
        if row.enabled:
            for item in row.items:
                if item.ready:
                    yield item
    return
""",
    )

    assert "extract_helper" not in kinds


def test_cli_does_not_suggest_extract_helper_for_many_mutated_state_fields(tmp_path, capsys):
    kinds = _suggestion_kinds_from_cli(
        tmp_path,
        capsys,
        """
def compute(state, flag):
    if flag and state.ready:
        log(state)
    if flag:
        state.a += 1
        state.b += state.a
        state.c += state.b
        state.d += state.c
        state.e += state.d
        for i in range(state.e):
            if i % 2:
                state.c += i
            if state.c > 100:
                return state
    return state
""",
    )

    assert "extract_helper" not in kinds


def test_fix_rewrites_file_and_lowers_score(tmp_path, capsys):
    path = _write(tmp_path, "m.py", FIXABLE)
    before = {f.qualname: f.score for f in scored_functions([str(path)])}
    assert main([str(path), "--fix", "--min", "0"]) == 0
    after = {f.qualname: f.score for f in scored_functions([str(path)])}
    assert after["f"] < before["f"]
    assert "if not (x):" in path.read_text()
    err = capsys.readouterr().err
    assert "guard-clause fix(es)" in err  # aggregate rollup
    assert f"fixed {path}" in err  # per-file audit trail (ae65)


def test_fix_then_gate_can_pass_after_rewrite(tmp_path):
    # A function that fails the gate, then passes once --fix flattens it.
    path = _write(tmp_path, "m.py", FIXABLE)
    assert main([str(path), "--max", "5"]) == 1
    assert main([str(path), "--fix", "--max", "5"]) == 0


def test_fix_skips_unparseable_files_without_crashing(tmp_path, capsys):
    _write(tmp_path, "bad.py", "def f(:\n    pass\n")
    assert main([str(tmp_path), "--fix", "--min", "0"]) == 0
    assert "applied 0 guard-clause fix(es)" in capsys.readouterr().err


def test_fix_leaves_files_without_fixable_pattern_untouched(tmp_path, capsys):
    path = _write(tmp_path, "m.py", FLAT)  # nothing to flatten
    assert main([str(path), "--fix", "--min", "0"]) == 0
    assert path.read_text() == FLAT
    assert "applied 0 guard-clause fix(es)" in capsys.readouterr().err


def test_fix_write_failure_is_reported_and_exits_nonzero(tmp_path, capsys, monkeypatch):
    # A write that fails mid-batch must not abort the run, must be reported, and
    # must surface in the exit code (was: silent success / exit 0).
    import cognitive_complexity.cli as climod

    path = _write(tmp_path, "m.py", FIXABLE)

    def boom(_path: object, _data: object) -> None:
        raise OSError("disk full")

    monkeypatch.setattr(climod, "atomic_write", boom)
    assert main([str(path), "--fix", "--min", "0"]) == 2
    err = capsys.readouterr().err
    assert "FAILED to write" in err
    assert path.read_text() == FIXABLE  # original untouched


# --- Option A: named nested functions are scored as their own units ---

NESTED_FACTORY = """
def create_app():
    app = make()

    def handler_a(x):
        if x > 0:
            for i in range(x):
                if i % 2:
                    log(i)
        return x

    def handler_b(x):
        if x < 0:
            return -x
        return x

    return app
"""

METHOD_LOCAL = """
class K:
    def m(self, xs):
        def inner(x):
            if x:
                return 1
        return inner
"""

NESTED_RECURSION = """
def outer(n):
    def rec(k):
        return rec(k - 1)
    return rec(n)
"""


def test_nested_defs_reported_as_own_units(tmp_path):
    _write(tmp_path, "m.py", NESTED_FACTORY)
    scores = {f.qualname: f.score for f in scored_functions([str(tmp_path)])}
    # The factory itself is trivial; each handler is scored on its own merits,
    # from nesting 0 (no containment surcharge).
    assert scores["create_app"] == 0
    assert scores["create_app.<locals>.handler_a"] == 6
    assert scores["create_app.<locals>.handler_b"] == 1


def test_method_local_nested_def_keeps_class_in_qualname(tmp_path):
    _write(tmp_path, "m.py", METHOD_LOCAL)
    quals = {f.qualname for f in scored_functions([str(tmp_path)])}
    assert "K.m" in quals
    assert "K.m.<locals>.inner" in quals


def test_lambda_still_folds_into_parent(tmp_path):
    # Lambdas are anonymous and keep folding: the `x and x` bool-op counts toward
    # `f`, and no separate lambda unit is reported.
    _write(tmp_path, "m.py", "def f(a):\n    g = lambda x: x and x\n    return g(a)\n")
    scores = {f.qualname: f.score for f in scored_functions([str(tmp_path)])}
    assert scores == {"f": 1}


def test_nested_recursion_scored_in_nested_unit_not_outer(tmp_path):
    _write(tmp_path, "m.py", NESTED_RECURSION)
    scores = {f.qualname: f.score for f in scored_functions([str(tmp_path)])}
    assert scores["outer.<locals>.rec"] == 1  # rec calls itself
    assert scores["outer"] == 0  # outer's call to rec is not outer-recursion


def test_explain_resolves_nested_def_by_qualname(tmp_path, capsys):
    p = _write(tmp_path, "m.py", NESTED_FACTORY)
    assert main(["--explain", f"{p}::create_app.<locals>.handler_a"]) == 0
    assert "cognitive complexity = 6" in capsys.readouterr().out


def test_explain_resolves_nested_def_by_line(tmp_path, capsys):
    p = _write(tmp_path, "m.py", NESTED_FACTORY)
    line = next(
        n.lineno
        for n in ast.walk(ast.parse(NESTED_FACTORY))
        if isinstance(n, ast.FunctionDef) and n.name == "handler_a"
    )
    assert main(["--explain", f"{p}:{line}"]) == 0
    assert "handler_a" in capsys.readouterr().out


# --- --nested=fold compatibility mode (pre-2.0.0 scoring) ---

DECORATOR = """
def deco(f):
    def wrapper(x):
        if x:
            return f(x)
    return wrapper
"""


def test_nested_fold_mode_folds_handlers_into_parent(tmp_path):
    _write(tmp_path, "m.py", NESTED_FACTORY)
    scores = {f.qualname: f.score for f in scored_functions([str(tmp_path)], fold_nested=True)}
    # Fold mode: handlers are NOT separate units; they fold into create_app, each
    # scored one nesting level deeper (handler_a 6->9, handler_b 1->2 => 11).
    assert scores == {"create_app": 11}


def test_nested_fold_mode_scores_decorator_by_inner_function(tmp_path):
    _write(tmp_path, "m.py", DECORATOR)
    scores = {f.qualname: f.score for f in scored_functions([str(tmp_path)], fold_nested=True)}
    # is_decorator: deco returns its single inner, so it is scored AS wrapper
    # (the `if x` at nesting 0 = 1), not wrapper-folded-at-nesting-1 (which is 2).
    assert scores == {"deco": 1}


def test_nested_fold_two_statement_non_decorator_folds_normally(tmp_path):
    # Exactly two statements and the first is a nested def, but it is NOT returned
    # by name — so this is not a decorator. In fold mode it scores normally with
    # the inner def folded in (the `if x` at nesting 1 => 2), not scored-as-inner.
    src = "def f(x):\n    def g():\n        if x:\n            return 1\n    return 2\n"
    _write(tmp_path, "m.py", src)
    scores = {fn.qualname: fn.score for fn in scored_functions([str(tmp_path)], fold_nested=True)}
    assert scores == {"f": 2}


def test_cli_nested_fold_flag_collapses_units(tmp_path, capsys):
    _write(tmp_path, "m.py", NESTED_FACTORY)
    assert main([str(tmp_path), "--min", "0"]) == 0
    assert "create_app.<locals>.handler_a" in capsys.readouterr().out  # unit mode: separate
    assert main([str(tmp_path), "--min", "0", "--nested", "fold"]) == 0
    fold_out = capsys.readouterr().out
    assert "<locals>" not in fold_out  # fold mode: one create_app row
    assert "create_app" in fold_out


def test_explain_respects_nested_fold_mode(tmp_path, capsys):
    p = _write(tmp_path, "m.py", NESTED_FACTORY)
    # In fold mode the nested unit no longer exists; create_app is the whole score.
    assert main(["--explain", f"{p}::create_app", "--nested", "fold"]) == 0
    assert "cognitive complexity = 11" in capsys.readouterr().out
