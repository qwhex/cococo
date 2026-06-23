# The single gate, run by CI (.github/workflows/ci.yml) and the pre-push hook (`just install-hooks`).
check: format-check lint typecheck complexity test check-readme

# Lint with ruff (ruleset mirrors the parent cosmetix data_pipeline)
lint:
    ruff check .

# Gate our own complexity with cococo (dogfooding), ratcheted to the current ceiling.
complexity:
    # Tighten --max (or refactor) rather than loosen it: no function should get
    # harder to read than today's worst.
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

# Lint the README (mdl, a Ruby gem). Required in CI; optional locally.
check-readme:
    #!/usr/bin/env bash
    set -euo pipefail
    # Skip with a warning if mdl isn't installed locally rather than hard-fail the
    # gate; CI installs it and enforces it. When present, its exit code propagates.
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

# Draft changelog bullets + a suggested bump since the last tag (pass a base ref for the first release).
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

# Cut a release (see RELEASING.md): commit the bump, tag vX.Y.Z, push (triggers publish). `just release dry` to preview.
release dry="":
    #!/usr/bin/env bash
    set -euo pipefail
    # Use the project venv without manual activation (no-op in CI, which has no .venv).
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
