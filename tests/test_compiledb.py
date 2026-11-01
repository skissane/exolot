import logging
from pathlib import Path

import pytest

from exolot import cli, compiledb, config
from exolot.analyze import AnalysisSession
from exolot.config import Config
from tests.test_analyze import FakeServer


def _database(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("[]\n")
    return path


def test_find_takes_the_nearest_in_or_above_each_path(tmp_path):
    (tmp_path / ".git").mkdir()
    top = _database(tmp_path / "compile_commands.json")
    cmake = _database(tmp_path / "lib" / "build" / "compile_commands.json")
    (tmp_path / "src" / "deep").mkdir(parents=True)
    (tmp_path / "lib" / "x.c").write_text("x\n")
    assert compiledb.find([tmp_path / "src" / "deep", tmp_path / "src"]) == [top]
    assert compiledb.find([tmp_path / "lib" / "x.c", tmp_path]) == [cmake, top]


def test_find_comes_before_build(tmp_path):
    here = _database(tmp_path / "compile_commands.json")
    _database(tmp_path / "build" / "compile_commands.json")
    assert compiledb.find([tmp_path]) == [here]


def test_find_stops_at_the_repo_root(tmp_path):
    _database(tmp_path / "compile_commands.json")
    (tmp_path / "repo" / ".git").mkdir(parents=True)
    (tmp_path / "repo" / "compile_commands.json").mkdir()  # not a file
    assert compiledb.find([tmp_path / "repo"]) == []


def test_config_compile_commands_is_relative_to_the_config_file(tmp_path):
    (tmp_path / ".exolot.toml").write_text('compile-commands = "build/compile_commands.json"\n')
    (tmp_path / "sub").mkdir()
    assert config.load(tmp_path / "sub") == Config(
        compile_commands=tmp_path / "build" / "compile_commands.json", path=tmp_path / ".exolot.toml"
    )


def test_session_passes_the_database_in_its_settings(tmp_path):
    server = FakeServer(root=tmp_path, java=Path("java"))
    assert "pathToCompileCommands" not in AnalysisSession(server, tmp_path)._settings()
    database = tmp_path / "compile_commands.json"
    settings = AnalysisSession(server, tmp_path, compile_commands=database)._settings()
    assert settings["pathToCompileCommands"] == str(database)


@pytest.fixture
def c_project(tmp_path, monkeypatch):
    """A git repository with C and Python files, analyzed by the fake
    server, whose AnalysisSession records the database it was given."""
    monkeypatch.setattr(cli, "ensure_server", lambda *args: FakeServer(root=tmp_path, java=Path("java")))
    used = []
    real_init = AnalysisSession.__init__

    def init(self, *args, **kwargs):
        real_init(self, *args, **kwargs)
        used.append(self.compile_commands)

    monkeypatch.setattr(AnalysisSession, "__init__", init)
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".git").mkdir()
    for name in ("a.py", "b.c", "c.h", "d.cpp"):
        (tmp_path / name).write_text("x\n")
    return used


def test_cli_skips_c_files_without_a_database(c_project, capsys):
    assert cli.main(["--exit-zero"]) == 0
    err = capsys.readouterr().err
    assert (
        "exolot: warning: no compilation database (compile_commands.json) was found; make one, e.g. with bear or "
        "CMake, or pass --compile-commands, so 3 C/C++/Objective-C file(s) were not analyzed\n"
    ) in err
    assert "1 issue(s) in 1 file(s) analyzed; 3 C/C++/Objective-C file(s) not analyzed (no compilation database)" in err
    assert c_project == [None]


def test_cli_finds_the_database(c_project, tmp_path, capsys, caplog):
    caplog.set_level(logging.INFO, "exolot.cli")
    database = _database(tmp_path / "build" / "compile_commands.json")
    cli.main([])
    assert f"using the compilation database {database}" in caplog.messages
    # The database is a JSON file, so it's analyzed too.
    assert "5 issue(s) in 5 file(s) analyzed\n" in capsys.readouterr().err
    assert c_project == [database]


def test_cli_wont_choose_between_databases(c_project, tmp_path, capsys):
    (tmp_path / "x").mkdir()
    (tmp_path / "x" / "e.c").write_text("x\n")
    one = _database(tmp_path / "compile_commands.json")
    two = _database(tmp_path / "x" / "compile_commands.json")
    cli.main([".", "x"])
    err = capsys.readouterr().err
    assert f"there's more than one compilation database ({one}, {two}); choose one with --compile-commands" in err
    assert "4 C/C++/Objective-C file(s) not analyzed (no compilation database)" in err
    assert c_project == [None]


def test_cli_doesnt_look_without_c_files(c_project, tmp_path, monkeypatch):
    monkeypatch.setattr(compiledb, "find", lambda paths: pytest.fail("looked for a database"))
    cli.main(["a.py"])
    assert c_project == [None]


def test_cli_uses_the_given_database_before_the_configs(c_project, tmp_path):
    given = _database(tmp_path / "given.json")
    configured = _database(tmp_path / "configured.json")
    _database(tmp_path / "compile_commands.json")
    (tmp_path / ".exolot.toml").write_text('compile-commands = "configured.json"\n')
    cli.main(["--compile-commands", "given.json", "a.py"])
    cli.main(["a.py"])
    assert c_project == [given, configured]


@pytest.mark.parametrize(
    ("args", "config_text", "source"),
    [
        (["--compile-commands", "missing.json"], None, "--compile-commands"),
        ([], 'compile-commands = "missing.json"\n', ".exolot.toml"),
    ],
)
def test_cli_rejects_a_missing_database(c_project, tmp_path, capsys, args, config_text, source):
    if config_text:
        (tmp_path / ".exolot.toml").write_text(config_text)
    assert cli.main(args) == 2
    err = capsys.readouterr().err
    assert f"exolot: no such compilation database: {tmp_path / 'missing.json'} (from " in err
    assert source in err
    assert c_project == []


def test_analyze_repo_takes_the_database_from_the_current_directory(tmp_path, monkeypatch):
    seen = {}
    monkeypatch.setattr(cli, "_clone_and_analyze", lambda args: seen.setdefault("path", args.compile_commands) and 0)
    monkeypatch.chdir(tmp_path)
    cli.main(["analyze-repo", "https://example.com/repo", "--compile-commands", "db.json"])
    assert seen["path"] == tmp_path / "db.json"
