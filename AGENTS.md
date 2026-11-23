# AGENTS.md

Notes for AI coding agents (and humans) working on exolot.
See `README.md` for what exolot does, how it works and how to run the tests.

This file is written one sentence per line rather than wrapped at a fixed width.
`just sentence-per-line-check` (part of `just check`) enforces that formatting.
`README.md` is still wrapped, so the check leaves it out for now.

## Commands

CI (`.github/workflows/build.yml`) calls the `justfile`'s recipes rather than running commands inline.
Run `just ci` before opening a PR to run everything CI runs.
`just check` runs every check without fixing anything or running tests.
`just fix` applies every autofix, and `just --list` shows the individual recipes.
Both need `gh` logged in with the gh-actions-lock extension for `actions-lock-check` and `actions-lock` (see below).
Whatever `just fix` fixes, `just check` checks.
`just mypy` (part of `just check`) type-checks `src` and `tests` with mypy in strict mode (`pyproject.toml`'s `[tool.mypy]`).
All new code (tests included) needs full type annotations.
Test functions return `-> None`, and pytest's fixtures are `tmp_path: Path`, `monkeypatch: pytest.MonkeyPatch`, `capsys: pytest.CaptureFixture[str]` and `caplog: pytest.LogCaptureFixture`.
A method that overrides one in a base class needs `@override` (mypy's `explicit-override`, pyright's `reportImplicitOverride`).
`just pyright` type-checks the same code with pyright in strict mode (`[tool.pyright]`) as a second opinion.
It isn't part of `just check`, so CI doesn't run it while two type checkers in CI aren't clearly worth it.
It reports nothing today.
Running it after changing types is optional and welcome, as it catches some things mypy doesn't.
The `pyright` package bundles pyright itself, and its `nodeenv` dependency downloads nothing when installed (`uv sync` fetches no Node.js).
Only running `just pyright` on a machine with no `node` on its `PATH` downloads Node.js into `~/.cache/pyright-python/nodeenv` on the first run and reuses it after that.
`just lint` (part of `just check`) runs ruff with `--no-cache` and fails on any warning ruff prints (such as an invalid `noqa` directive) as well as on its findings.
ruff itself only prints warnings and gives them only for files it reparses.
`just whitespace-check` (part of `just check`) fails on trailing whitespace, a leading blank line or a missing or extra final newline in any Git-tracked text file.
`just doubled-spaces-check` (part of `just check`) fails on doubled spaces between words in `AGENTS.md` and `README.md` prose, and `just doubled-spaces-fix` (part of `just fix`) collapses them.
`just check-justfile` (part of `just check`) checks that the justfile has repoutils' standard recipes and that `check`, `fix`, `ci` and `patch-coverage` reach the standard ones.
A recipe or dependency exolot leaves out on purpose goes in `pyproject.toml`'s `[tool.repoutils.justfile]`, which today keeps `pyright` out of `check`.
Every `just` run first runs `repoutils git-config-setup` to point the checkout's `blame.ignoreRevsFile` at `.git-blame-ignore-revs`, so `git blame` skips the commits listed there (none yet).
`just blame-ignore-revs-check` (part of `just check`) fails unless each entry is a full hash of a commit in the history of `$BLAME_IGNORE_REVS_TARGET` (or of `HEAD` when unset).
On PRs, CI sets that variable to the base branch because a PR's own commits are lost when it's squash-merged.
List a commit there only once it's on `master`.
`just prose-check` (part of `just check`) checks `AGENTS.md` and `README.md` for long, clause-heavy sentences or too many short ones.
`just lock-platforms-check` (part of `just check`) fails if `uv.lock` has wheels for platforms outside `[tool.uv] environments` (macOS, Linux x86_64 and aarch64, and Windows x86_64, where CI runs).
`just requirements-check` (part of `just check`) fails if a dependency's minimum in `pyproject.toml` isn't the version `uv.lock` locks, and `just requirements-fix` (part of `just fix`) raises the minimums to match.
`just lint-workflows` (part of `just check`) runs `jactionlint` over the workflows and `.github/dependabot.yml` with the rules `.github/jactionlint.yaml` turns on.
It shellchecks their `run:` steps only when `shellcheck` is on your `PATH` (as on GitHub's Ubuntu runners), and otherwise prints a note and skips them.
Before opening a PR, also run `just patch-coverage`.
It runs `just coverage` (tests with a coverage report and `coverage.xml`) and reports which changed lines since `origin/master` the tests miss.
Pass another base as its first argument when needed, e.g. `just patch-coverage origin/some-branch`.
Cover the changed lines it reports where a test is worth it.
CI's coverage job shows total and patch coverage in its job summary on every push and PR (on `master`, the patch is the commit's own change).
Its `post-coverage-status` job posts them as the `coverage/project` and `coverage/patch` commit statuses (always `success`) on `master`'s commits and on non-Dependabot PRs from this repository.
That gives `master`'s statuses a history of coverage.
On those PRs, its `post-patch-coverage` job also posts the patch coverage report as a PR comment (`just patch-coverage-post`).
The report includes the project's coverage and its change from the base commit's `coverage/project` status.
The comment warns without failing anything when a PR drops total coverage by more than 2 points or leaves patch coverage more than 1 point below the base's total.
`[tool.repoutils.coverage]` can change both thresholds.
The base's CI may still be running when a PR's coverage is ready.
The coverage job first runs `just wait-for-base-coverage`, which waits up to 10 minutes for the base's `coverage/project` status and gives up with a warning rather than a failure.
`just ci` leaves out CI's `integration` job (`just integration`), which runs the end-to-end tests and downloads the ~250 MB language server.
Run `just integration` yourself when you change how exolot talks to the server or unpacks it.
CI pins its tools across the repository.
Every `setup-uv` step sets `version` to the minimum in `pyproject.toml`'s `[tool.uv] required-version`, and every `setup-just` step sets `just-version` to the `justfile`'s `minimum-version`.
`.python-version` names an exact Python patch release, while the test matrix overrides it with each minor version.
To upgrade uv or just, change the minimum and every workflow's pin together.
`just check-pins` (part of `just check`) checks both and fails if they differ.
repoutils' `prepare-publish` action (see below) takes the same pins as its `uv-version` and `just-version` inputs, which `just check-pins` checks too.
Every `actions/checkout` step sets `persist-credentials` to `false`, or to `true` only in a job that pushes with the checkout's token (with a comment saying so).
`just check-checkout-credentials` (part of `just check`) fails on any step that doesn't.
jactionlint's `artipacked` rule can't enforce this because it skips checkout v6 and later, which still leave the token readable by every later step.
Workflows name every action by its full version tag (`uses: actions/checkout@v7.0.1`).
`.github/workflows/actions.lock` pins each action (including transitive ones used by repoutils' composite actions) to a commit with its repository's IDs.
That keeps a moved tag or a renamed and re-created repository from changing the code that runs.
It's generated by GitHub's [`gh actions-lock`](https://github.com/github/gh-actions-lock) extension (`gh extension install github/gh-actions-lock --pin v0.4.1`) and must never be edited by hand.
After changing any `uses:`, run `just actions-lock` (part of `just fix`), which runs `gh actions-lock` to update the lockfile.
It narrows a partial version (`@v7`) to the newest full tag (`@v7.0.1`) when it first pins it, so name full tags.
exolot has no composite actions of its own and uses repoutils' instead (see below).
`gh actions-lock` needs GitHub's GraphQL API, which Claude Code sessions can't reach.
In those sessions `just check` fails at `actions-lock-check` and `just fix` fails at its last step, `actions-lock` (after its other fixes have run).
Run the other recipes `check` lists instead.
After a `uses:` change, open the PR as a draft and comment `/autofix` (see below) to relock in Actions and push the result.
`just actions-lock-check` (part of `just check`) runs `gh actions-lock --verify` and fails if the lockfile is missing an action or a locked commit no longer verifies upstream.
In CI it runs in `check-and-build` (the `build` job, named apart from `attestations.yml`'s `build` job) with `GITHUB_TOKEN` (`contents: read`).
`check-and-build` is the only required check and also waits on `test`, failing unless `test` succeeded so a failure blocks merging.
It runs even when `test` fails because a job skipped due to a failed dependency would count as passing.
`check-and-build` and `fix.yml` install the extension with repoutils' `install-gh-actions-lock` action.
That action downloads the `linux-amd64` release binary of the version its `install.sh` pins, checks its SHA-256 and installs it as a local extension.
`gh extension install --pin` isn't used there because it takes only a release tag for a precompiled extension.
When a repoutils release changes that version, change the `--pin` version in the install command above to match.
Dependabot bumps the actions weekly with a 7-day cooldown and regenerates the lockfile entries in the same PR.
It bumps the dev dependencies in `uv.lock` weekly too, using its own uv.
Dependabot's uv can write `uv.lock` in a newer format than the pinned uv, churning lines unrelated to the bump.
On Dependabot's uv PRs, `build.yml`'s `dependabot-fix` job runs `just dependabot-relock origin/<base>` (`repoutils dependabot-relock`).
It restores the merge base's `uv.lock` and re-locks it with the pinned uv, upgrading only the packages Dependabot bumped to its exact versions.
If that fails or locks other versions, the job fails and Dependabot's `uv.lock` stays.
`dependabot-fix` runs the branch's code with a read-only token and uploads its commit as a Git bundle.
Then `dependabot-push` (which runs nothing from the branch) uses repoutils' `push-bundle` action to check that the bundle is one commit on the PR head changing only `uv.lock`.
It pushes that commit with the `DEPENDABOT_FIX_TOKEN` Dependabot secret (a fine-grained token with only contents write on this repository) so the push triggers CI.
When you add a step to CI, add it as a recipe and include it in `check`, `fix` or `ci` as fits so `just ci` keeps matching CI.
GitHub's API doesn't serve step summaries, so every job that writes one also uploads it as an artifact that `gh run download <run> --pattern 'step-summaries-*'` can fetch.
A step that writes to `$GITHUB_STEP_SUMMARY` (itself or through a command such as `just patch-coverage-post`) starts with a `trap` that copies that file to `$RUNNER_TEMP/step-summaries/<name>.md` when the step exits.
The trap copies it even when the step fails, keeping a failed step's summary as well.
The job's last step (`Upload the step summaries`) uploads that directory as the artifact `step-summaries-${{ github.job }}` with `if: always()` and `if-no-files-found: ignore`.
Copy both from an existing job, such as `long-files` in `build.yml`.
A matrix job adds its matrix values to the artifact's name, as each artifact in a run needs its own name.

## repoutils

The repository checks and CI helpers come from [repoutils](https://github.com/sjktools/repoutils), a dev dependency in its own `repoutils` dependency group configured in `pyproject.toml`'s `[tool.repoutils]`.
See repoutils' README for each command.
Recipes that only check run `uv run repoutils <command>`.
Recipes that CI runs with a write-capable token or `id-token: write` (posting PR comments and commit statuses, `check-attestations`) use the justfile's `repoutils` variable (`uv run --project <the justfile's directory> --only-group repoutils repoutils`).
That command installs only repoutils (hash-checked against `uv.lock`) and doesn't build or install exolot.
repoutils also has composite actions that the workflows use as `uses: sjktools/repoutils/.github/actions/<action>@v<version>`.
Each runs one repoutils command from the action's own commit with the runner's `python3` and installs nothing:

- `autofix-start`, `autofix-relock`, `autofix-check`, `autofix-resolve` and `push-bundle` for `/autofix` (see below), and `push-bundle` for `dependabot-push`.
- `post-comment` for `fix-push.yml`'s report and the Claude workflows' self-test reports.
- `testpypi-dispatch` for `/testpypi`, `bump-version` for the Bump Version workflow and `release-tag` for `build.yml`'s `release` job.
- `inspect-secrets` for the Inspect Secrets workflow and `claude-route` for the Claude workflows' `route` jobs.
- `prepare-publish` for the publish jobs and `attestations.yml`, and `install-gh-actions-lock` (see above).

`post-comment` and `autofix-start` read `comment-prefix` from `pyproject.toml`, so their jobs check out that file first unless the job already has a checkout.
`just check-pins` checks that `actions.lock` locks every repoutils action at the commit the locked repoutils package was built from, so the actions' `@v<version>` and `uv.lock`'s repoutils move together.
repoutils' Bump downstream workflow opens a PR here that moves both at each repoutils release, so `.github/dependabot.yml` tells Dependabot to ignore repoutils in both ecosystems.
On PRs, the jobs that post comments and commit statuses (`post-patch-coverage`, `post-coverage-status`, `post-self-analysis`, `long-files` and `added-strings`) check out the PR's base commit rather than the PR.
That way a PR's changes to the justfile, `pyproject.toml` or `uv.lock` don't run beside their write-capable token and take effect only once it merges.
The workflow file itself still comes from the PR, as in any `pull_request` run.
`long-files` and `added-strings` report on the PR's head, so they also check it out into `head/` as data only and run the base's `[no-cd]` recipes in it with `just --justfile ../justfile`.
That checkout's `pyproject.toml` is read as data, so a PR's changes to `[tool.repoutils]`'s report settings apply to its own reports.
`comment-prefix = "exolot"` keeps the PR comments' hidden markers as they were before repoutils (`<!-- exolot-patch-coverage -->`, `<!-- exolot-self-analysis -->`).
`[tool.repoutils.secrets]` lists the secrets the workflows use.
`just secrets-workflows-check` (part of `just check`) fails if a workflow starts or stops using a secret without updating that list, and `just variables-workflows-check` does the same for Actions variables.

## Long files and added suppressions

Two more reports are for information only.
What they find never fails anything, though an error running one (a bad setting, a failed git command or a failed GitHub request) still does.
`just long-files` lists the Python files over `[tool.repoutils.long-files]`' limit of 500 lines, with the ones changed since `origin/master` first.
Split a long file only where that makes the code better, as the report's policy says.
A long file that is one cohesive unit can stay as it is.
`just added-strings` lists the `NOSONAR`, `# noqa` and `# type: ignore` comments added since `origin/master` (`[tool.repoutils.added-strings]` configures them), making the rule against suppressing findings below easy to check.
Its regexes match only a comment rather than a string or test data naming one, and `tests/test_added_strings.py` checks them.
Both recipes are `[no-cd]` and report on the working tree they're run in.
Both take `--post <PR>` to post the report as a PR comment that later runs edit in place.
CI's `long-files` job (on PRs and `master`) and `added-strings` job (on PRs) write their reports to the job summary.
On non-Dependabot PRs from this repository, they also post them as PR comments, while neither posts a first comment when it has nothing to report.
Keep each added suppression that's actually needed, with no reply or explanation, and remove the rest.

## `/autofix`

A PR comment that is just `/autofix` from the repository's owner (or an organization member) runs `just fix` on the PR's branch and pushes the result with the `AUTOFIX_TOKEN` secret.
It works only on an open PR from this repository.
`autofix-comment.yml` dispatches `fix.yml` (PR Fixes) on the PR's branch.
`fix.yml` merges the base branch in, runs `just fix` with no secrets and a read-only `GITHUB_TOKEN`, and uploads its commits as a Git bundle.
Then `fix-push.yml` (PR Fixes Push) runs from `master` and executes no code from the branch.
It checks that the bundle only adds commits to the branch and pushes them with repoutils' `autofix-resolve` and `push-bundle` actions.
`autofix-comment.yml`'s `autofix-start` action (`repoutils autofix`) waits for the fix run and dispatches `fix-push.yml` itself, as a run dispatched with a `GITHUB_TOKEN` starts no `workflow_run` workflow.
A `workflow_run` trigger covers a fix run that a person starts by hand (Actions → PR Fixes → Run workflow, on the PR's branch).
`autofix-comment.yml` passes the PR's number to `fix.yml`, which puts it in the run's name because GitHub's API gives a run's name but not its inputs.
`fix-push.yml` reads the number from there, so a branch with several open PRs against different bases fixes the one commented on.
A fix run started by hand without a number needs the branch to have exactly one open PR in this repository.
`repoutils autofix <PR>` starts a fix run as the comment does, for a client that can't post the comment as it is (such as Claude Code on the web).
It finds the push run by `fix-push.yml`'s run name, which names the fix run.
Each `/autofix` reports its outcome (success or failure) in a new PR comment, which notifies the PR's subscribers as an edit wouldn't, and hides the earlier reports as outdated.
GitHub won't start the branch's `fix.yml` while the branch's `actions.lock` doesn't list every action it uses.
When that happens, `autofix-comment.yml`'s `relock` job (repoutils' `autofix-relock` action) relocks the branch with no write-capable token and runs nothing from the branch.
Its `retry` job then has `fix-push.yml` push that relock (a single commit that changes only `actions.lock`) and starts PR Fixes again on the new head.
The fix runs on the branch rather than on `master` because code in a run can write to the Actions cache of the run's branch.
If it ran on `master`, the branch's code could plant cache entries that `master`'s jobs would restore.
`AUTOFIX_TOKEN` is a fine-grained token with only contents and workflows write on this repository, so its push triggers CI (unlike a `GITHUB_TOKEN` push).
It needs workflows write to push `.github/workflows/actions.lock`, which `just fix` regenerates.
`fix-push.yml` checks that the bundle holds at most a clean merge of the base branch and one commit of fixes that changes nothing under `.github/workflows` except `actions.lock`.
It lives in the `autofix` environment, which only `master` can deploy to, as with `release`.
A branch that predates `fix.yml` has to merge `master` in before `/autofix` can run on it.

## Releases and GitHub settings

Releases are cut from `master`.
The Bump Version workflow (run from `master`) opens a PR bumping `version` in `pyproject.toml` and `uv.lock` with the `GH_ACTIONS_TOKEN` secret.
It uses repoutils' `bump-version` action, which edits both files as text and runs no uv alongside the token.
Once the PR merges, `build.yml`'s `release` job uses repoutils' `release-tag` action to push the tag `v<version>` over SSH with the `RELEASE_DEPLOY_KEY` deploy key.
That tag triggers `publish-pypi.yml`, and the job then creates the GitHub release with its own `GITHUB_TOKEN`.
`publish-pypi.yml` publishes to TestPyPI and checks that the release installs from there.
It publishes the same files to PyPI only once Simon approves the `pypi` environment's deployment, which only `v*` tags can make.
The sonarlint-vscode release exolot downloads by default and the digests it checks each VSIX against are in `src/exolot/upstream.toml`.
`repoutils github-releases bump` writes that file (configured in `pyproject.toml`'s `[tool.repoutils.github-releases.sonarlint-vscode]`), so don't edit it by hand.
The Bump sonarlint-vscode workflow (`bump-sonarlint-vscode.yml`) runs it daily on `master` and opens a PR with `GH_ACTIONS_TOKEN` when sonarlint-vscode has a newer release at least 7 days old.
It takes the digests from GitHub's releases API without downloading anything, so check that PR's `integration` job (which isn't required) before merging it, and cut a release after.
`just upstream-check` reports whether there's a newer release.
It isn't part of `just check`, as a new release would then fail unrelated PRs.
`GH_ACTIONS_TOKEN` and `RELEASE_DEPLOY_KEY` live in the `release` environment, which only `master` can deploy to, so a workflow run from any other branch can't read them.
The Inspect Secrets workflow (`inspect-secrets.yml`, run by hand from `master`) runs `repoutils secrets inspect` on each secret `[tool.repoutils.secrets]` lists.
It reports each GitHub token's type, owner and expiry (never its value) in its job summary, and fails when a token expires within 14 days or GitHub rejects it.
Each job runs repoutils' `inspect-secrets` action, which uploads the job's step summary as `step-summaries-<job>-<environment>`.
The workflow has one job per environment that holds secrets, as a job gets an environment's secrets only by deploying to it.
Add a job when you add an environment with secrets.
`just inspect-secrets` starts that workflow from your machine and prints its summaries (it needs a token with Actions write access, e.g. `gh auth login`'s).
`just inspect-secrets --run-id <run>` prints an earlier run's summaries instead.
Two tag rulesets protect `v*` tags: nobody can move or delete one, and only a deploy key can create one.
That deploy key must be the repository's only one with write access, as the ruleset's bypass covers them all.
Immutable releases stop a published release's assets and tag from changing.
The jobs that publish or attest a release install uv with `enable-cache: false` (`prepare-publish` does).
The jobs that tag or bump a release install no uv at all, so a poisoned Actions cache entry can't reach them.

`pyproject.toml`'s `[tool.repoutils]` declares these settings along with the labels, the repository settings and `master`'s ruleset.
`just github-settings-check` checks that the repository matches it, and `just github-settings-ensure` applies it (see repoutils' README).
Both need a token with administration access, which neither CI nor Claude Code sessions have, so Simon runs them.
When you change a setting on GitHub, change `pyproject.toml` to match, and the other way round.

## exolot's findings on itself

CI's `self-analysis` job runs exolot on its own code (`just self-analyze --exit-zero --diff-base origin/<base branch>` on PRs).
You can run it yourself, adding `--changed-only` to see just the findings on lines you changed (it downloads the language server like `just integration`).
It shows the findings as annotations on the PR's diff (`--annotations`) and lists them in its job summary.
On non-Dependabot PRs from this repository, it also posts them as a PR comment with the findings on changed lines first.
The report is made with `--format github-comment`, which starts with the policy in `pyproject.toml`'s `[tool.exolot]` `preamble`.
The `post-self-analysis` job posts it with `repoutils post-comment --hide-previous`, hiding the previous run's comment as outdated.
The findings are for information only, and `--exit-zero` means findings never fail the job (though a failed analysis still does).

- Judge each finding on one question: would the change it asks for make the code better (a real bug fixed, or code that's clearer, simpler or safer)?
  If so, make it, and if not, leave it.
  For metric rules such as cognitive complexity (`python:S3776`), sketch the actual refactor and judge the result.
  How far the code is over the threshold is not a reason to fix or to ignore it.
  A refactor that only moves complexity into helpers that don't name a real idea, or splits code that reads best as one piece, makes the code worse, so leave that finding.
- Pay most attention to findings on lines your PR changes.
  Don't widen a PR to fix findings elsewhere unless asked.
- A finding you've chosen to ignore doesn't block a PR and needs no reply or explanation.
- Don't suppress an ignored finding: no `NOSONAR` or `noqa` comments, and no `--rules` file to turn rules off.
  The comment's list of findings is fine as it is.

## Test warnings policy

pytest turns every warning into an error (`filterwarnings = ["error"]` in `pyproject.toml`).
This matters most for `ResourceWarning` because exolot spawns the language server and talks to it over pipes.
A process or pipe that isn't closed shows up as a `ResourceWarning`, often in a later test than the one that leaked it.
Fix the cause of a warning rather than filtering it.
If one really can't be fixed (e.g. it comes from a dependency), filter only that warning by category and message as narrowly as possible, with a comment saying why.
Use one test's `@pytest.mark.filterwarnings` rather than `pyproject.toml` if only one test triggers it.
Never add a blanket ignore such as `ignore::ResourceWarning` or `ignore::DeprecationWarning`.

## Issue labels

Issues are labelled `dimension:value`.
When you file an issue, give it one `type:` and one `priority:` label, a `size:` label unless it's a parent issue, and any `concern:` labels that apply.

- `type:` (exactly one): `bug` (something behaves wrongly), `feature` (a new capability), `improvement` (makes something that already works better), `maintenance` (refactors, dead code, CI, dependencies, with no visible change) or `docs` (documentation only).
- `priority:` (exactly one, defined by what to do about it): `p0` (drop everything when a release is broken, e.g. `uvx exolot` fails or reports wrong results), `p1` (do next), `p2` (worth doing when convenient) or `p3` (someday/maybe).
- `size:` (exactly one, except on parent issues), by how many PRs it takes rather than hours: `s` (one small PR), `m` (one PR that needs some design) or `l` (several PRs).
  An `l` issue should become a parent issue with sub-issues.
  Parent issues get no `size:` label, and their sub-issues do.
- `concern:` (zero or more):
  - `security`: a security risk or hardening, e.g. verifying the VSIX or JRE download.
  - `upstream`: depends on how SonarSource's VSIX or language server behaves, so a new VSIX release can break or change it.
  - `platform`: specific to an OS or architecture, e.g. linux-arm64, which has no platform VSIX.
  - `breaking`: changes CLI flags, output or exit codes that users' scripts rely on.

  These are separate from `type:`, as a security problem can be a bug, a missing feature or a maintenance job.

`question` is for issues that ask something rather than report or request something.
`dependencies` marks Dependabot's PRs, which also get `type:maintenance` (`.github/dependabot.yml` sets both).
Close duplicates and things that won't be done with GitHub's "duplicate" and "not planned" close reasons (there are no labels for them).

An open issue with no `priority:` label is untriaged (`is:open -label:priority:p0 -label:priority:p1 -label:priority:p2 -label:priority:p3`).
When asked what to work on next, start from the `priority:p1` issues.
Update an issue's labels when you learn more about it, e.g. when a fix turns out bigger than its `size:` or is split into sub-issues and loses its `size:`.
Use only these labels: applying a label that doesn't exist creates a new grey one, so a typo or a new value silently adds to the scheme.
Propose a new dimension or value to the owner rather than inventing one.
