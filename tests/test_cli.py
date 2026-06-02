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


def test_main_gate_fails_when_over_max(tmp_path, capsys):
    _write(tmp_path, "m.py", NESTED)
    assert main([str(tmp_path), "--max", "5"]) == 1
    assert "exceed cognitive complexity 5" in capsys.readouterr().err


def test_main_gate_passes_when_within_max(tmp_path):
    _write(tmp_path, "m.py", FLAT)
    assert main([str(tmp_path), "--max", "5"]) == 0


def test_main_empty_returns_zero(tmp_path):
    assert main([str(tmp_path)]) == 0
