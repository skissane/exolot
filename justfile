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

# check and fix get the lint and format recipes as they're added (#6).

# Run all checks, without fixing anything or running tests
check:

# Autofix lint issues and reformat code
fix:

# Run everything the CI workflow runs
ci: lock-check sync check test build
