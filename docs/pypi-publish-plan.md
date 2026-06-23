# Publishing `cococo` to PyPI — Full Plan

## Decision summary

- **Distribution name (PyPI):** `codecoco` — verified available. (`cognitive_complexity` is
  owned upstream; `cococo` is squatted, not ours.)
- **Import name (unchanged):** `cognitive_complexity` — **no rename, no source changes.**
  The parent `data_pipeline` dependency keeps working.
- **CLI command (unchanged):** `cococo`.
- **Publishing method:** PyPI **Trusted Publishing** (OIDC via GitHub Actions) — no API
  tokens stored anywhere. Manual `twine` upload kept as a documented fallback.
- **Release trigger:** pushing a git tag `vX.Y.Z`, wrapped in a single `just release`
  command with safety guards. The repo has **no tags yet** — adding the tag step is the
  missing link. **First published version: `3.5.1`** (the tooling changes themselves).
- **Changelog/version drafting:** `smcp changelog` (CLI) drafts the notes and *suggests* a
  semver bump; the human curates and may upgrade the bump to major per the score rule.
- **No secrets needed:** trusted publishing is OIDC — only a PyPI pending publisher + a
  GitHub `pypi` environment.

After this: `pip install codecoco`, then `import cognitive_complexity` and run `cococo`.
The three names differ on purpose (install `codecoco`, import `cognitive_complexity`,
command `cococo`) — documented in the README to avoid confusion.

---

## The three names

| Name kind | Value | Changes? |
|-----------|-------|----------|
| PyPI **dist** | `cognitive_complexity` → **`codecoco`** | ✅ one line in `setup.py` |
| Import package / dir | `cognitive_complexity` | ❌ no |
| CLI command | `cococo` | ❌ no |
| Version source | `cognitive_complexity/__init__.py` `__version__` | ❌ no |

No source files are touched. The only code-adjacent edits are packaging/release tooling.

---

## How a release works (the seamless flow)

The design keeps **human judgment** where it belongs and automates everything mechanical.

```
   (human)                          (one command)            (CI, automatic)
 decide version  ──►  write       ──►  just release   ──►  build sdist+wheel
 + changelog          CHANGELOG +       (guards, tag,        publish to PyPI
 prose                bump __version__  push tag)            create GH Release
```

### What stays manual (judgment — can't/shouldn't automate)

1. **Draft notes + bump suggestion** with the changelog generator:
   `smcp changelog v<last-tag> HEAD` (or `--json` for `{added, changed, fixed, bump}`).
   It returns grouped Added/Changed/Fixed bullets **and** a suggested semver `bump`
   (`patch`/`minor`/`major`). Exposed as `just changelog-draft`.
2. **Decide the final version.** Start from the suggested `bump`, but **override upward per
   `RELEASING.md`'s rule: any score-moving change is a major.** The generator is an LLM and
   does *not* know that rule — it judges by diff shape only (e.g. it suggests `minor` for an
   output-only `--fix`, which is right; but it would under-call a score-moving fix). The
   human has the final say on the number.
3. **Edit `CHANGELOG.md`** — paste/curate the drafted bullets into a new
   `## [X.Y.Z] - YYYY-MM-DD` section.
4. **Bump `__version__`** in `cognitive_complexity/__init__.py`.

(No manual commit step — `just release` owns the release commit; see below.)

### What `just release` automates (mechanical — error-prone if done by hand)

A new `just release` recipe that **owns the release commit** (so the commit message is
consistent by construction — no convention to remember; see "Release commit" below):

1. **Guards** — refuses to run unless:
   - on `master`,
   - the **only** uncommitted changes are `cognitive_complexity/__init__.py` and
     `CHANGELOG.md` (the bump + notes); everything else must already be committed,
   - `just check` is green (reuses the single gate),
   - the version in `__init__.py` has a **matching `## [X.Y.Z]` section in CHANGELOG.md**
     (the key drift-catcher — bumping one but not the other is the classic mistake),
   - tag `vX.Y.Z` does **not** already exist.
2. **Commits** — stages *only* those two files and commits them as `release X.Y.Z`.
3. **Tags** — creates an **annotated** tag `vX.Y.Z`, using that version's CHANGELOG section
   as the tag message.
