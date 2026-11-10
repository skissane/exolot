# AGENTS.md

Notes for AI coding agents (and humans) working on exolot.
See `README.md` for what exolot does, how it works, and how to run the tests.

## Commands

CI (`.github/workflows/build.yml`) calls the `justfile`'s recipes rather than running commands inline, so run `just ci` before opening a PR to run everything CI runs.
`just check` runs every check without fixing anything or running tests, `just fix` applies every autofix, and `just --list` shows the individual recipes.
`just mypy` (part of `just check`) type-checks `src`, `scripts` and `tests` with mypy in strict mode (set in `pyproject.toml`'s `[tool.mypy]`), so all new code, tests included, needs full type annotations: test functions return `-> None`, and pytest's fixtures are `tmp_path: Path`, `monkeypatch: pytest.MonkeyPatch`, `capsys: pytest.CaptureFixture[str]` and `caplog: pytest.LogCaptureFixture`.
A method that overrides one in a base class needs `@override` (mypy's `explicit-override`, pyright's `reportImplicitOverride`).
`just pyright` type-checks the same code with pyright in strict mode (`[tool.pyright]`), as a second opinion; it isn't part of `just check`, so CI doesn't run it: it isn't yet clear that two type checkers in CI are worth it.
It reports nothing today; running it after changing types is optional, but welcome, as it catches some things mypy doesn't.
The `pyright` package bundles pyright itself, and its `nodeenv` dependency downloads nothing when installed: `uv sync` fetches no Node.js. Only running `just pyright` might, and only the first time on a machine with no `node` on its `PATH`, in which case it downloads Node.js into `~/.cache/pyright-python/nodeenv` and reuses it after that.
`just lint-workflows` (part of `just check`) runs `jactionlint` over the workflows and `.github/dependabot.yml`, with the rules `.github/jactionlint.yaml` turns on; it shellchecks their `run:` steps only if `shellcheck` is on your `PATH` (it is on GitHub's Ubuntu runners), and otherwise prints a note and skips them.
Before opening a PR, also run `just patch-coverage`, which runs `just coverage` (tests with a coverage report and `coverage.xml`) and then reports which changed lines since `origin/master` the tests miss; pass another base as its first argument, e.g. `just patch-coverage origin/some-branch`.
Cover the changed lines it reports where a test is worth it; CI's coverage job shows total coverage in its summary on every push and PR, and the patch coverage report too on PRs, which its `post-patch-coverage` job also posts as a PR comment (`just patch-coverage-post`) on PRs from this repository other than Dependabot's.
The coverage job also uploads `coverage.xml` to Codecov, and the `junit.xml` test results `just coverage` writes for Codecov Test Analytics (even if the tests failed), with the `CODECOV_TOKEN` secret, which is set as both an Actions and a Dependabot secret so Dependabot's PRs upload too.
Codecov's `codecov/project` and `codecov/patch` statuses check coverage against `codecov.yml`'s thresholds: a PR may drop total coverage by up to 2% and leave patch coverage up to 1% below the base's total. They aren't required checks, so they report but don't block merging.
Codecov works out a PR's comparison with its base commit's report only when the PR's own upload is processed, and never redoes it, so on PRs the coverage job first runs `just wait-for-base-coverage` (`scripts/wait_for_base_coverage.py`, from taxtracker): it polls Codecov's API until the base has a report, giving up with a warning (never a failure) 2 minutes after the base's `coverage` check run succeeds (or at once finds there's no such run), immediately if that run concluded any other way, or after 10 minutes in all.
`codecov.yml` sets `if_not_found: failure`, so when it gave up `codecov/project` fails; re-run the PR's coverage job once the base has uploaded.
`just ci` leaves out CI's `integration` job, which runs `just integration` (the end-to-end tests, which download the ~250 MB language server); run it yourself when you change how exolot talks to the server or unpacks it.
CI pins its tools: every `setup-uv` step sets `version` to the minimum in `pyproject.toml`'s `[tool.uv] required-version`, every `setup-just` step sets `just-version` to the `justfile`'s `minimum-version`, and `.python-version` names an exact Python patch release (the test matrix overrides it with each minor version).
To upgrade uv or just, change the minimum and every workflow's pin together, including those in the local composite actions under `.github/actions` (`prepare-publish`, which the publish jobs share); `just check-pins` (part of `just check`) checks both and fails if they differ.
Every `actions/checkout` step sets `persist-credentials`: `false`, or `true` only in a job that pushes with the checkout's token, with a comment saying so; `just check-checkout-credentials` (part of `just check`) fails on one that doesn't.
jactionlint's `artipacked` rule can't enforce this, as it skips checkout v6 and later, which still leave the token readable by every later step.
Workflows and local composite actions name every action by its full version tag (`uses: actions/checkout@v7.0.1`), and `.github/workflows/actions.lock` pins each, transitive ones (those composite actions use) included, to a commit, with its repository's IDs, so a moved tag or a renamed and re-created repository can't change the code that runs.
It's generated by GitHub's [`gh actions-lock`](https://github.com/github/gh-actions-lock) extension (`gh extension install github/gh-actions-lock --pin v0.4.1`); never edit it by hand.
After changing any `uses:`, run `gh actions-lock` to update it; it narrows a partial version (`@v7`) to the newest full tag (`@v7.0.1`) when it first pins it, so name full tags.
Workflows use the local `prepare-publish` action as `$/.github/actions/prepare-publish` rather than `./…`, as `gh actions-lock` follows only `$/` references into a local action to lock the actions it uses; a `$/` action always runs at the workflow's own commit.
`gh actions-lock` needs GitHub's GraphQL API, which Claude Code sessions can't reach; there, push the workflow change with a temporary step in `build.yml`'s `actions-lock` job that runs `gh actions-lock` and prints the result, then commit the generated file and remove the step.
The `actions-lock` job runs `gh actions-lock --verify` (with `GITHUB_TOKEN`, `contents: read`), failing if the lockfile is missing an action or a locked commit no longer verifies upstream, and `build`, the only required check, waits on it and on `test`, and fails unless both succeeded (it runs even when they fail, as a job skipped because one it needs failed would count as passing), so a failure blocks merging; `just ci` leaves it out, as it needs GitHub's API.
It downloads v0.4.1's `linux-amd64` release binary and checks its SHA-256 before running it standalone, rather than `gh extension install --pin`, which takes only a release tag for a precompiled extension; to upgrade it, change the version in the URL, the hash, and the `--pin` version in the install command above together.
Dependabot bumps the actions weekly, with a 7-day cooldown, and regenerates the lockfile entries in the same PR.
When you add a step to CI, add it as a recipe and include it in `check`, `fix` or `ci` as fits, so `just ci` keeps matching CI.

## exolot's findings on itself

CI's `self-analysis` job runs exolot on its own code (`just self-analyze --exit-zero --diff-base origin/<base branch>` on PRs, which you can run yourself, adding `--changed-only` to see just the findings on lines you changed; it downloads the language server like `just integration`).
It shows the findings as annotations on the PR's diff (`--annotations`), lists them in its job summary and, on PRs from this repository other than Dependabot's, posts them as a PR comment (made with `--format github-comment`, which starts it with the policy in `pyproject.toml`'s `[tool.exolot]` `preamble`, and posted by the `post-self-analysis` job, `scripts/self_analysis.py`), with the ones on lines the PR changes first; each run hides the previous run's comment as outdated.
The findings are for information only: `--exit-zero` means findings never fail the job, though a failed analysis still does.

- Judge each finding on one question: would the change it asks for make the code better (a real bug fixed, or code that's clearer, simpler or safer)? If so, make it; if not, leave it. For metric rules such as cognitive complexity (`python:S3776`), sketch the actual refactor and judge the result: how far the code is over the threshold is not a reason to fix or to ignore it. A refactor that only moves complexity into helpers that don't name a real idea, or splits code that reads best as one piece, makes the code worse, so leave that finding.
- Pay most attention to findings on lines your PR changes. Don't widen a PR to fix findings elsewhere unless asked.
- A finding you've chosen to ignore doesn't block a PR, and needs no reply or explanation.
- Don't suppress an ignored finding: no `NOSONAR` or `noqa` comments, and no `--rules` file to turn rules off. The comment's list of findings is fine as it is.

## Test warnings policy

pytest turns every warning into an error (`filterwarnings = ["error"]` in `pyproject.toml`).
This matters most for `ResourceWarning`: exolot spawns the language server and talks to it over pipes, so a process or pipe that isn't closed shows up as one, often in a later test than the one that leaked it.
Fix the cause of a warning rather than filtering it.
If one really can't be fixed (e.g. it comes from a dependency), filter only that warning, by category and message, as narrowly as possible (one test's `@pytest.mark.filterwarnings` rather than `pyproject.toml` if only one test triggers it), with a comment saying why.
Never add a blanket ignore such as `ignore::ResourceWarning` or `ignore::DeprecationWarning`.

## Issue labels

Issues are labelled `dimension:value`.
When you file an issue, give it one `type:` and one `priority:` label, a `size:` label unless it's a parent issue, and any `concern:` labels that apply.

- `type:` (exactly one): `bug` (something behaves wrongly), `feature` (a new capability), `improvement` (makes something that already works better), `maintenance` (refactors, dead code, CI, dependencies; no visible change) or `docs` (documentation only).
- `priority:` (exactly one), defined by what to do about it: `p0` (drop everything: a release is broken, e.g. `uvx exolot` fails, or it reports wrong results), `p1` (do next), `p2` (worth doing when convenient) or `p3` (someday/maybe).
- `size:` (exactly one, except on parent issues), by how many PRs it takes rather than hours: `s` (one small PR), `m` (one PR that needs some design) or `l` (several PRs).
  An `l` issue should become a parent issue with sub-issues; parent issues get no `size:` label, their sub-issues do.
- `concern:` (zero or more):
  - `security`: a security risk or hardening, e.g. verifying the VSIX or JRE download.
  - `upstream`: depends on how SonarSource's VSIX or language server behaves, so a new VSIX release can break or change it.
  - `platform`: specific to an OS or architecture, e.g. linux-arm64, which has no platform VSIX.
  - `breaking`: changes CLI flags, output or exit codes that users' scripts rely on.

  These are separate from `type:`, as a security problem can be a bug, a missing feature or a maintenance job.

`question` is for issues that ask something rather than report or request something.
`dependencies` marks Dependabot's PRs, which also get `type:maintenance` (`.github/dependabot.yml` sets both).
Close duplicates and things that won't be done with GitHub's "duplicate" and "not planned" close reasons; there are no labels for them.

An open issue with no `priority:` label is untriaged; find them with `is:open -label:priority:p0 -label:priority:p1 -label:priority:p2 -label:priority:p3`.
When asked what to work on next, start from the `priority:p1` issues.
Update an issue's labels when you learn more about it, e.g. a fix turns out bigger than its `size:`, or it's split into sub-issues and so loses its `size:`.
Use only these labels: applying a label that doesn't exist creates a new grey one, so a typo or a new value silently adds to the scheme.
Propose a new dimension or value to the owner rather than inventing one.
