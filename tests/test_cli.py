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
