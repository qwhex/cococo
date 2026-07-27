# Changelog

All notable changes to cococo are documented here. The format is based on
[Keep a Changelog](https://keepachangelog.com/), and the project follows
[Semantic Versioning](https://semver.org/) with one project-specific rule: the
**reported complexity score is the public contract**, so *any* change that moves
a score — even a bug fix — is a major release, because it can flip a downstream
`--max` gate red or green.

## [4.0.0] - 2026-07-27

Bugfix release from a full-codebase audit; major per the score-as-contract rule
because the boolean-operand fix moves scores.

### Changed

- **Constructs nested inside boolean operands now score.** The scorer previously
  stopped walking at a `BoolOp`, so ternaries, comprehensions, lambdas, and
  recursive calls inside `and`/`or` operands scored 0 — e.g.
  `a and (b if c else d)` was 1, now 2 — and unit mode missed recursion in
  operands (`x and f(x-1)`) that fold mode counted. A boolean expression tree
  still counts once, at its own nesting level, so plain chains like
  `a and b and c` are unchanged (`f663262`).
- Breakdown attribution: `for`/`while` `else` gets its own labeled `else` entry
  instead of being folded into the loop's points, and `else` line numbers now
  point at the line just after the branch above rather than the first body
  statement. Totals are unchanged; visible in `--explain` and `--json`
  (`f663262`).
- Directory scans prune hidden directories and `venv`/`site-packages`/
  `node_modules`/`build`/`dist`/`__pycache__`/`*.egg-info` by default — `cococo
  . --fix` no longer rewrites your `.venv` (`f1d0c81`).
- `--explain` setup failures (missing file, unknown qualname, unparseable
  source) exit 2, not 1 — exit 1 now always means "over the ceiling". Scripts
  branching on the old code must update (`f1d0c81`).
- Detector reduction estimates are derived from the score breakdown instead of
  arm counts: a flat `match` is worth its actual +1 (now below the suggestion
  noise floor rather than over-stated ~3x), `elif` ladders and sequential
  dispatch runs report the points they really remove, and overlapping
  suggestions are suppressed across kinds so reductions no longer sum past the
  function total (`c7011e4`).
- The `[--fix]` badge (and `autofixable` in `--json`) appears only on guards the
  rewriter will genuinely apply — mid-block guards keep the advice, lose the
  false promise (`c7011e4`).

### Added

- `--exclude PATTERN` (repeatable, fnmatch on name or path) for directory scans
  and `--fix` (`f1d0c81`).
- Encoding and newline fidelity: sources are read via `tokenize.detect_encoding`
  (PEP 263 declarations and UTF-8 BOM now score instead of being skipped) and
  written back in their own codec; CRLF files stay CRLF through `--fix`
  (`f1d0c81`).
- `--fix` safety: skips symlinked files (preserving the link) and files modified
  between read and write, names each skip on stderr, and explains
  tab-indentation refusals instead of silently reporting "applied 0"
  (`f1d0c81`).
- Eval harness rigor: detection is asserted by default (opt-out requires
  `forbidden_kind` + notes), `known_gap = true` produces a visible XFAIL that
  fails once the gap closes, `silent` is a real composable assertion, and a new
  always-on `fix_claim` axis fails any case whose suggestions over-claim
  autofixability (`aff0b93`).
- Wider gates: mypy strict, the complexity ceiling, and the 100% coverage floor
  now also cover `evals/`; `benchmarks/` is held to ruff + mypy strict + the
  ceiling as a declared exemption from coverage (`aff0b93`).

### Fixed

- Fold-mode scoring of decorator factories no longer changes when the factory
  gains a docstring (`f663262`).
- The `--baseline` ratchet file is written atomically and is never created from
  a run whose scan was untrusted (skipped files or failed `--fix` writes)
  (`f1d0c81`).
- Recursive functions are no longer advised to extract their entire body by the
  decompose-by-span fallback (`c7011e4`).
- `just check` warns loudly on a skipped README lint and `just release` refuses
  to run without `mdl`, so a green local gate can no longer silently be weaker
  than CI (`aff0b93`).

## [3.7.0] - 2026-06-24

### Added

- Four new refactor-suggestion detectors, all output-only (no complexity score
  changes): `merge_nested_if` collapses `if a:` / `if b:` into `if a and b:`
  (`52202b3`); `flatten_else_after_return` drops a redundant `else` after a
  terminal `if` body (`15ebb2a`); `sequential_dispatch` turns an
  `if x == k: return …` ladder into a dispatch table (`60e3ea6`); and a
  `decompose_by_span` fallback points at the heaviest span to split when no named
  refactor matches — replacing the old "no mechanical refactor found" dead end
  (`b7e9937`).
- `--no-suggest` flag: skip refactor-suggestion computation entirely, a faster path
  for CI gates that only need the pass/fail (`fe795b2`).
- A refactor-suggestion eval set under `evals/refactors/` (gated by the test suite)
  plus a `suggest` benchmark mode (`python -m benchmarks.run_benchmark --mode
  suggest`) that tracks the suggestion-vs-scoring overhead ratio — the regression
  guards for the suggestion engine (`6b3452c`, `b9e0735`).

### Changed

- The refactor-suggestion engine moved from a single `refactor.py` into a
  `detectors/` package: one self-contained module per kind plus a shared toolkit,
  with control-flow regions computed once per function so adding detectors no
  longer re-walks the AST. **`Suggestion` and `suggest_refactors` now import from
  `cognitive_complexity.detectors`** (previously `cognitive_complexity.refactor`)
  (`6d925eb`, `1bd6337`).

### Fixed

- Coupling analysis now counts an augmented assignment (`x += 1`) as both a read
  and a write, so `extract_helper` is correctly suppressed for regions that carry
  an accumulator across the boundary (`e5075b4`).

## [3.6.0] - 2026-06-23

### Added

- Refactor suggestions now appear **by default** in the plain listing, inline on
  stdout under each function — so the actionable advice is the primary output, not
  a gate-only diagnostic. New `--suggest-min N` flag attaches suggestions only to
  functions scoring at least `N` (defaults to `--min`), applied to both the text
  listing and the `--json` report. Listing mode stays quiet when no refactor
  applies (the "no mechanical refactor found" line remains gate-only). Output
  only; no complexity score is affected. (`856a64a`)

### Changed

- `just release` gained a dry-run mode (`just release dry`) that runs the guards
  and prints the commit/tag/push plan without committing, tagging, or pushing.
  (`fb6a054`)

## [3.5.1] - 2026-06-23

### Added

- Published to PyPI as `codecoco` (`pip install codecoco`). The import name
  (`cognitive_complexity`) and CLI (`cococo`) are unchanged. Releases are now cut
  with `just release`, which tags `vX.Y.Z` and triggers a GitHub Actions workflow
  that builds and publishes via PyPI trusted publishing (OIDC) and creates a
  GitHub Release. Added `just changelog-draft`/`build`/`check-dist`/`publish`
  recipes and `build`/`twine` dev dependencies. No library behavior change; no
  complexity score is affected.

## [3.5.0] - 2026-06-23

### Fixed

- `--fix` now emits clean inverted conditions instead of blindly wrapping every
  guard condition in `not (...)`. Redundant parentheses around atomic conditions
  are dropped (`not (isinstance(x, list))` → `not isinstance(x, list)`), and
  membership/identity comparisons are negated through their operator
  (`not (k in block)` → `k not in block`; `not (k is x)` → `k is not x`) so the
  output no longer trips `ruff`/`pycodestyle` `E713`/`E714` or needs a follow-up
  `ruff format` pass. Ordering/equality comparisons (`<`, `==`, …), boolean
  `and`/`or`, and chained comparisons keep the safe `not (...)` wrapper, since
  flipping them is not always behavior-preserving (e.g. `not (x < y)` differs
  from `x >= y` for `NaN`). Output only; complexity scores are unchanged.

## [3.4.1] - 2026-06-17

### Fixed

- Restored the 100% test-coverage gate, which the 3.4.0 refactor-suggestion work
  had dropped to 98%: added tests covering attribute-mutation counting,
  mixed-subject and constant-on-left equality chains, and `match` guard/OR
  patterns in the suggestion heuristics, plus baseline write-failure and
  outside-root key fallback in the CLI. Removed an unreachable defensive branch
  in the coupling analysis. No behavior change.

## [3.4.0] - 2026-06-17

### Added

- Documented `--nested` and `--baseline` CLI options, exit codes, and the
  `# cococo: ignore` directive in the README. (`dc48f39`)
- Validation and error handling for baseline files, with exit code 2 for
  untrusted baselines. (`e81df65`)
- Coupling analysis in refactor suggestions, so extractions with high
  parameter/return overhead are no longer suggested. (`7a1514e`)

### Changed

- Refactor suggestions now suppress unsafe patterns: predicate extraction for
  walrus operators, dispatcher suggestions for ordered comparisons or
  side-effectful conditions, and helper extraction for regions with control-flow
  statements or excessive attribute mutations. (`ddf31ab`)
- Baseline function keys now use relative paths when possible, for consistency
  across relative and absolute invocations. (`e81df65`)
- Baseline creation is skipped when the scan skips files or finds no functions,
  avoiding partial baselines. (`efa6928`)
- Reduced cognitive complexity of the refactor-analysis internals (no behavior
  change). (`3766ace`)

### Fixed

- Data clump refactor suggestions now analyze variable coupling across region
  boundaries instead of over-suggesting. (`7a1514e`)
- Structural match pattern detection no longer suggests dispatcher refactoring
  for patterns with guards or complex destructuring. (`7a1514e`)

## [3.3.0] - 2026-06-11

### Added

- `cognitive_complexity.discovery` module exposing `scored_functions(paths)` (plus
  `iter_python_files`, `find_function`, `parse_target`) so library consumers can
  discover and score functions from files/directories without importing the CLI
  presentation layer.

### Changed

- Function-discovery logic moved out of `cognitive_complexity.cli` into the new
  `discovery` module (the CLI re-imports it; no behavior change). The redundant
  `cli.score_paths` accessor was removed — use `discovery.scored_functions(...)`
  and read `ScoredFunction` attributes (`.score`, `.qualname`, …).

## [3.2.0] - 2026-06-11

### Added

- Suppression for the `--max` gate, so it can be adopted incrementally instead of
  being all-or-nothing:
  - `# cococo: ignore` on a function's `def` line excludes that function from the
    gate; an "unused ignore" warning fires when the function is back within the
    ceiling.
  - `--baseline FILE` (requires `--max`) records current scores on first run, then
    fails only on regressions above the recorded score (new code is still gated at
    `--max`).
  - JSON `over`/`exceeded` honor both, so the report agrees with the exit code.

## [3.1.0] - 2026-06-11

### Added

- `--json` now reports `files_scanned` and `skipped` (`[{path, reason}]`) so a
  pipeline can distinguish a complete scan from a partial one — previously a scan
  that silently skipped unparseable files looked identical to a clean tree.

## [3.0.0] - 2026-06-11

This batch contains one score-changing fix (the recursion correction below), so
it is a **major** release. The non-score-changing items (gate behavior, `--fix`
hardening) are bundled here rather than shipped as a separate `2.x` first.

### Breaking

- Recursion is no longer counted on the enclosing function when its own name is
  called only from inside a nested `def`. Under the unit model that call belongs
  to the nested function's score, not the enclosing one, so factory/closure
  functions with this shape drop by 1 point. Pin the previous numbers with
  `--nested=fold` if a gate depends on them.

### Added

- `--nested=fold|unit` flag (default `unit`). `fold` restores the pre-2.0.0
  model: named nested functions fold into their enclosing function's score (one
  nesting level deeper) and a decorator/closure factory is scored by its inner
  function. Available programmatically as
  `get_cognitive_complexity(funcdef, fold_nested=True)`. Intended as a migration
  aid for gates pinned to pre-2.0.0 numbers, not a permanent second metric.
- The `--max` gate now fails loud (exit code `2`, distinct from `1` for "found
  offenders") when a scan matches zero functions — a typo'd or renamed path can
  no longer silently turn the gate into a no-op.
- The `--max` gate now fails (exit code `2`) when any file is skipped because it
  could not be read, parsed, or scored, with a per-file diagnostic on stderr.
  `--json` always emits a valid (possibly empty) report so pipelines keep
  working.

### Fixed

- `--fix` no longer corrupts multi-line string / f-string literals via a blind
  line-by-line dedent; guards whose body contains such a literal are left
  untouched.
- `--fix` writes are atomic (temp file in the same directory, `fsync`, then
  `os.replace`) and preserve the file's mode, so an interrupted run can no
  longer truncate or half-write a source file.
- `--fix` reports per-file outcomes and exits non-zero (`2`) when any write
  fails, instead of printing success and exiting `0` regardless. One bad file no
  longer aborts the whole batch.
- A pathologically deep AST (a long subscript chain, a huge `elif` ladder) now
  skips that one file (loud, gate-failing) instead of aborting the entire scan
  with an uncaught `RecursionError`.

## [2.0.0] - 2026-06-07

### Breaking

- Named nested functions are scored as their own independent units (from nesting
  level 0) rather than folding into the enclosing function. This changed the
  reported numbers for factory/closure-heavy code and removed the old
  `is_decorator` special case from the default path. See
  [docs/nested-function-scoring.md](docs/nested-function-scoring.md). Use
  `--nested=fold` (added in the next release) for the previous behavior.

### Added

- A `cococo` command-line interface; heuristic refactor suggestions on a failing
  gate; a `--json` report; and a `--fix` flag that applies provably safe
  guard-clause rewrites.
- Support for `async for`, `match`/`case`, comprehension `if` filters, and
  method recursion (`self`/`cls`) in scoring; Python 3.10+ packaging.
