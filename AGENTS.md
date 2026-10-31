# AGENTS.md

Notes for AI coding agents (and humans) working on exolot.
See `README.md` for what exolot does, how it works, and how to run the tests.

## Commands

CI (`.github/workflows/build.yml`) calls the `justfile`'s recipes rather than running commands inline, so run `just ci` before opening a PR to run everything CI runs.
`just check` runs every check without fixing anything or running tests, `just fix` applies every autofix, and `just --list` shows the individual recipes.
`just lint-workflows` (part of `just check`) runs `jactionlint --profile correctness` over the workflows; it shellchecks their `run:` steps only if `shellcheck` is on your `PATH` (it is on GitHub's Ubuntu runners), and otherwise prints a note and skips them.
Before opening a PR, also run `just patch-coverage`, which runs `just coverage` (tests with a coverage report and `coverage.xml`) and then reports which changed lines since `origin/master` the tests miss; pass another base as its first argument, e.g. `just patch-coverage origin/some-branch`.
Cover the changed lines it reports where a test is worth it; CI's coverage job shows total coverage in its summary on every push and PR, and the patch coverage report too on PRs, which its `post-patch-coverage` job also posts as a PR comment (`just patch-coverage-post`) on PRs from this repository other than Dependabot's; there is no threshold to fail on.
`just ci` leaves out CI's `integration` job, which runs `just integration` (the end-to-end tests, which download the ~250 MB language server); run it yourself when you change how exolot talks to the server or unpacks it.
CI pins its tools: every `setup-uv` step sets `version` to the minimum in `pyproject.toml`'s `[tool.uv] required-version`, every `setup-just` step sets `just-version` to the `justfile`'s `minimum-version`, and `.python-version` names an exact Python patch release (the test matrix overrides it with each minor version).
To upgrade uv or just, change the minimum and every workflow's pin together; `just check-pins` (part of `just check`) fails if they differ.
When you add a step to CI, add it as a recipe and include it in `check`, `fix` or `ci` as fits, so `just ci` keeps matching CI.

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
Close duplicates and things that won't be done with GitHub's "duplicate" and "not planned" close reasons; there are no labels for them.

An open issue with no `priority:` label is untriaged; find them with `is:open -label:priority:p0 -label:priority:p1 -label:priority:p2 -label:priority:p3`.
When asked what to work on next, start from the `priority:p1` issues.
Update an issue's labels when you learn more about it, e.g. a fix turns out bigger than its `size:`, or it's split into sub-issues and so loses its `size:`.
Use only these labels: applying a label that doesn't exist creates a new grey one, so a typo or a new value silently adds to the scheme.
Propose a new dimension or value to the owner rather than inventing one.
