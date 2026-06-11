import ast
from pathlib import Path
from typing import NamedTuple

AnyFuncdef = ast.FunctionDef | ast.AsyncFunctionDef


class ScoredFunction(NamedTuple):
    """A scored function plus the node it was scored from (for breakdowns/fixes)."""

    score: int
    path: Path
    lineno: int
    qualname: str
    funcdef: AnyFuncdef


class SkippedFile(NamedTuple):
    """A file the scanner could not read, parse, or score, with the reason why."""

    path: Path
    reason: str
