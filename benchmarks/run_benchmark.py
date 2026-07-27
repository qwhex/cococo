#!/usr/bin/env python3
"""Performance benchmark for the cognitive-complexity algorithm.

Times ``get_cognitive_complexity`` in-process over synthetic functions — this
isolates the algorithm (no pytest/interpreter startup noise) and is the
sensitive guard against per-node overhead and super-linear blow-ups.

Three modes:

* ``compute`` (default) -- repeatedly score one large function and report the
  wall-clock distribution (mean/median/stdev/p95) plus per-call time.

* ``sweep`` -- score functions of increasing size and report time *per AST
  node*. If the algorithm is linear that figure stays flat as the function
  grows; a rising per-node time signals an accidental O(n^2).

* ``suggest`` -- the regression guard for the *suggestion engine*. Over the eval
  corpus (``evals/refactors/*/bad.py``), it times ``suggest_refactors`` against
  the breakdown we already compute, and reports the **overhead ratio** (suggest
  time / scoring time) plus a per-kind breakdown. As detectors accumulate, that
  one ratio is what climbs -- watch it, not micro-benchmarks of each detector.
  ``--no-suggest`` removes this cost entirely, which this mode quantifies.

Run from the repo root so the package is importable::

    python -m benchmarks.run_benchmark                       # compute, default size
    python -m benchmarks.run_benchmark --depth 20 --breadth 400
    python -m benchmarks.run_benchmark --mode sweep
    python -m benchmarks.run_benchmark --mode suggest
"""

from __future__ import annotations

import argparse
import ast
import json
import statistics
import subprocess
import time
from collections import defaultdict
from collections.abc import Callable
from datetime import datetime
from functools import partial
from pathlib import Path
from typing import TypedDict

from cognitive_complexity.api import (
    get_cognitive_complexity,
    get_cognitive_complexity_breakdown,
)
from cognitive_complexity.common_types import AnyFuncdef, is_funcdef
from cognitive_complexity.detectors import suggest_refactors


class SuggestSummary(TypedDict):
    """One `suggest` measurement pass — also the JSONL log record (see `_append_log`)."""

    corpus_n: int
    score_median_us: float
    suggest_median_us: float
    suggest_p95_us: float
    suggest_p99_us: float
    suggest_max_us: float
    full_pass_us: float
    overhead_ratio: float
    by_kind_median_us: dict[str, float]


def _build_large_function(depth: int, breadth: int) -> AnyFuncdef:
    """Generate a deeply nested + wide function for the compute benchmark."""
    lines = ["def big(a, b, c, d):"]
    indent = "    "
    for level in range(depth):
        pad = indent * (level + 1)
        lines.append(f"{pad}if a and b or c and d:  # nesting {level}")
    pad = indent * (depth + 1)
    lines.extend(f"{pad}x{i} = a if b else c" for i in range(breadth))
    funcdef = ast.parse("\n".join(lines)).body[0]
    assert is_funcdef(funcdef)
    return funcdef


def _count_nodes(funcdef: AnyFuncdef) -> int:
    return sum(1 for _ in ast.walk(funcdef))


def run_compute_once(funcdef: AnyFuncdef, repeats: int) -> float:
    """Time ``repeats`` scorings of one funcdef in-process; return seconds."""
    start = time.perf_counter()
    for _ in range(repeats):
        get_cognitive_complexity(funcdef)
    return time.perf_counter() - start


def _sample(funcdef: AnyFuncdef, repeats: int, runs: int, warmup: int) -> list[float]:
    """Per-scoring seconds across ``runs`` timed samples (after ``warmup``)."""
    for _ in range(warmup):
        run_compute_once(funcdef, repeats)
    return [run_compute_once(funcdef, repeats) / repeats for _ in range(runs)]


def percentile(values: list[float], pct: float) -> float:
    """Linear-interpolated percentile (pct in 0..100)."""
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    k = (len(ordered) - 1) * (pct / 100)
    lo = int(k)
    hi = min(lo + 1, len(ordered) - 1)
    return ordered[lo] + (ordered[hi] - ordered[lo]) * (k - lo)


