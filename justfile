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

# Run the test suite with coverage, printing a report and writing coverage.xml
coverage *args:
    uv run --group dev pytest -q --cov --cov-report=term-missing --cov-report=xml {{args}}

# Run coverage, then report coverage of the lines changed since base
patch-coverage base='origin/master': coverage (diff-cover base)

# Report coverage of the lines changed since base from an existing coverage.xml (extra args go to diff-cover)
diff-cover base='origin/master' *args:
    uv run --group dev diff-cover coverage.xml --compare-branch={{base}} --branch-coverage {{args}}

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

# Lint the GitHub Actions workflows with jactionlint
lint-workflows:
    uv run --group dev jactionlint --profile correctness

# Run all checks, without fixing anything or running tests
check: lint fmt-check lint-workflows

# Reformat code and autofix lint issues. Formatting first fixes the long lines it
# can, so lint-fix stops only on findings that need a hand edit.
fix: fmt lint-fix

# Run everything CI's build, test and coverage jobs run (except the PR-only patch coverage), on this machine's Python and OS
ci: lock-check sync check coverage build
