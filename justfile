# `just check` is the single gate: CI runs it (see .github/workflows/ci.yml)
# and the pre-push hook runs it locally (see `just install-hooks`).
check: lint typecheck test check-readme

# Lint with ruff (ruleset mirrors the parent cosmetix data_pipeline)
lint:
    ruff check .

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
