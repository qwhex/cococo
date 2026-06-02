# Run linters, type checks, tests, and the readme lint
check: lint typecheck test check-readme

# Lint with flake8
lint:
    flake8 .

# Type-check with mypy
typecheck:
    mypy .

# Run the test suite with coverage
test:
    python -m pytest --cov=cognitive_complexity --cov-report=xml

# Lint the README
check-readme:
    mdl README.md

# Run the performance benchmark. Pass extra args, e.g. `just bench --mode compute -n 200`
bench *args:
    python benchmarks/run_benchmark.py {{args}}
