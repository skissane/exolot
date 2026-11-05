import json
from pathlib import Path
from typing import Any

import pytest

from exolot import cli, config, rules
from exolot.analyze import AnalysisSession
from exolot.config import Config, ConfigError
from tests.test_analyze import FakeServer


def test_check_keeps_valid_settings() -> None:
    value = {
        "python:S1764": {"level": "off"},
        "python:S107": {"level": "on", "parameters": {"max": "5"}},
        "javascript:S103": {"parameters": {}},
        "python:S100": {},
    }
    assert rules.check(value, "here") == value
    assert rules.check({}, "here") == {}


def test_check_makes_parameters_strings() -> None:
    value = {"python:S107": {"parameters": {"max": 5, "ratio": 0.5, "strict": True, "lax": False}}}
    assert rules.check(value, "here") == {
        "python:S107": {"parameters": {"max": "5", "ratio": "0.5", "strict": "true", "lax": "false"}}
    }


@pytest.mark.parametrize(
    ("value", "error"),
    [
        ([], "here: rules should be an object of rule keys to settings"),
        ({"S1764": {"level": "off"}}, "here: rule 'S1764': rule keys look like 'python:S1764'"),
        ({"a:b:c": {}}, "rule keys look like"),
        ({"python:S1764": "off"}, "here: rule 'python:S1764': should be an object"),
        ({"python:S1764": {"level": "Off"}}, 'level should be "on" or "off"'),
        ({"python:S1764": {"level": False}}, 'level should be "on" or "off"'),
        ({"python:S1764": {"severity": "off"}}, "unknown setting 'severity' (known: level, parameters)"),
        ({"python:S107": {"parameters": ["max"]}}, "parameters should be an object"),
        ({"python:S107": {"parameters": {"max": [5]}}}, "parameter 'max' should be a string, number or boolean"),
        ({"python:S107": {"parameters": {"max": None}}}, "parameter 'max' should be"),
    ],
)
def test_check_rejects_malformed_settings(value: object, error: str) -> None:
    with pytest.raises(ValueError) as exc:
        rules.check(value, "here")
    assert error in str(exc.value)


def test_load(tmp_path: Path) -> None:
    path = tmp_path / "rules.json"
    path.write_text('{"python:S1764": {"level": "off"}}')
    assert rules.load(path) == {"python:S1764": {"level": "off"}}
    path.write_text("{not json")
    with pytest.raises(ValueError, match=r"rules\.json: Expecting property name"):
        rules.load(path)
    path.write_text('["python:S1764"]')
    with pytest.raises(ValueError, match=r"rules\.json: rules should be an object"):
        rules.load(path)
    with pytest.raises(OSError):
        rules.load(tmp_path / "missing.json")


