# `just check` is the single gate: CI runs it (see .github/workflows/ci.yml)
# and the pre-push hook runs it locally (see `just install-hooks`).
check: format-check lint typecheck complexity test check-readme

# Lint with ruff (ruleset mirrors the parent cosmetix data_pipeline)
lint:
    ruff check .

# Gate our own cognitive complexity with cococo (dogfooding). Ratcheted to the
# current ceiling so no function is allowed to get harder to read than today's
# worst; tighten it (or refactor) rather than loosen it.
complexity:
    python -m cognitive_complexity.cli cognitive_complexity --max 10

# Reformat with ruff
format:
    ruff format .

# Verify formatting without modifying files (run in `check`)
format-check:
    ruff format --check .

# Type-check the package with mypy (strict)
typecheck:
    mypy cognitive_complexity

# Run the test suite with coverage (enforces the 100% floor)
test:
    python -m pytest --cov=cognitive_complexity --cov-report=xml --cov-fail-under=100

# Lint the README. mdl is a Ruby gem; CI installs it (Ruby 3.3) and enforces it.
# Locally it's optional — if it isn't installed, warn and skip rather than hard-
# fail the gate (and `just release`) on a missing external linter. When mdl IS
# present its exit code propagates, so real lint failures still fail the recipe.
check-readme:
    #!/usr/bin/env bash
    set -euo pipefail
    if command -v mdl >/dev/null 2>&1; then
        mdl README.md
    else
        echo "mdl not installed — skipping README lint (CI enforces it)"
    fi

# Install git hooks: pre-push runs `just check`, the same gate as CI
install-hooks:
    git config core.hooksPath .githooks
    @echo "Installed: pre-push now runs 'just check' (bypass with 'git push --no-verify')"

# Run the performance benchmark. Pass extra args, e.g. `just bench --mode sweep`
bench *args:
    python -m benchmarks.run_benchmark {{args}}

# --- Release (see RELEASING.md) -------------------------------------------------

# Draft changelog bullets + a suggested semver bump for the range since the last
# tag (or `just changelog-draft <base-ref>` for the first release, which has no
# tag). The suggested bump is advisory: upgrade to a major yourself if the change
# moves any complexity score (the score is cococo's public contract).
changelog-draft base="":
    #!/usr/bin/env bash
    set -euo pipefail
    base="{{base}}"
    [ -n "$base" ] || base=$(git describe --tags --abbrev=0)
    smcp changelog "$base" HEAD

# Build the sdist + wheel into a clean dist/.
build:
    rm -rf dist
    python -m build

# Validate the built artifacts (metadata + README rendering on PyPI).
check-dist: build
    twine check dist/*

# Cut a release: must be on master with only the version bump + changelog entry
# uncommitted. Verifies the version in __init__.py has a matching CHANGELOG.md
# section, commits those two files as `release X.Y.Z`, then tags and pushes —
# pushing the tag triggers the publish workflow (.github/workflows/release.yml).
# Pass any argument for a dry run that runs the guards and prints the plan
# without running `just check`, committing, tagging, or pushing — `just release dry`.
release dry="":
    #!/usr/bin/env bash
    set -euo pipefail
    # Use the project venv without requiring manual activation (CI has no .venv
    # and gets `python` from setup-python, so this is a no-op there).
    [ -x .venv/bin/python ] && export PATH="$PWD/.venv/bin:$PATH"
    dry="{{dry}}"
    branch=$(git rev-parse --abbrev-ref HEAD)
    [ "$branch" = "master" ] || { echo "release must be cut from master (on $branch)"; exit 1; }
    # Only the version + changelog may be uncommitted; everything else must be in.
    dirty=$(git status --porcelain --untracked-files=no \
        | grep -vE ' (cognitive_complexity/__init__\.py|CHANGELOG\.md)$' || true)
    [ -z "$dirty" ] || { echo "uncommitted changes outside version/changelog:"; echo "$dirty"; exit 1; }
    version=$(python -c "import cognitive_complexity as c; print(c.__version__)")
    grep -qF "## [$version]" CHANGELOG.md || { echo "no '## [$version]' section in CHANGELOG.md"; exit 1; }
    git rev-parse "v$version" >/dev/null 2>&1 && { echo "tag v$version already exists"; exit 1; } || true
    notes=$(awk "/^## \[$version\]/{f=1;next} /^## \[/{f=0} f" CHANGELOG.md)
    if [ -n "$dry" ]; then
        echo "[dry-run] release $version — guards passed. Would then:"
        echo "[dry-run]   just check"
        echo "[dry-run]   git commit cognitive_complexity/__init__.py CHANGELOG.md -m 'release $version'"
        echo "[dry-run]   git tag -a v$version  (notes below)"
        echo "[dry-run]   git push origin master v$version"
        echo "[dry-run] --- tag notes ---"
        echo "$notes"
        exit 0
    fi
    just check
    git add cognitive_complexity/__init__.py CHANGELOG.md
    git diff --cached --quiet || git commit -m "release $version"
    git tag -a "v$version" -m "$notes"
    git push origin master "v$version"
    echo "Pushed v$version — the release workflow will publish to PyPI."

# Manual publish fallback (CI publishes via trusted publishing; use only if needed).
publish: check-dist
    twine upload dist/*
