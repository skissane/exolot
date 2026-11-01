import pytest

from exolot import config
from exolot.config import Config, ConfigError


def test_no_config(tmp_path):
    (tmp_path / ".git").mkdir()
    assert config.load(tmp_path) == Config()


def test_exolot_toml_comes_before_pyproject(tmp_path):
    (tmp_path / ".exolot.toml").write_text('preamble = "from exolot.toml"\n')
    (tmp_path / "pyproject.toml").write_text('[tool.exolot]\npreamble = "from pyproject"\n')
    assert config.load(tmp_path) == Config(preamble="from exolot.toml", path=tmp_path / ".exolot.toml")


def test_pyproject_without_a_table_is_skipped(tmp_path):
    sub = tmp_path / "sub"
    sub.mkdir()
    (sub / "pyproject.toml").write_text("[tool.ruff]\nline-length = 1\n")
    (tmp_path / "sub" / "deeper").mkdir()
    (sub / "deeper" / "pyproject.toml").write_text('tool = "exolot"\n')
    (tmp_path / "pyproject.toml").write_text('[tool.exolot]\npreamble = """\nRead *this*.\n"""\n')
    assert config.load(sub / "deeper") == Config(preamble="Read *this*.\n", path=tmp_path / "pyproject.toml")


def test_search_stops_at_the_repo_root(tmp_path):
    (tmp_path / ".exolot.toml").write_text('preamble = "outside"\n')
    repo = tmp_path / "repo"
    (repo / "sub").mkdir(parents=True)
    (repo / ".git").write_text("gitdir: elsewhere\n")
    assert config.find(repo / "sub") is None
    (repo / ".exolot.toml").write_text("")
    assert config.load(repo / "sub") == Config(path=repo / ".exolot.toml")


@pytest.mark.parametrize(
    ("name", "text", "error"),
    [
        (".exolot.toml", "preamble = 1\n", "preamble should be a str"),
        (".exolot.toml", "nope = 1\n", "unknown setting 'nope'"),
        (".exolot.toml", "preamble = \n", "Invalid value"),
        ("pyproject.toml", "[tool.exolot]\nnope = 1\n", "[tool.exolot]: unknown setting 'nope'"),
        ("pyproject.toml", "tool.exolot = 1\n", "should be a table"),
        ("pyproject.toml", "[tool\n", "pyproject.toml: "),
    ],
)
def test_bad_config(tmp_path, name, text, error):
    (tmp_path / name).write_text(text)
    with pytest.raises(ConfigError) as exc:
        config.load(tmp_path)
    assert error in str(exc.value)


def test_directories_named_like_config_files_are_skipped(tmp_path):
    (tmp_path / ".exolot.toml").mkdir()
    (tmp_path / "pyproject.toml").mkdir()
    assert config.load(tmp_path) == Config()
