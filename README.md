# cococo

**co**de **co**gnitive **co**mplexity — a library and CLI to compute the
cognitive complexity of Python functions.

This is a fork of [Melevir/cognitive_complexity](https://github.com/Melevir/cognitive_complexity)
(MIT) that adds a command-line tool, modern-Python construct support, and
Python 3.10+ packaging. The importable package and distribution are still
named `cognitive_complexity`; the repo and CLI are `cococo`.

## Installation

Not published to PyPI — install from the repository:

```bash
pip install git+https://github.com/qwhex/cococo
# or, with uv:
uv pip install git+https://github.com/qwhex/cococo
```

This installs the `cococo` command and the importable `cognitive_complexity`
package.

## Usage

### Command line

```bash
cococo src/                  # score every function, worst first
cococo src/ --max 20         # gate: exit non-zero if any function exceeds 20
cococo a.py b.py --min 10    # only show functions scoring >= 10
```

`cococo` scores every module-level function and method; nested functions are
folded into their enclosing function's score.

### Library

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
- the decorator/closure heuristic is tightened to require the inner function to
  be returned *by name*.
- a **`cococo` command-line interface**.
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

## Development

```bash
pip install -r requirements_dev.txt
just install-hooks  # pre-push runs `just check` (the same gate as CI)
just check          # format-check + lint + type-check + complexity + tests + readme lint
just test           # tests with coverage
just bench          # performance benchmark
```

`just check` is the single gate — CI runs the exact same recipe.

## License

MIT. See [LICENSE](LICENSE). Original work © Ilya Lebedev and contributors.
