set minimum-version := '1.58.0'

# Runs repoutils (see AGENTS.md) with nothing else installed, for recipes CI
# runs with a write-capable token: --only-group installs only the repoutils
# group, checking its hashes against uv.lock, and doesn't build or install
# exolot, whose build backend would otherwise run alongside the token.
# --project names this justfile's project, so a [no-cd] recipe run in another
# checkout (as CI's long-files and added-strings jobs do) still uses it.
repoutils := "uv run --project " + quote(justfile_directory()) + " --only-group repoutils repoutils"

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
    uv run --group dev pytest -q --cov --cov-report=term-missing --cov-report=xml {{ args }}

# Run coverage, then report coverage of the lines changed since base
patch-coverage base='origin/master': coverage (diff-cover base)

# Report coverage of the lines changed since base from an existing coverage.xml (extra args go to diff-cover)
diff-cover base='origin/master' *args:
    uv run --group dev diff-cover coverage.xml --compare-branch={{ base }} --branch-coverage {{ args }}

# The posting recipes run with a write-capable token in CI, so they use the
# repoutils variable above, installing nothing else.

# Post a patch coverage report (default patch-coverage.md) to a PR as a comment, or update the existing one (--output <file> writes it there instead)
[positional-arguments]
patch-coverage-post *args:
    {{ repoutils }} post-patch-coverage "$@"

# Post the coverage in coverage.xml (and --patch-report) as commit statuses on a commit (argument: its SHA)
[positional-arguments]
coverage-status-post *args:
    {{ repoutils }} post-coverage-status "$@"

# Wait (up to 10 minutes) for a PR base commit's coverage/project status: arguments are owner/repo and the base SHA
[positional-arguments]
wait-for-base-coverage *args:
    {{ repoutils }} wait-for-base-coverage "$@"

# Re-lock a Dependabot branch's uv.lock with this uv, from the merge base's uv.lock, upgrading only the packages Dependabot bumped (argument: the PR's base branch, already fetched, e.g. origin/master)
dependabot-relock base:
    {{ repoutils }} dependabot-relock {{ quote(base) }}

# Report whether sonarlint-vscode has a release past its cooldown that's newer than upstream.toml's current one (not in check, as a new release would fail unrelated PRs)
upstream-check:
    uv run repoutils github-releases check

# Pin sonarlint-vscode's newest release past its cooldown in upstream.toml, if it's newer than the current one (--pr: on a new branch, in a new PR, as bump-sonarlint-vscode.yml does)
[positional-arguments]
upstream-bump *args:
    {{ repoutils }} github-releases bump "$@"

# These two report on the working tree they're run in ([no-cd]), so CI can run
# this justfile, from the PR's base, on a checkout of the PR's head beside it.

# List the files over pyproject.toml's line limit as Markdown, changed files first, or post that to a PR (--post <PR>)
[no-cd]
[positional-arguments]
long-files *args:
    {{ repoutils }} long-files "$@"

# List the suppression comments (NOSONAR, noqa, type: ignore) added since a base as Markdown, or post that to a PR (--post <PR>)
[no-cd]
[positional-arguments]
added-strings *args:
    {{ repoutils }} added-strings "$@"

# Run exolot on its own code; extra args go to exolot, e.g. --exit-zero. Like
# `just integration`, it downloads the language server (about 250 MB) on first
# run, so `just ci` leaves it out; CI's self-analysis job runs it.

# Analyze this repo with exolot itself
[positional-arguments]
self-analyze *args:
    uv run exolot "$@"

# Post a `just self-analyze --format github-comment` report to a PR, hiding the ones posted before: arguments are the PR number and the report
[positional-arguments]
self-analysis-post *args:
    {{ repoutils }} post-comment --name self-analysis --hide-previous "$@"

# Build the sdist and wheel into dist/
build:
    uv build

# The publish jobs run this between attest-action and uv publish, which would
# otherwise upload a file without its attestation. It installs nothing else, as
# they run it with id-token: write.

# Check that every distribution in dist/ (or the directory given) has a PEP 740 publish attestation
[positional-arguments]
check-attestations dist="dist":
    {{ repoutils }} check-attestations "$1"

# Install the wheel `just build` built into a fresh environment and check that it runs
smoke:
    #!/usr/bin/env bash
    set -euo pipefail
    version="$(uv version --short)"
    wheel="dist/exolot-${version}-py3-none-any.whl"
    run() { uvx --isolated --no-cache --from "$wheel" exolot "$@"; }
    # The build hook records the commit, and whether the checkout had changes
    # (untracked files included), as the build saw them.
    commit="$(git rev-parse HEAD)"
    expected="exolot ${version} (${commit:0:12}"
    if [ -n "$(git status --porcelain --untracked-files=normal -- .)" ]; then
        expected+=" with uncommitted changes"
    fi
    expected+=")"
    actual="$(run --version)"
    if [ "$actual" != "$expected" ]; then
        echo "expected '${expected}' from ${wheel} --version, got '${actual}'" >&2
        exit 1
    fi
    run --help >/dev/null
    run cache-dir >/dev/null
    echo "${wheel} installs and runs"

# Retries while the index catches up with a new upload. --version may name the
# build's commit after the version, which this doesn't check (smoke does).
# Check that a released version installs from PyPI (or the index given) and runs
[positional-arguments]
check-release version index="https://pypi.org/simple/":
    #!/usr/bin/env bash
    set -euo pipefail
    for delay in 0 10 20 40 80 160; do
        sleep "$delay"
        if actual="$(uvx --isolated --no-cache --default-index "$2" --from "exolot==$1" exolot --version)" && [[ "$actual" == "exolot $1" || "$actual" == "exolot $1 ("* ]]; then
            echo "exolot $1 installs from $2 and runs"
            exit 0
        fi
    done
    echo "exolot $1 did not install from $2 and run" >&2
    exit 1