def summarize(label: str, per_call: list[float]) -> dict[str, float]:
    """Print and return mean/median/stdev/min/max/p95 for per-call seconds."""
    mean = statistics.mean(per_call)
    stats = {
        "runs": len(per_call),
        "mean": mean,
        "median": statistics.median(per_call),
        "stdev": statistics.stdev(per_call) if len(per_call) > 1 else 0.0,
        "min": min(per_call),
        "max": max(per_call),
        "p95": percentile(per_call, 95),
    }
    cv = (stats["stdev"] / mean * 100) if mean else 0.0
    print(f"\n{label} over {stats['runs']} runs:")
    print(f"  mean   {mean * 1e6:9.2f} us/call")
    print(f"  median {stats['median'] * 1e6:9.2f} us/call")
    print(f"  stdev  {stats['stdev'] * 1e6:9.2f} us/call  ({cv:.1f}% CV)")
    print(f"  min    {stats['min'] * 1e6:9.2f} us/call")
    print(f"  p95    {stats['p95'] * 1e6:9.2f} us/call")
    return stats


def run_sweep(sizes: list[int], depth: int, repeats: int, runs: int, warmup: int) -> None:
    """Score functions of growing width; report time per AST node to expose
    any super-linear scaling (per-node time should stay flat if linear)."""
    print(f"\nScaling sweep (depth={depth}, median of {runs} runs):")
    print(f"  {'stmts':>6}  {'nodes':>7}  {'per-call':>11}  {'per-node':>9}")
    per_node: list[float] = []
    for breadth in sizes:
        funcdef = _build_large_function(depth, breadth)
        nodes = _count_nodes(funcdef)
        call = statistics.median(_sample(funcdef, repeats, runs, warmup))
        per_node.append(call / nodes)
        print(f"  {breadth:>6}  {nodes:>7}  {call * 1e6:>8.2f}us  {call / nodes * 1e6:>7.4f}us")
    ratio = per_node[-1] / per_node[0] if per_node[0] else 0.0
    verdict = "≈linear" if ratio < 1.5 else "SUPER-LINEAR — investigate"
    print(
        f"\n  per-node {per_node[0] * 1e6:.4f}us -> {per_node[-1] * 1e6:.4f}us "
        f"({ratio:.2f}x over {sizes[0]}->{sizes[-1]} stmts): {verdict}"
    )


def _load_corpus() -> list[tuple[str, str, AnyFuncdef]]:
    """The eval ``bad.py`` entry functions + their kind, as the benchmark workload.

    Reads ``evals/refactors/*/case.toml`` (kind + entry) and the matching
    ``bad.py``. These are the worst-case complex functions where detectors work
    hardest, and the corpus grows for free as eval cases are added.
    """
    from evals.refactor_eval import load_cases

    corpus: list[tuple[str, str, AnyFuncdef]] = []
    for case in load_cases():
        funcs = {
            n.name: n
            for n in ast.walk(ast.parse((case.dir / "bad.py").read_text(encoding="utf-8")))
            if is_funcdef(n)
        }
        funcdef = funcs.get(case.entry)
        if funcdef is not None:
            corpus.append((case.id, case.kind, funcdef))
    return corpus


def _per_call(work: Callable[[], object], repeats: int, runs: int, warmup: int) -> float:
    """Median per-call seconds for ``work`` (a no-arg callable), after warmup."""

    def once() -> float:
        start = time.perf_counter()
        for _ in range(repeats):
            work()
        return (time.perf_counter() - start) / repeats

    for _ in range(warmup):
        once()
    return statistics.median(once() for _ in range(runs))


def measure_suggest(repeats: int, runs: int, warmup: int) -> SuggestSummary | None:
    """One full measurement pass over the eval corpus; returns summary metrics (us)."""
    corpus = _load_corpus()
    if not corpus:
        return None
    score_s: list[float] = []
    suggest_s: list[float] = []
    by_kind: dict[str, list[float]] = defaultdict(list)
    for _case_id, kind, funcdef in corpus:
        breakdown = get_cognitive_complexity_breakdown(funcdef)
        score = partial(get_cognitive_complexity_breakdown, funcdef)
        score_s.append(_per_call(score, repeats, runs, warmup))
        s = _per_call(partial(suggest_refactors, funcdef, breakdown), repeats, runs, warmup)
        suggest_s.append(s)
        by_kind[kind].append(s)
    score_med = statistics.median(score_s)
    suggest_med = statistics.median(suggest_s)
    return {
        "corpus_n": len(corpus),
        "score_median_us": score_med * 1e6,
        "suggest_median_us": suggest_med * 1e6,
        "suggest_p95_us": percentile(suggest_s, 95) * 1e6,
        "suggest_p99_us": percentile(suggest_s, 99) * 1e6,
        "suggest_max_us": max(suggest_s) * 1e6,
        "full_pass_us": sum(suggest_s) * 1e6,
        "overhead_ratio": suggest_med / score_med if score_med else 0.0,
        "by_kind_median_us": {k: statistics.median(v) * 1e6 for k, v in sorted(by_kind.items())},
    }


