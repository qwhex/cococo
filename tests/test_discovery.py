"""Path walking: what a whole-tree scan reaches, and what it must never reach."""

from pathlib import Path

from cognitive_complexity.discovery import iter_python_files

SRC = "def f():\n    return 1\n"


def _tree(root: Path) -> None:
    """A project layout with the trees a scan must prune around it."""
    for rel in (
        "pkg/mod.py",
        ".venv/lib/python3.12/site-packages/dep.py",
        ".git/hooks/hook.py",
        ".tox/py312/x.py",
        "build/gen.py",
        "dist/built.py",
        "node_modules/tool/helper.py",
        "pkg/__pycache__/mod.py",
        "pkg.egg-info/meta.py",
    ):
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(SRC)


def test_walk_prunes_venv_vendor_build_and_hidden_dirs(tmp_path):
    # The blast-radius property: `cococo .` (and therefore `cococo . --fix`)
    # must see project source only, never installed or generated trees.
    _tree(tmp_path)
    found = [p.relative_to(tmp_path).as_posix() for p in iter_python_files([str(tmp_path)])]
    assert found == ["pkg/mod.py"]


def test_named_file_inside_an_excluded_dir_is_still_scanned(tmp_path):
    # Exclusions prune the *walk*; a path the user names explicitly is opted in.
    _tree(tmp_path)
    named = tmp_path / ".venv/lib/python3.12/site-packages/dep.py"
    assert list(iter_python_files([str(named)])) == [named]


def test_exclude_patterns_prune_directories_and_files(tmp_path):
    (tmp_path / "vendor").mkdir()
    (tmp_path / "vendor/lib.py").write_text(SRC)
    (tmp_path / "keep.py").write_text(SRC)
    (tmp_path / "schema_pb2.py").write_text(SRC)

    found = iter_python_files([str(tmp_path)], exclude=["vendor", "*_pb2.py"])

    assert [p.name for p in found] == ["keep.py"]


def test_walk_does_not_follow_symlinked_directories(tmp_path):
    # Following them would both leave the scanned tree and risk a cycle.
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "far.py").write_text(SRC)
    scanned = tmp_path / "scanned"
    scanned.mkdir()
    (scanned / "near.py").write_text(SRC)
    (scanned / "link").symlink_to(outside, target_is_directory=True)

    assert [p.name for p in iter_python_files([str(scanned)])] == ["near.py"]