# Lint with ruff, failing on any warning too, as ruff only warns about such
# things as an invalid noqa directive. --no-cache, as ruff gives those only for
# files it reparses. uv's --quiet keeps uv's own warnings out of the check.
lint:
    #!/usr/bin/env bash
    set -euo pipefail
    stderr="$(mktemp)"
    trap 'rm -f "$stderr"' EXIT
    status=0
    uv run --quiet --group dev ruff check --no-cache . 2>"$stderr" || status=$?
    cat "$stderr" >&2
    if grep -q '^warning:' "$stderr"; then
        echo 'ruff gave a warning (see above)' >&2
        exit 1
    fi
    exit "$status"

# Lint with ruff, applying its autofixes
lint-fix:
    uv run --group dev ruff check --fix .

# Format code with ruff
fmt:
    uv run --group dev ruff format .

# Check code is formatted, without changing it
fmt-check:
    uv run --group dev ruff format --check .

# Format justfile using just's built-in formatter
just-fmt:
    {{ quote(just_executable()) }} --justfile {{ quote(justfile()) }} --fmt

# Check that the justfile is formatted according to just's built-in formatter
just-fmt-check:
    {{ quote(just_executable()) }} --justfile {{ quote(justfile()) }} --fmt --check

# Type-check src and tests with mypy (strict; see pyproject.toml's [tool.mypy])
mypy:
    uv run --group dev mypy

# Type-check src and tests with pyright (strict; see pyproject.toml's [tool.pyright])
pyright:
    uv run --group dev pyright

# Lint the GitHub Actions workflows with jactionlint
lint-workflows:
    uv run --group dev jactionlint

# Check Git-tracked text files for trailing whitespace and bad newlines
whitespace-check:
    uv run repoutils check-whitespace

# Check the Markdown files pyproject.toml lists stay one sentence per line
sentence-per-line-check:
    uv run repoutils check-sentence-per-line

# Check AGENTS.md and README.md prose for long, clause-heavy sentences, or too many short ones (not yet in check: neither passes)
prose-check:
    uv run repoutils check-prose

# Check that every workflow and local action installs the uv version pyproject.toml requires and the just version the justfile requires
check-pins:
    uv run repoutils check-pins

# Check that every actions/checkout step sets persist-credentials, so none keeps its token by default
check-checkout-credentials:
    uv run repoutils check-checkout-credentials

# Check that the workflows use exactly the secrets pyproject.toml lists
secrets-workflows-check:
    uv run repoutils secrets check-workflows

# Check that the workflows use exactly the variables pyproject.toml lists
variables-workflows-check:
    uv run repoutils variables check-workflows

# Check that the justfile has the standard recipes, and that check, fix, ci and patch-coverage reach the standard ones
check-justfile:
    uv run repoutils check-justfile --just {{ quote(just_executable()) }} --justfile {{ quote(justfile()) }}

# Check `secrets export` round-trips made-up secrets through age (on the PATH), also encrypting to the GitHub key given as USER/SHA256:FINGERPRINT
secrets-export-test $SECRETS_EXPORT_KEY='':
    {{ repoutils }} secrets export --self-test ${SECRETS_EXPORT_KEY:+--github-key "$SECRETS_EXPORT_KEY"}

# Check that uv.lock only has wheels for the platforms pyproject.toml allows
lock-platforms-check:
    uv run repoutils check-lock-platforms

# Check that dependency minimums in pyproject.toml match uv.lock
requirements-check:
    {{ repoutils }} requirements-min-versions check

# Rewrite dependency minimums in pyproject.toml to the versions in uv.lock
requirements-fix:
    {{ repoutils }} requirements-min-versions fix

# Check the GitHub settings pyproject.toml declares (labels, repository and security settings, rulesets, environments, secrets, deploy keys); needs an admin token, so CI doesn't run it
github-settings-check *args:
    uv run repoutils github-settings check {{ args }}

# Apply the GitHub settings pyproject.toml declares, creating what's missing; needs an admin token
github-settings-ensure *args:
    uv run repoutils github-settings ensure {{ args }}

# Run the Inspect Secrets workflow on master and print what it found about each secret (token types, owners, expiry); needs a token with Actions write access
inspect-secrets *args:
    uv run repoutils secrets inspect-remote {{ args }}

# Leaves out `just pyright`, a second-opinion type checker that CI deliberately
# doesn't run (yet), and `just prose-check`, which the docs don't pass yet
# (both listed in pyproject.toml's [tool.repoutils.justfile]).

# Run all checks, without fixing anything or running tests
check: lint fmt-check just-fmt-check mypy lint-workflows actions-lock-check whitespace-check sentence-per-line-check check-pins check-checkout-credentials secrets-workflows-check variables-workflows-check check-justfile lock-platforms-check requirements-check

# Formatting first fixes the long lines it can, so lint-fix stops only on
# findings that need a hand edit.

# Reformat code, autofix lint issues and update actions.lock
fix: fmt just-fmt lint-fix requirements-fix actions-lock

# Check .github/workflows/actions.lock pins every action the workflows use, transitive ones included, to a commit that still verifies upstream (needs gh, logged in, with the github/gh-actions-lock extension)
actions-lock-check:
    gh actions-lock --verify

# Pin every action the workflows use in .github/workflows/actions.lock (needs gh, logged in, with the github/gh-actions-lock extension)
actions-lock:
    gh actions-lock

# Leaves out CI's integration job (`just integration`), which downloads the language server.

# Run everything CI's build, test and coverage jobs run (except the PR-only patch coverage), on this machine's Python and OS
ci: lock-check sync check coverage build smoke