def _git_commit() -> str:
    try:
        out = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"], capture_output=True, text=True, timeout=5
        )
        return out.stdout.strip() or "unknown"
    except (OSError, subprocess.SubprocessError):
        return "unknown"


def _append_log(path: Path, summary: SuggestSummary, repeats: int, runs: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    entry = {
        "ts": datetime.now().isoformat(timespec="seconds"),
        "commit": _git_commit(),
        "repeats": repeats,
        "runs": runs,
        **summary,
    }
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(entry) + "\n")


def _stat_line(label: str, values: list[float], unit: str) -> None:
    mean = statistics.mean(values)
    sd = statistics.stdev(values) if len(values) > 1 else 0.0
    cv = (sd / mean * 100) if mean else 0.0
    print(
        f"  {label:16s} mean {mean:8.2f}{unit}  stdev {sd:7.3f}{unit}  "
        f"min {min(values):8.2f}{unit}  max {max(values):8.2f}{unit}  CV {cv:4.1f}%"
    )


def run_suggest(repeats: int, runs: int, warmup: int, trials: int, log_path: Path) -> None:
    """Run the suggest measurement ``trials`` times; log each and report stability."""
    summaries: list[SuggestSummary] = []
    for t in range(trials):
        summary = measure_suggest(repeats, runs, warmup)
        if summary is None:
            print("no eval corpus found under evals/refactors/ — nothing to benchmark")
            return
        summaries.append(summary)
        _append_log(log_path, summary, repeats, runs)
        print(
            f"  trial {t + 1:>2}/{trials}: ratio {summary['overhead_ratio']:.2f}x  "
            f"suggest median {summary['suggest_median_us']:.1f}us  "
            f"p95 {summary['suggest_p95_us']:.1f}us"
        )

    last = summaries[-1]
    print(
        f"\nSuggestion overhead over {last['corpus_n']} eval functions, "
        f"{trials} trial(s) ({repeats} calls/run x {runs}):"
    )
    _stat_line("overhead ratio", [s["overhead_ratio"] for s in summaries], "x")
    _stat_line("suggest median", [s["suggest_median_us"] for s in summaries], "us")
    _stat_line("suggest p95", [s["suggest_p95_us"] for s in summaries], "us")
    print("\n  per kind (median per fn, last trial):")
    for kind, value in last["by_kind_median_us"].items():
        print(f"    {kind:18s}  {value:8.2f}us")
    print(f"\n  appended {trials} trial(s) to {log_path}")


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--mode", choices=("compute", "sweep", "suggest"), default="compute")
    parser.add_argument("-n", "--runs", type=int, default=20)
    parser.add_argument("--warmup", type=int, default=1, help="discarded warmup runs")
    parser.add_argument("--depth", type=int, default=15, help="nesting depth")
    parser.add_argument("--breadth", type=int, default=200, help="compute mode: statements")
    parser.add_argument("--repeats", type=int, default=1000, help="scorings timed per run")
    parser.add_argument(
        "--trials", type=int, default=1, help="suggest mode: full measurement passes (stability)"
    )
    parser.add_argument(
        "--log",
        default="benchmarks/results/suggest.jsonl",
        help="suggest mode: JSONL file to append each trial's summary to",
    )
    args = parser.parse_args(argv)

    if args.mode == "sweep":
        run_sweep([50, 100, 200, 400, 800], args.depth, args.repeats, args.runs, args.warmup)
        return

    if args.mode == "suggest":
        run_suggest(args.repeats, args.runs, args.warmup, args.trials, Path(args.log))
        return

    funcdef = _build_large_function(args.depth, args.breadth)
    summarize(
        f"Compute ({args.repeats} scorings/run, depth={args.depth}, breadth={args.breadth})",
        _sample(funcdef, args.repeats, args.runs, args.warmup),
    )


if __name__ == "__main__":
    main()
