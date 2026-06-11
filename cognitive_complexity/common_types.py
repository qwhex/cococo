import ast
from pathlib import Path
from typing import NamedTuple

AnyFuncdef = ast.FunctionDef | ast.AsyncFunctionDef


class ScoredFunction(NamedTuple):
    """A scored function plus the node it was scored from (for breakdowns/fixes).

    ``ignored`` is true when the function's ``def`` line carries a
    ``# cococo: ignore`` directive, which excludes it from the ``--max`` gate.
    """

    score: int
    path: Path
    lineno: int
    qualname: str
    funcdef: AnyFuncdef
    ignored: bool = False


class SkippedFile(NamedTuple):
    """A file the scanner could not read, parse, or score, with the reason why."""

    path: Path
    reason: str
