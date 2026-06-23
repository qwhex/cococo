# Releasing

cococo is published to PyPI as **`codecoco`** (the import name stays
`cognitive_complexity`, the CLI stays `cococo`). Releases are driven by a pushed
`vX.Y.Z` git tag: `just release` commits the bump, tags, and pushes, and the
[release workflow](.github/workflows/release.yml) builds and publishes via PyPI
trusted publishing (OIDC — no stored tokens) and cuts a GitHub Release.

## Versioning rule

Standard [SemVer](https://semver.org/), with one project-specific rule: the
**reported complexity score is the public contract**. *Any* change that moves a
score — even a bug fix — is a **major** release, because it can flip a downstream
`--max` gate red or green. Output-only changes (e.g. `--fix` formatting) are
minor/patch.

## Steps

1. On `master` with all feature work committed, confirm `just check` is green
   (format, lint, mypy strict, complexity, tests at 100% coverage).
2. **Draft the changelog** for the range since the last release: `just changelog-draft`
   (uses the last tag → HEAD). For the first release, which has no tag, pass an
   explicit base ref: `just changelog-draft <commit>`. It prints the
   Added/Changed/Fixed bullets and a suggested semver `bump`.
   - Outside contributors without that tooling: review the range by hand
     (`git log`, `git diff`) and write the bullets.
3. Pick the version from that bump, **applying the score-as-contract rule above**
   — the suggested bump is advisory and does not know that rule, so upgrade to a
   major yourself if any score moves.
4. Prepend a `## [X.Y.Z] - YYYY-MM-DD` section to `CHANGELOG.md`
   ([Keep a Changelog](https://keepachangelog.com/) style) with those bullets.
5. Bump `__version__` in `cognitive_complexity/__init__.py` (read by `setup.py`).
6. `just release` — guards (master; only the version + changelog uncommitted;
   `just check` green; CHANGELOG section present; tag unused), commits those two
   files as `release X.Y.Z`, tags `vX.Y.Z`, and pushes. The push triggers the
   workflow, which publishes to PyPI and cuts the GitHub Release.
7. Verify: `pip install codecoco==X.Y.Z` in a clean venv; `import cognitive_complexity`
   and `cococo --help` both work.

### One-time publishing setup

Trusted publishing needs **no secrets**. Configure once:

- **PyPI** → Account → Publishing → add a pending publisher for project
  `codecoco`, owner `qwhex`, repo `cococo`, workflow `release.yml`, environment
  `pypi`.
- **GitHub** → repo Settings → Environments → create an environment named `pypi`
  (the name must match). Optionally add a protection rule.

### Manual fallback

If CI is unavailable: `just publish` (builds, `twine check`, then `twine upload
dist/*`) with a PyPI API token in `~/.pypirc`.
