set minimum-version := '1.58.0'

# List available recipes
default:
    @just --list

# Check that uv.lock is up to date with pyproject.toml
lock-check:
    uv lock --check

# Sync dependencies (including dev group)
sync:
    uv sync --group dev

# Run the test suite (set EXOLOT_INTEGRATION=1 to include the integration tests)
test:
    uv run --group dev pytest -q

# Build the sdist and wheel into dist/
build:
    uv build

# Lint with ruff
lint:
    uv run --group dev ruff check .

# Lint with ruff, applying its autofixes
lint-fix:
    uv run --group dev ruff check --fix .

# Format code with ruff
fmt:
    uv run --group dev ruff format .

# Check code is formatted, without changing it
fmt-check:
    uv run --group dev ruff format --check .

# check gets lint-workflows when it replaces CI's validate-actions job (#13).

# Run all checks, without fixing anything or running tests
check: lint fmt-check

# Reformat code and autofix lint issues. Formatting first fixes the long lines it
# can, so lint-fix stops only on findings that need a hand edit.
fix: fmt lint-fix

# Run everything CI's build and test jobs run, on this machine's Python and OS
ci: lock-check sync check test build