def test_config_rules_table(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text(
        '[tool.exolot.rules]\n"python:S1764" = { level = "off" }\n'
        '"python:S107" = { level = "on", parameters = { max = 5 } }\n'
    )
    assert config.load(tmp_path) == Config(
        rules={"python:S1764": {"level": "off"}, "python:S107": {"level": "on", "parameters": {"max": "5"}}},
        path=tmp_path / "pyproject.toml",
    )


def test_config_rules_file_is_relative_to_the_config_file(tmp_path: Path) -> None:
    (tmp_path / ".exolot.toml").write_text('rules-file = "lint/rules.json"\n')
    (tmp_path / "sub").mkdir()
    assert config.load(tmp_path / "sub") == Config(
        rules_file=tmp_path / "lint" / "rules.json", path=tmp_path / ".exolot.toml"
    )


@pytest.mark.parametrize(
    ("text", "error"),
    [
        ('rules = "rules.json"\n', "rules should be a dict"),
        ("rules-file = 1\n", "rules-file should be a str"),
        ('rules-file = "r.json"\n[rules]\n', "set rules or rules-file, not both"),
        ('[rules]\n"python:S1764" = { level = "no" }\n', "rule 'python:S1764': level should be"),
    ],
)
def test_config_rejects_bad_rules(tmp_path: Path, text: str, error: str) -> None:
    (tmp_path / ".exolot.toml").write_text(text)
    with pytest.raises(ConfigError) as exc:
        config.load(tmp_path)
    assert f"{tmp_path / '.exolot.toml'}: " in str(exc.value)
    assert error in str(exc.value)


def test_session_sends_the_rules_in_its_settings(tmp_path: Path) -> None:
    server = FakeServer(root=tmp_path, java=Path("java"))
    assert AnalysisSession(server, tmp_path)._settings()["rules"] == {}
    settings = {"python:S1764": {"level": "off"}}
    assert AnalysisSession(server, tmp_path, rules=settings)._settings()["rules"] == settings


@pytest.fixture
def used_rules(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    """A git repository with a Python file, analyzed by the fake server,
    whose AnalysisSession records the rule settings it was given."""
    monkeypatch.setattr(cli, "ensure_server", lambda *args: FakeServer(root=tmp_path, java=Path("java")))
    used: list[dict[str, Any]] = []
    real_init = AnalysisSession.__init__

    def init(self: AnalysisSession, *args: Any, **kwargs: Any) -> None:
        real_init(self, *args, **kwargs)
        used.append(self.rules)

    monkeypatch.setattr(AnalysisSession, "__init__", init)
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".git").mkdir()
    (tmp_path / "a.py").write_text("x = 1\n")
    return used


OFF = {"python:S1764": {"level": "off"}}
ON = {"python:S1764": {"level": "on"}}


def test_cli_uses_the_configs_rules(used_rules: list[dict[str, Any]], tmp_path: Path) -> None:
    (tmp_path / ".exolot.toml").write_text('[rules]\n"python:S1764" = { level = "off" }\n')
    cli.main(["a.py"])
    (tmp_path / "lint").mkdir()
    (tmp_path / "lint" / "rules.json").write_text(json.dumps(ON))
    (tmp_path / ".exolot.toml").write_text('rules-file = "lint/rules.json"\n')
    cli.main(["a.py"])
    assert used_rules == [OFF, ON]


def test_cli_rules_option_replaces_the_configs(used_rules: list[dict[str, Any]], tmp_path: Path) -> None:
    (tmp_path / "given.json").write_text(json.dumps(ON))
    (tmp_path / ".exolot.toml").write_text('[rules]\n"python:S1764" = { level = "off" }\n"python:S1" = {}\n')
    cli.main(["--rules", "given.json", "a.py"])
    (tmp_path / ".exolot.toml").write_text('rules-file = "missing.json"\n')
    cli.main(["--rules", "given.json", "a.py"])
    assert used_rules == [ON, ON]


@pytest.mark.parametrize(
    ("args", "config_text", "error"),
    [
        ([], 'rules-file = "missing.json"\n', "exolot: can't read rules-file {missing} (from {config}): "),
        ([], 'rules-file = "bad.json"\n', "exolot: {bad}: rules should be an object"),
        (["--rules", "missing.json"], None, "exolot: [Errno 2] No such file or directory: 'missing.json'"),
        (["--rules", "bad.json"], None, "exolot: bad.json: rules should be an object"),
    ],
)
def test_cli_rejects_bad_rules_files(
    used_rules: list[dict[str, Any]],
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    args: list[str],
    config_text: str | None,
    error: str,
) -> None:
    (tmp_path / "bad.json").write_text("[]")
    if config_text:
        (tmp_path / ".exolot.toml").write_text(config_text)
    assert cli.main([*args, "a.py"]) == 2
    expected = error.format(
        missing=tmp_path / "missing.json", bad=tmp_path / "bad.json", config=tmp_path / ".exolot.toml"
    )
    assert expected in capsys.readouterr().err
    assert used_rules == []
