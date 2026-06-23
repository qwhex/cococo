# Releasing

cococo is **not published to PyPI** — consumers install from the repository, so a
release is just a version bump and a changelog entry in a commit. No upload step.

## Versioning rule

Standard [SemVer](https://semver.org/), with one project-specific rule: the
**reported complexity score is the public contract**. *Any* change that moves a
score — even a bug fix — is a **major** release, because it can flip a downstream
`--max` gate red or green. Output-only changes (e.g. `--fix` formatting) are
minor/patch.

## Steps

1. On `master` with a clean tree, confirm `just check` is green (format, lint,
   mypy strict, complexity, tests at 100% coverage).
2. **Draft the changelog from the commit range** since the last release.
   - Maintainers: use the `changelog` tool (scripts MCP) over
     `<last-release>..HEAD` — it produces the Added/Changed/Fixed bullets and a
     suggested semver bump.
   - Outside contributors without that tooling: review the range manually
     (`git log <last-release>..HEAD`, `git diff <last-release>..HEAD`) and write
     the bullets by hand.
3. Pick the version from that bump, applying the score-as-contract rule above.
4. Bump `__version__` in `cognitive_complexity/__init__.py` (read by `setup.py`).
5. Prepend a `## [X.Y.Z] - YYYY-MM-DD` section to `CHANGELOG.md`
   ([Keep a Changelog](https://keepachangelog.com/) style) with the bullets from
   step 2.
6. Commit the changed files. The message can be anything descriptive — the
   version lives in `__init__.py` and `CHANGELOG.md`, not the commit subject.
