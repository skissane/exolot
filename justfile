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

# Run the test suite with coverage, printing a report and writing coverage.xml
coverage *args:
    uv run --group dev pytest -q --cov --cov-report=term-missing --cov-report=xml {{args}}

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
    uv run --group dev jactionlint --profile correctness

# Check that every workflow installs the uv version pyproject.toml requires and the just version the justfile requires
check-pins:
    #!/usr/bin/env bash
    set -euo pipefail
    uv_min="$(sed -n 's/^required-version = ">=\(.*\)"$/\1/p' pyproject.toml)"
    just_min="$(sed -n "s/^set minimum-version := '\(.*\)'$/\1/p" justfile)"
    status=0
    check() {
        local action="$1" key="$2" want="$3" found uses
        found="$(grep -A4 "uses: ${action}@" .github/workflows/*.yml | grep -c "${key}: \"${want}\"" || true)"
        uses="$(grep -c "uses: ${action}@" .github/workflows/*.yml | awk -F: '{n += $2} END {print n}')"
        if [ -z "$want" ] || [ "$found" != "$uses" ]; then
            echo "${found} of ${uses} ${action} steps set ${key}: \"${want}\"" >&2
            status=1
        fi
    }
    check astral-sh/setup-uv version "$uv_min"
    check extractions/setup-just just-version "$just_min"
    [ "$status" = 0 ] && echo "workflows pin uv ${uv_min} and just ${just_min}"
    exit "$status"

# Run all checks, without fixing anything or running tests
check: lint fmt-check lint-workflows check-pins

# Reformat code and autofix lint issues. Formatting first fixes the long lines it
# can, so lint-fix stops only on findings that need a hand edit.
fix: fmt lint-fix

# Leaves out CI's integration job (`just integration`), which downloads the language server.
# Run everything CI's build, test and coverage jobs run (except the PR-only patch coverage), on this machine's Python and OS
ci: lock-check sync check coverage build smoke
