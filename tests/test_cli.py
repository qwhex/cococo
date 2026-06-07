import ast
import json

from cognitive_complexity.cli import main, score_paths

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
    scores = {qual: score for score, _, _, qual in score_paths([str(tmp_path)])}
    assert scores["f"] == 10
    assert scores["g"] == 0


def test_score_paths_accepts_a_bare_file_and_module_level_statements(tmp_path):
    # A `.py` path is scored directly (not only directories), and module-level
    # statements that aren't defs/classes are walked past without error.
    p = _write(tmp_path, "m.py", "import os\nVALUE = 1\n" + NESTED)
    scores = {qual: score for score, _, _, qual in score_paths([str(p)])}
    assert scores == {"f": 10}


def test_score_paths_skips_unparseable_files(tmp_path):
    _write(tmp_path, "good.py", FLAT)
    _write(tmp_path, "bad.py", "def f(:\n    pass\n")
    quals = {qual for _, _, _, qual in score_paths([str(tmp_path)])}
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


def test_fix_rewrites_file_and_lowers_score(tmp_path, capsys):
    path = _write(tmp_path, "m.py", FIXABLE)
    before = {q: s for s, _, _, q in score_paths([str(path)])}
    assert main([str(path), "--fix", "--min", "0"]) == 0
    after = {q: s for s, _, _, q in score_paths([str(path)])}
    assert after["f"] < before["f"]
    assert "if not (x):" in path.read_text()
    assert "guard-clause fix(es)" in capsys.readouterr().err


def test_fix_then_gate_can_pass_after_rewrite(tmp_path):
    # A function that fails the gate, then passes once --fix flattens it.
    path = _write(tmp_path, "m.py", FIXABLE)
    assert main([str(path), "--max", "5"]) == 1
    assert main([str(path), "--fix", "--max", "5"]) == 0


def test_fix_skips_unparseable_files_without_crashing(tmp_path, capsys):
    _write(tmp_path, "bad.py", "def f(:\n    pass\n")
    assert main([str(tmp_path), "--fix", "--min", "0"]) == 0
    assert "applied 0 guard-clause fix(es)" in capsys.readouterr().err


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
    scores = {q: s for s, _, _, q in score_paths([str(tmp_path)])}
    # The factory itself is trivial; each handler is scored on its own merits,
    # from nesting 0 (no containment surcharge).
    assert scores["create_app"] == 0
    assert scores["create_app.<locals>.handler_a"] == 6
    assert scores["create_app.<locals>.handler_b"] == 1


def test_method_local_nested_def_keeps_class_in_qualname(tmp_path):
    _write(tmp_path, "m.py", METHOD_LOCAL)
    quals = {q for _, _, _, q in score_paths([str(tmp_path)])}
    assert "K.m" in quals
    assert "K.m.<locals>.inner" in quals


def test_lambda_still_folds_into_parent(tmp_path):
    # Lambdas are anonymous and keep folding: the `x and x` bool-op counts toward
    # `f`, and no separate lambda unit is reported.
    _write(tmp_path, "m.py", "def f(a):\n    g = lambda x: x and x\n    return g(a)\n")
    scores = {q: s for s, _, _, q in score_paths([str(tmp_path)])}
    assert scores == {"f": 1}


def test_nested_recursion_scored_in_nested_unit_not_outer(tmp_path):
    _write(tmp_path, "m.py", NESTED_RECURSION)
    scores = {q: s for s, _, _, q in score_paths([str(tmp_path)])}
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
