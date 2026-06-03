#!/usr/bin/env python3
"""Performance benchmark for the cognitive-complexity library.

Two modes:

* ``suite`` (default) -- run the full pytest suite N times in fresh
  subprocesses and report the wall-clock distribution. This is the
  "run the test suite N times and do stats on them" regression guard:
  a change that slows the suite shows up as a shift in the distribution.
  Note that pytest start-up/collection dominates this number, so it is a
  coarse signal.

* ``compute`` -- time only ``get_cognitive_complexity`` over a large
  synthetic function, in-process. This isolates the algorithm itself and
  is the sensitive guard against quadratic blow-ups or per-node overhead.

Usage::

    python benchmarks/run_benchmark.py                  # 20 suite runs
    python benchmarks/run_benchmark.py -n 50
    python benchmarks/run_benchmark.py --mode compute -n 200
    python benchmarks/run_benchmark.py -- -k try        # extra pytest args
"""
from __future__ import annotations

import argparse
import ast
import statistics
import subprocess
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent


def run_suite_once(pytest_args: list[str]) -> float:
    """Run the full suite once in a subprocess; return wall-clock seconds."""
    cmd = [
        sys.executable, "-m", "pytest", "tests/",
        "-q", "-p", "no:cacheprovider", *pytest_args,
    ]
    start = time.perf_counter()
    result = subprocess.run(cmd, cwd=REPO_ROOT, capture_output=True, text=True)
    elapsed = time.perf_counter() - start
    if result.returncode != 0:
        sys.stderr.write(result.stdout)
        sys.stderr.write(result.stderr)
        raise SystemExit(f"Test suite failed during benchmark (exit {result.returncode})")
    return elapsed


def _build_large_function(depth: int, breadth: int) -> ast.AST:
    """Generate a deeply nested + wide function for the compute benchmark."""
    lines = ["def big(a, b, c, d):"]
    indent = "    "
    for level in range(depth):
        pad = indent * (level + 1)
        lines.append(f"{pad}if a and b or c and d:  # nesting {level}")
    pad = indent * (depth + 1)
    lines.extend(f"{pad}x{i} = a if b else c" for i in range(breadth))
    return ast.parse("\n".join(lines)).body[0]


def run_compute_once(funcdef: ast.AST, repeats: int) -> float:
    """Time ``repeats`` scorings of one funcdef in-process; return seconds."""
    from cognitive_complexity.api import get_cognitive_complexity

    start = time.perf_counter()
    for _ in range(repeats):
        get_cognitive_complexity(funcdef)
    return time.perf_counter() - start


def percentile(values: list[float], pct: float) -> float:
    """Linear-interpolated percentile (pct in 0..100)."""
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    k = (len(ordered) - 1) * (pct / 100)
    lo = int(k)
    hi = min(lo + 1, len(ordered) - 1)
    return ordered[lo] + (ordered[hi] - ordered[lo]) * (k - lo)


def summarize(label: str, durations: list[float]) -> dict[str, float]:
    """Print and return mean/median/stdev/min/max/p95 for a sample (seconds)."""
    mean = statistics.mean(durations)
    stats = {
        "runs": len(durations),
        "mean": mean,
        "median": statistics.median(durations),
        "stdev": statistics.stdev(durations) if len(durations) > 1 else 0.0,
        "min": min(durations),
        "max": max(durations),
        "p95": percentile(durations, 95),
    }
    cv = (stats["stdev"] / mean * 100) if mean else 0.0
    print(f"\n{label} over {stats['runs']} runs:")
    print(f"  mean   {mean * 1000:9.3f} ms")
    print(f"  median {stats['median'] * 1000:9.3f} ms")
    print(f"  stdev  {stats['stdev'] * 1000:9.3f} ms  ({cv:.1f}% CV)")
    print(f"  min    {stats['min'] * 1000:9.3f} ms")
    print(f"  max    {stats['max'] * 1000:9.3f} ms")
    print(f"  p95    {stats['p95'] * 1000:9.3f} ms")
    return stats


def main(argv: list[str] | None = None) -> dict[str, float]:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--mode", choices=("suite", "compute"), default="suite")
    parser.add_argument("-n", "--runs", type=int, default=20)
    parser.add_argument("--warmup", type=int, default=1, help="discarded warmup runs")
    parser.add_argument("--depth", type=int, default=15, help="compute mode: nesting depth")
    parser.add_argument("--breadth", type=int, default=200, help="compute mode: statements")
    parser.add_argument("--repeats", type=int, default=1000, help="compute mode: scorings per run")
    parser.add_argument("pytest_args", nargs="*", help="extra args forwarded to pytest")
    args = parser.parse_args(argv)

    if args.mode == "suite":
        for _ in range(args.warmup):
            run_suite_once(args.pytest_args)
        durations = [run_suite_once(args.pytest_args) for _ in range(args.runs)]
        return summarize("Full-suite wall-clock", durations)

    funcdef = _build_large_function(args.depth, args.breadth)
    for _ in range(args.warmup):
        run_compute_once(funcdef, args.repeats)
    durations = [run_compute_once(funcdef, args.repeats) for _ in range(args.runs)]
    stats = summarize(
        f"Compute-only ({args.repeats} scorings/run, depth={args.depth}, breadth={args.breadth})",
        durations,
    )
    per_call_us = stats["mean"] / args.repeats * 1e6
    print(f"  -> {per_call_us:.2f} us per get_cognitive_complexity() call")
    return stats


if __name__ == "__main__":
    main()
