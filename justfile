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

# Run only the integration tests, which download the language server (about 250 MB) on first run
integration:
    EXOLOT_INTEGRATION=1 uv run --group dev pytest -q tests/test_integration.py

# Run the test suite with coverage, printing a report and writing coverage.xml and junit.xml
coverage *args:
    uv run --group dev pytest -q --cov --cov-report=term-missing --cov-report=xml --junitxml=junit.xml -o junit_family=legacy {{args}}

# Run coverage, then report coverage of the lines changed since base
patch-coverage base='origin/master': coverage (diff-cover base)

# Report coverage of the lines changed since base from an existing coverage.xml (extra args go to diff-cover)
diff-cover base='origin/master' *args:
    uv run --group dev diff-cover coverage.xml --compare-branch={{base}} --branch-coverage {{args}}

# patch-coverage-post's arguments are a PR number and, optionally, --report
# (default patch-coverage.md, from `just diff-cover origin/master --format
# markdown:patch-coverage.md`), --commit and --run-url (see --help for the
# rest). It comments with $GITHUB_TOKEN (default `gh auth token`, so locally it
# posts as you), posts nothing unless --commit is still the PR's head, and edits
# its previous comment rather than posting another. --no-project, as it needs
# only the standard library: CI runs it with a write-capable token, and nothing
# should be installed alongside that.

# Post a patch coverage report to a PR as a comment, or update the existing one
[positional-arguments]
patch-coverage-post *args:
    uv run --no-project python -m scripts.post_patch_coverage "$@"

# CI's coverage job runs this on PRs before uploading to Codecov; it never fails,
# only warns. --no-project, like patch-coverage-post, as it runs with a token.

# Wait (up to 10 minutes) for Codecov to have a PR base commit's coverage: arguments are owner/repo and the base SHA
[positional-arguments]
wait-for-base-coverage *args:
    uv run --no-project python -m scripts.wait_for_base_coverage "$@"

# Run exolot on its own code; extra args go to exolot, e.g. --exit-zero. Like
# `just integration`, it downloads the language server (about 250 MB) on first
# run, so `just ci` leaves it out; CI's self-analysis job runs it.

# Analyze this repo with exolot itself
[positional-arguments]
self-analyze *args:
    uv run exolot "$@"

# Turn `just self-analyze --format json` output into a Markdown report (see --help)
[positional-arguments]
self-analysis-report *args:
    uv run --no-project python -m scripts.self_analysis report "$@"

# --no-project, like patch-coverage-post, as CI runs it with a write-capable token.

# Post a self-analysis report to a PR, hiding the ones posted before: arguments are the PR number and the report
[positional-arguments]
self-analysis-post *args:
    uv run --no-project python -m scripts.self_analysis post "$@"

# Build the sdist and wheel into dist/
build:
    uv build

# Install the wheel `just build` built into a fresh environment and check that it runs
smoke:
    #!/usr/bin/env bash
    set -euo pipefail
    version="$(uv version --short)"
    wheel="dist/exolot-${version}-py3-none-any.whl"
    run() { uvx --isolated --no-cache --from "$wheel" exolot "$@"; }
    actual="$(run --version)"
    if [ "$actual" != "exolot ${version}" ]; then
        echo "expected 'exolot ${version}' from ${wheel} --version, got '${actual}'" >&2
        exit 1
    fi
    run --help >/dev/null
    run cache-dir >/dev/null
    echo "${wheel} installs and runs"

# Retries while PyPI's index catches up with a new upload.
# Check that a released version installs from PyPI and runs
[positional-arguments]
check-release version:
    #!/usr/bin/env bash
    set -euo pipefail
    for delay in 0 10 20 40 80 160; do
        sleep "$delay"
        if actual="$(uvx --isolated --no-cache --from "exolot==$1" exolot --version)" && [ "$actual" = "exolot $1" ]; then
            echo "exolot $1 installs from PyPI and runs"
            exit 0
        fi
    done
    echo "exolot $1 did not install from PyPI and run" >&2
    exit 1

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
    uv run --group dev jactionlint

# Check that every workflow installs the uv version pyproject.toml requires and the just version the justfile requires
check-pins:
    uv run --no-project python -m scripts.check_pins

# Run all checks, without fixing anything or running tests
check: lint fmt-check lint-workflows check-pins

# Reformat code and autofix lint issues. Formatting first fixes the long lines it
# can, so lint-fix stops only on findings that need a hand edit.
fix: fmt lint-fix

# Leaves out CI's integration job (`just integration`), which downloads the language server.
# Run everything CI's build, test and coverage jobs run (except the PR-only patch coverage), on this machine's Python and OS
ci: lock-check sync check coverage build smoke
