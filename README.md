# cococo

**co**de **co**gnitive **co**mplexity — a library and CLI to compute the
cognitive complexity of Python functions.

This is a fork of [Melevir/cognitive_complexity](https://github.com/Melevir/cognitive_complexity)
(MIT) that adds a command-line tool, modern-Python construct support, and
Python 3.10+ packaging. Three names differ on purpose: install **`codecoco`**,
import **`cognitive_complexity`**, run **`cococo`** (`cognitive_complexity` and
`cococo` were both already taken on PyPI, so the distribution is published as
`codecoco`).

## Installation

```bash
pip install codecoco
# or, with uv:
uv pip install codecoco
```

This installs the `cococo` command and the importable `cognitive_complexity`
package. To install the unreleased tip from the repository instead:

```bash
pip install git+https://github.com/qwhex/cococo
```

## Usage

### Command line

```bash
cococo src/                  # score worst-first, with refactor suggestions inline
cococo src/ --max 20         # gate: exit non-zero if any function exceeds 20
cococo a.py b.py --min 10    # only list functions scoring >= 10
cococo src/ --suggest-min 10 # only attach suggestions to functions scoring >= 10
cococo src/ --max 20 --no-suggest  # gate only: skip suggestions (faster for CI)
cococo src/ --max 20 --json  # machine-readable report for a pipeline
cococo src/ --fix            # apply safe guard-clause rewrites in place
cococo src/ --nested fold    # pre-2.0.0 scoring: fold nested defs into the parent
cococo src/ --max 20 --baseline .cococo.json  # ratchet: fail only on regressions
```

`cococo` scores every function, method, and **named nested function** as its own
unit — a nested `def` is reported on its own row with a qualified name
(`outer.<locals>.inner`, `Klass.method.<locals>.helper`), scored from nesting
level 0, not folded into the function that encloses it. This keeps factory and
registry shapes (FastAPI/Flask app factories, decorator factories, dispatch
tables of closures) honest: the trivial outer function scores low and each inner
handler is judged on its own merits. Lambdas, being anonymous, still fold into
their enclosing function. See
[docs/nested-function-scoring.md](docs/nested-function-scoring.md) for the
rationale.

For gates pinned to pre-2.0.0 numbers, `--nested=fold` restores the old model
(nested defs fold into the enclosing function; a decorator/closure factory is
scored by its inner function) as a migration aid; the same is available in the
library as `get_cognitive_complexity(funcdef, fold_nested=True)`. See
[CHANGELOG.md](CHANGELOG.md).

### Refactor suggestions

Beyond reporting a score, cococo points at what to *do* about a complex
function: the default listing prints concrete, mechanical refactors inline —
each with the lines it touches and an estimated complexity drop:

```text
  14  src/load.py:42  load
    - Extract this block into a helper function (lines 50-61, ~-7 -> 7)
    - Flatten nested block with a guard clause (lines 45-61, ~-3 -> 11) [--fix]
```

`--suggest-min N` attaches suggestions only to functions scoring at least `N`
(it defaults to `--min`), to focus the output on the worst offenders. Under a
`--max` gate the offending functions are reported on stderr with the same
suggestions instead, so a failing CI step says exactly what to fix. `--no-suggest`
skips suggestion computation entirely — a faster path for a CI gate that only
needs the pass/fail.

Suggestions tagged `[--fix]` can be applied automatically. `--fix` rewrites only
transforms it can prove keep behavior identical (an `if` with no `else` that is
the last statement of a function or loop body becomes an early
`return`/`continue` guard, de-indenting its body); anything else is left
untouched, and comments/formatting in the moved body are preserved.

### Adopting the gate incrementally

No real codebase passes a strict ceiling on day one, so the `--max` gate has two
ways to grandfather existing offenders rather than be all-or-nothing:

- **Per-function:** put `# cococo: ignore` on a function's `def` line to exclude
  that one function from the gate (the listing still shows it). cococo warns when
  an ignore is no longer needed (the function is back under the ceiling), so the
  directives don't rot silently.

  ```python
  def legacy_handler(req):  # cococo: ignore
      ...
  ```

- **Whole codebase:** `--baseline FILE` (requires `--max`) records every current
  score the first time it runs, then on later runs fails only on **regressions** —
  a function rising above its recorded score, or new code over `--max`. This lets
  a team adopt the gate against a dirty tree in one commit and ratchet down from
  there. Commit the baseline file; delete it to re-baseline.

### Exit codes

In gate mode (`--max`), the exit code distinguishes the outcomes a CI step cares
about:

- **0** — all functions within the ceiling (or, without `--max`, a successful
  listing).
- **1** — one or more functions exceed the ceiling (offenders printed with
  suggestions).
- **2** — the gate could not be trusted: no functions were scanned (a typo'd or
  empty path), a file was skipped (unreadable, unparseable, or too deeply nested
  to score), or a `--fix` write failed. A `2` means "fix the setup", not "code is
  too complex".

### JSON output

`--json` emits the same scores, per-construct breakdowns, and suggestions as a
single JSON document on stdout (exit code still gates on `--max`), so cococo
drops into a pipeline:

```bash
cococo src/ --max 20 --json | jq '.functions[] | select(.over)'
```

### Library

Score every function under a path (no CLI required):

```python
from cognitive_complexity.discovery import scored_functions

for f in scored_functions(["src/"]):
    print(f.qualname, f.score)
```

`scored_functions` returns a list of `ScoredFunction` named tuples with
`.score`, `.qualname`, `.path`, `.lineno`, `.funcdef`, `.breakdown`, and
`.ignored` fields.

The suggestion engine is importable too:

```python
from cognitive_complexity.api import get_cognitive_complexity_breakdown
from cognitive_complexity.refactor import suggest_refactors

breakdown = get_cognitive_complexity_breakdown(funcdef)
for s in suggest_refactors(funcdef, breakdown):
    print(s.title, s.estimated_reduction)
```

The low-level AST API:

```python
>>> import ast
>>> funcdef = ast.parse("""
... def f(a):
...     return a * f(a - 1)  # +1 for recursion
... """).body[0]

>>> from cognitive_complexity.api import get_cognitive_complexity
>>> get_cognitive_complexity(funcdef)
1
```

## What's different from upstream

This fork diverges from `Melevir/cognitive_complexity` 1.3.0:

- **`async for`** is counted as a loop (upstream scored it 0).
- **`match`/`case`** is counted as a single branching structure plus a nesting
  level (upstream did not handle it).
- **comprehension `if` filters** each count as a decision point.
- **method recursion** (`self.method(...)` / `cls.method(...)`) is detected, not
  only bare-name recursion.
- **named nested functions are scored as their own units** (reported as
  `outer.<locals>.inner`), not folded into the enclosing function; lambdas still
  fold. This removes the per-containment nesting surcharge on factory/registry
  code and the old `is_decorator` special case — both still available via
  `--nested=fold` for pre-2.0.0 compatibility. See
  [docs/nested-function-scoring.md](docs/nested-function-scoring.md).
- a **`cococo` command-line interface**, with **heuristic refactor suggestions**
  on a failing gate, a **`--json`** report for pipelines, and a **`--fix`** flag
  that applies provably safe guard-clause rewrites.
- **Python 3.10+** only; type hints and packaging modernized.

The core control-flow scoring (Campbell's rules) is unchanged — it is the
empirically validated part of the metric.

## What is cognitive complexity

For a synthesis of the research and industry thinking on what makes code hard to
understand — and how cognitive complexity fits in — see
[docs/cognitive-complexity-of-code.md](docs/cognitive-complexity-of-code.md).

Here are some readings about cognitive complexity:

- [Cognitive Complexity, Because Testability != Understandability](https://blog.sonarsource.com/cognitive-complexity-because-testability-understandability);
- [Cognitive Complexity: A new way of measuring understandability](https://www.sonarsource.com/docs/CognitiveComplexity.pdf),
  white paper by G. Ann Campbell;
- [Cognitive Complexity: the New Guide to Refactoring for Maintainable Code](https://www.youtube.com/watch?v=5C6AGTlKSjY);
- [Cognitive Complexity](https://docs.codeclimate.com/docs/cognitive-complexity)
  from CodeClimate docs;
- [Is Your Code Readable By Humans? Cognitive Complexity Tells You](https://www.tomasvotruba.cz/blog/2018/05/21/is-your-code-readable-by-humans-cognitive-complexity-tells-you/).

## Realization details

This is not a precise realization of the original algorithm proposed by
[G. Ann Campbell](https://github.com/ganncamp), but it gives rather similar
results. The algorithm gives complexity points for breaking control flow,
nesting, recursion, and stacked logical operations.

**Known limitation:** only *direct* recursion is detected (a function calling
itself by name, or via `self`/`cls`). Indirect/mutual recursion — `a()` calls
`b()` calls `a()` — is not counted, since detecting it needs a whole-program
call graph rather than the single-function AST this tool works from.

## Development

To develop `cococo`, first set up and activate a virtual environment so the toolchain (`python`, `pytest`, etc.) is available on your PATH:

```bash
# With standard pip/venv:
python -m venv .venv
source .venv/bin/activate
pip install -r requirements_dev.txt

# Or with uv:
uv venv
uv pip install -r requirements_dev.txt
```

Once the environment is active (or by prefixing commands with `uv run`, e.g., `uv run just test`), you can use the `just` recipes:

```bash
just install-hooks  # pre-push runs `just check` (the same gate as CI)
just check          # format-check + lint + type-check + complexity + tests + readme lint
just test           # tests with coverage
just bench          # performance benchmark
```

`just check` is the single gate — CI runs the exact same recipe.

## License

MIT. See [LICENSE](LICENSE). Original work © Ilya Lebedev and contributors.
