# Changelog

All notable changes to cococo are documented here. The format is based on
[Keep a Changelog](https://keepachangelog.com/), and the project follows
[Semantic Versioning](https://semver.org/) with one project-specific rule: the
**reported complexity score is the public contract**, so *any* change that moves
a score — even a bug fix — is a major release, because it can flip a downstream
`--max` gate red or green.

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
