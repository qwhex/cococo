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

# Lint the README
check-readme:
    mdl README.md

# Install git hooks: pre-push runs `just check`, the same gate as CI
install-hooks:
    git config core.hooksPath .githooks
    @echo "Installed: pre-push now runs 'just check' (bypass with 'git push --no-verify')"

# Run the performance benchmark. Pass extra args, e.g. `just bench --mode compute -n 200`
bench *args:
    python benchmarks/run_benchmark.py {{args}}