4. **Pushes** the branch + tag (`git push origin master vX.Y.Z`).

Pushing the tag is what **triggers** the GitHub workflow.

### What CI does (automatic, on tag push)

`.github/workflows/release.yml`:

- builds the sdist + wheel,
- publishes to PyPI via trusted publishing (OIDC, no tokens),
- creates a **GitHub Release** whose notes are the extracted `## [X.Y.Z]` CHANGELOG section
  (so release notes stay single-sourced from the changelog you already maintain).

Net result locally: **`just changelog-draft` → curate notes + bump `__version__`, then
`just release`.** One command commits, tags, pushes; CI does the publishing.

### Release commit convention

Historically `3.4.0`/`3.4.1` used `release version X.Y.Z` commits, but `3.5.0`'s bump rode
inside a feature commit — the convention was already inconsistent. In a tag-driven flow the
**tag** is the release marker; **no tooling reads the commit message.** Rather than rely on
discipline, `just release` *owns* the commit and writes `release X.Y.Z` itself, so the
message is automatic, consistent, and the bump lands as its own isolated commit (feature
work never bundles the version bump). The old "remember to name the commit" rule is dropped.

---

## Implementation steps (in-repo)

### Step 1 — `setup.py`: distribution name only

- `name="cognitive_complexity"` → `name="codecoco"`.
- Append `codecoco` to the `keywords` string so PyPI search still surfaces it under
  "cognitive complexity".
- Nothing else changes (version reader, entry point, classifiers all stay).

### Step 2 — `requirements_dev.txt`

- Add `build` and `twine`.

### Step 3 — `justfile`

- `changelog-draft` → `smcp changelog $(git describe --tags --abbrev=0) HEAD` (the last tag
  to HEAD); prints grouped bullets + the suggested `bump`. For the very first release (no
  tags) pass an explicit base ref — see bootstrap.
- `build` → clean `dist/`, then `python -m build` (sdist + wheel).
- `check-dist` → `twine check dist/*` (validates metadata + README renders on PyPI).
- `release` → the guarded commit/tag/push recipe described above. Reads the version from
  `cognitive_complexity/__init__.py` (single source of truth — never hardcoded), verifies
  the CHANGELOG section exists, commits the bump as `release X.Y.Z`, tags `vX.Y.Z`, pushes.
- `publish` → `twine upload dist/*` (manual fallback only; CI is the primary path).

### Step 4 — `.github/workflows/release.yml`

- **Trigger:** `on: push: tags: ['v*']`.
- **Job `build`:** checkout → setup-python → `pip install build` → `python -m build` →
  upload `dist/` artifact.
- **Job `publish`:** `needs: build`, `environment: pypi`, `permissions: id-token: write`
  → download artifact → `pypa/gh-action-pypi-publish` (no credentials).
- **Job `github-release`:** extract the tag's CHANGELOG section → `gh release create`
  (or `softprops/action-gh-release`) with those notes.
- Leaves the existing `ci.yml` (`just check` gate) untouched.

### Step 5 — `RELEASING.md` (rewrite — see next section)

### Step 6 — `README.md`

- One-line install note: `pip install codecoco`, then `import cognitive_complexity` /
  run `cococo`.

---

## Updating `RELEASING.md`

The current file says cococo is **"not published to PyPI"** and "there is no publish/upload
step." That becomes false. Changes:

- **Keep verbatim:** the versioning rule (score-is-the-contract → major bump). It's good.
- **Replace** the opening paragraph: cococo is published to PyPI as `codecoco`; releases are
  driven by a pushed `vX.Y.Z` tag via `just release`.
- **Extend the Steps** with the release flow:
  1. On `master`, all feature work committed, `just check` green.
  2. `just changelog-draft` — get drafted bullets + suggested `bump`.
  3. Decide the version: apply the bump, **upgrading to major if the change moves a score**.
  4. Add the `CHANGELOG.md` `## [X.Y.Z] - DATE` section from the draft.
  5. Bump `__version__` in `cognitive_complexity/__init__.py`.
  6. **`just release`** — guards, commits the bump as `release X.Y.Z`, tags `vX.Y.Z`, pushes.
  7. CI publishes to PyPI and cuts the GitHub Release automatically.
  8. Verify: `pip install codecoco==X.Y.Z` in a clean venv; `import cognitive_complexity`
     + `cococo --help`.

