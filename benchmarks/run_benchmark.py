#!/usr/bin/env python3
"""Performance benchmark for the cognitive-complexity algorithm.

Times ``get_cognitive_complexity`` in-process over synthetic functions — this
isolates the algorithm (no pytest/interpreter startup noise) and is the
sensitive guard against per-node overhead and super-linear blow-ups.

Two modes:

* ``compute`` (default) -- repeatedly score one large function and report the
  wall-clock distribution (mean/median/stdev/p95) plus per-call time.

* ``sweep`` -- score functions of increasing size and report time *per AST
  node*. If the algorithm is linear that figure stays flat as the function
  grows; a rising per-node time signals an accidental O(n^2).

Run from the repo root so the package is importable::

    python -m benchmarks.run_benchmark                       # compute, default size
    python -m benchmarks.run_benchmark --depth 20 --breadth 400
    python -m benchmarks.run_benchmark --mode sweep
"""

from __future__ import annotations

import argparse
import ast
import statistics
import time

from cognitive_complexity.api import get_cognitive_complexity


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


def _count_nodes(funcdef: ast.AST) -> int:
    return sum(1 for _ in ast.walk(funcdef))


def run_compute_once(funcdef: ast.AST, repeats: int) -> float:
    """Time ``repeats`` scorings of one funcdef in-process; return seconds."""
    start = time.perf_counter()
    for _ in range(repeats):
        get_cognitive_complexity(funcdef)
    return time.perf_counter() - start


def _sample(funcdef: ast.AST, repeats: int, runs: int, warmup: int) -> list[float]:
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


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--mode", choices=("compute", "sweep"), default="compute")
    parser.add_argument("-n", "--runs", type=int, default=20)
    parser.add_argument("--warmup", type=int, default=1, help="discarded warmup runs")
    parser.add_argument("--depth", type=int, default=15, help="nesting depth")
    parser.add_argument("--breadth", type=int, default=200, help="compute mode: statements")
    parser.add_argument("--repeats", type=int, default=1000, help="scorings timed per run")
    args = parser.parse_args(argv)

    if args.mode == "sweep":
        run_sweep([50, 100, 200, 400, 800], args.depth, args.repeats, args.runs, args.warmup)
        return

    funcdef = _build_large_function(args.depth, args.breadth)
    summarize(
        f"Compute ({args.repeats} scorings/run, depth={args.depth}, breadth={args.breadth})",
        _sample(funcdef, args.repeats, args.runs, args.warmup),
    )


if __name__ == "__main__":
    main()
