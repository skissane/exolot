from pathlib import Path

import pytest

from scripts.check_pins import main, pins, steps

WORKFLOW = """\
jobs:
  build:
    steps:
      - uses: actions/checkout@v4

      # A comment between steps
      - name: Install uv
        uses: astral-sh/setup-uv@v5
        with:
          # pinned
          version: "0.13.6"
          python-version: ${{ matrix.python-version }}

      - name: Install just
        uses: extractions/setup-just@v3
        with:
          just-version: '1.58.0'

      - name: Other
        uses: some/action@v1
        with:
          version: "9.9.9"
          args:
            - --x
            - --y
  other:
    steps:
      - uses: astral-sh/setup-uv@v5
      - run: echo
"""


def test_steps_splits_outermost_items_only():
    found = steps(WORKFLOW)
    assert [s[0].strip() for s in found] == [
        "- uses: actions/checkout@v4",
        "- name: Install uv",
        "- name: Install just",
        "- name: Other",
        "- uses: astral-sh/setup-uv@v5",
        "- run: echo",
    ]
    assert found[3][-1].strip() == "- --y"


def test_pins_reads_each_steps_own_input():
    # The unpinned setup-uv in `other` isn't masked by `Other`'s version.
    assert pins(WORKFLOW, "astral-sh/setup-uv", "version") == ["0.13.6", None]
    assert pins(WORKFLOW, "extractions/setup-just", "just-version") == ["1.58.0"]


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    (tmp_path / "pyproject.toml").write_text('[tool.uv]\nrequired-version = ">=0.13.6"\n')
    (tmp_path / "justfile").write_text("set minimum-version := '1.58.0'\n\ndefault:\n")
    (tmp_path / ".github" / "workflows").mkdir(parents=True)
    return tmp_path


def test_main_passes_when_all_pinned(repo, capsys):
    (repo / ".github/workflows/a.yml").write_text(WORKFLOW.split("  other:")[0])
    assert main(repo) == 0
    assert capsys.readouterr().out == "workflows pin uv 0.13.6 and just 1.58.0\n"


def test_main_reports_unpinned_and_mismatched_in_yaml_files(repo, capsys):
    (repo / ".github/workflows/a.yaml").write_text(WORKFLOW.replace("'1.58.0'", "1.57.0"))
    assert main(repo) == 1
    assert capsys.readouterr().err.splitlines() == [
        ".github/workflows/a.yaml: a astral-sh/setup-uv step has no version, not 0.13.6",
        ".github/workflows/a.yaml: a extractions/setup-just step has just-version: 1.57.0, not 1.58.0",
    ]


def test_main_rejects_unexpected_minimums(repo):
    (repo / "pyproject.toml").write_text('[tool.uv]\nrequired-version = "==0.13.6"\n')
    with pytest.raises(ValueError, match="isn't of the form"):
        main(repo)
    (repo / "pyproject.toml").write_text('[tool.uv]\nrequired-version = ">=0.13.6"\n')
    (repo / "justfile").write_text("default:\n")
    with pytest.raises(ValueError, match="no `set minimum-version"):
        main(repo)