---

## One-time setup (manual — needs your login)

> **No API token / GitHub secret is needed.** Trusted publishing uses OIDC: GitHub mints a
> short-lived identity per run and PyPI verifies it against the pending publisher. The only
> GitHub-side setup is an *environment* named `pypi` (not a secret). A `PYPI_API_TOKEN`
> secret is required *only* if you choose the older token method instead of OIDC.

**On PyPI** (<https://pypi.org> → **Account → Publishing → Add a pending publisher** —
works before the project exists; reserves `codecoco` on first publish):

- **PyPI project name:** `codecoco`
- **Owner:** `qwhex` (from the repo URL)
- **Repository name:** `cococo`
- **Workflow filename:** `release.yml`
- **Environment name:** `pypi`

**On GitHub** (repo → Settings → Environments): create an environment named **`pypi`**
(must match the value above). Optionally add protection rules (e.g. required reviewer) so a
publish can't fire unattended.

(Optional: rehearse on <https://test.pypi.org> first with a separate pending publisher.)

---

## First-release bootstrap

- The repo has **no tags**. `__version__` is `3.5.0` with a matching `CHANGELOG.md` section,
  but it was never tagged or published.
- **First published version = `3.5.1`** — these packaging/release-tooling changes are a
  patch. `3.5.0` stays as a prior (never-published) changelog entry; we do **not** tag it.
- Sequence:
  1. Land Steps 1–6 (the tooling changes) on `master`.
  2. Draft notes: since there's no prior tag, run
     `smcp changelog <release-3.4.1-commit> HEAD` (or the 3.5.0 feature commit) for the base
     — i.e. pass an explicit ref, not `git describe`. After v3.5.1 exists, every later
     release uses the previous tag automatically.
  3. Add a `## [3.5.1]` CHANGELOG section, bump `__version__` to `3.5.1`.
  4. `just release` → tags `v3.5.1`, pushes → CI's first publish reserves `codecoco` via the
     pending publisher.
- If you'd rather reserve the name immediately without CI, do one manual
  `just build && twine upload dist/*` with a temporary API token, then switch to OIDC for
  all later releases.

---

## Pre-flight checks before first publish

- [ ] `just check` green.
- [ ] `python -m build` produces `dist/codecoco-<ver>.tar.gz` + a `.whl`.
- [ ] `twine check dist/*` passes (README renders on PyPI).
- [ ] Wheel installs in a clean venv: `import cognitive_complexity` + `cococo --help` work.
- [ ] `__version__`, the CHANGELOG top section, and the tag all agree (the `release`
      recipe enforces this).

## Risks / notes

- **Name discoverability:** `codecoco` doesn't contain "cognitive complexity" — mitigated by
  `keywords` + `description` (already strong) and the README note.
- **Environment name must match** between the PyPI pending-publisher config and
  `release.yml` (`pypi` in both) or trusted publishing fails.
- **`.gitignore` already ignores** `dist/`, `build/`, `*.egg-info/` — no stray artifacts.
- **Three differing names** (dist/import/command) is the cost of skipping the rename;
  accepted, documented in README.

---

## Execution order

**Phase 1 — repo changes (me, landed as version `3.5.1`):**

1. `setup.py` — dist name `codecoco` + keyword. *(1 line + 1 word)*
2. `requirements_dev.txt` — add `build`, `twine`.
3. `justfile` — `changelog-draft` / `build` / `check-dist` / `release` / `publish` recipes.
4. `.github/workflows/release.yml` — tag-triggered build + trusted publish + GH Release.
5. `RELEASING.md` — rewrite intro, add the release flow.
6. `README.md` — install-name note.
7. Add the `## [3.5.1]` CHANGELOG entry + bump `__version__` to `3.5.1`.

**Phase 2 — accounts (you):**

8. PyPI pending publisher for `codecoco` + GitHub `pypi` environment (no secrets — OIDC).

**Phase 3 — first publish:**

9. `just release` → tags `v3.5.1`, pushes → CI publishes to PyPI + cuts the GitHub Release.

Phase 1 is doable in-repo now. Phase 2 needs your login; Phase 3 runs once Phase 2 is done.
