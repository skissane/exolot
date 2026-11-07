import json
from pathlib import Path
from typing import Any

import pytest

from exolot import cli, config, rules
from exolot.analyze import AnalysisSession
from exolot.config import Config, ConfigError
from tests.test_analyze import FakeServer


def test_check_keeps_valid_settings() -> None:
    value: dict[str, dict[str, Any]] = {
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
    path.write_bytes(b'{"python:S1764": {"level": "\xff"}}')
    with pytest.raises(ValueError, match=r"rules\.json: 'utf-8' codec can't decode"):
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


def test_parse_keys() -> None:
    assert rules.parse_keys("python:S1764") == ["python:S1764"]
    assert rules.parse_keys("python:S1764, python:S107") == ["python:S1764", "python:S107"]


@pytest.mark.parametrize("value", ["S1764", "", "python:S1764,", "a:b:c"])
def test_parse_keys_rejects_malformed_keys(value: str) -> None:
    with pytest.raises(ValueError, match="rule keys look like 'python:S1764'"):
        rules.parse_keys(value)


def test_select_turns_the_rules_on_keeping_their_parameters() -> None:
    settings = {
        "python:S1764": {"level": "off"},
        "python:S107": {"level": "off", "parameters": {"max": "1"}},
        "python:S100": {"level": "off"},
    }
    assert rules.select(settings, ["python:S1764", "python:S107", "python:S3776"]) == {
        "python:S1764": {"level": "on"},
        "python:S107": {"level": "on", "parameters": {"max": "1"}},
        "python:S100": {"level": "off"},
        "python:S3776": {"level": "on"},
    }
    assert settings["python:S1764"] == {"level": "off"}  # unchanged
    assert rules.select(None, ["python:S1764"]) == ON


def test_cli_select_turns_on_rules_the_config_turns_off(used_rules: list[dict[str, Any]], tmp_path: Path) -> None:
    (tmp_path / ".exolot.toml").write_text('[rules]\n"python:S1764" = { level = "off" }\n"python:S1" = {}\n')
    cli.main(["--select", "python:S1764", "a.py"])
    (tmp_path / "given.json").write_text(json.dumps(OFF))
    cli.main(["--rules", "given.json", "--select", "python:S1764,python:S2", "a.py"])
    assert used_rules == [{**ON, "python:S1": {}}, {**ON, "python:S2": {"level": "on"}}]


def test_cli_rejects_malformed_select(used_rules: list[dict[str, Any]], capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exc:
        cli.main(["--select", "S1764", "a.py"])
    assert exc.value.code == 2
    assert "argument --select: 'S1764' isn't a rule key" in capsys.readouterr().err
    assert used_rules == []


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("python:S107.max=5", ("python:S107", "max", "5")),
        ("python:S107.max=", ("python:S107", "max", "")),
        (" python:S107 . max =a=b ", ("python:S107", "max", "a=b ")),
        ("python:S100.format=^[a-z_][a-z0-9_.]*$", ("python:S100", "format", "^[a-z_][a-z0-9_.]*$")),
        ("repo.x:S1.name=v", ("repo.x:S1", "name", "v")),
    ],
)
def test_parse_param(value: str, expected: tuple[str, str, str]) -> None:
    assert rules.parse_param(value) == expected


@pytest.mark.parametrize("value", ["python:S107.max", "python:S107=5", "python:S107.=5", "python:S107. =5", "=5"])
def test_parse_param_rejects_malformed_settings(value: str) -> None:
    with pytest.raises(ValueError, match=r"should look like RULE\.NAME=VALUE"):
        rules.parse_param(value)


@pytest.mark.parametrize("value", ["S107.max=5", ".max=5", "a:b:c.max=5"])
def test_parse_param_rejects_malformed_rule_keys(value: str) -> None:
    with pytest.raises(ValueError, match="rule keys look like 'python:S1764'"):
        rules.parse_param(value)


def test_set_params_keeps_levels_and_other_parameters() -> None:
    settings = {
        "python:S1764": {"level": "off"},
        "python:S107": {"level": "on", "parameters": {"max": "1", "other": "x"}},
    }
    params = [("python:S107", "max", "2"), ("python:S1764", "p", "1"), ("python:S3776", "threshold", "5")]
    assert rules.set_params(settings, [*params, ("python:S107", "max", "3")]) == {
        "python:S1764": {"level": "off", "parameters": {"p": "1"}},
        "python:S107": {"level": "on", "parameters": {"max": "3", "other": "x"}},
        "python:S3776": {"parameters": {"threshold": "5"}},
    }
    assert settings["python:S107"] == {"level": "on", "parameters": {"max": "1", "other": "x"}}  # unchanged
    assert rules.set_params(None, [("python:S107", "max", "2")]) == {"python:S107": {"parameters": {"max": "2"}}}


def test_cli_rule_param_layers_on_the_rule_settings(used_rules: list[dict[str, Any]], tmp_path: Path) -> None:
    (tmp_path / ".exolot.toml").write_text('[rules]\n"python:S1764" = { level = "off" }\n')
    cli.main(["--rule-param", "python:S1764.a=1", "--rule-param", "python:S107.max=2", "a.py"])
    cli.main(["--select", "python:S1764", "--rule-param", "python:S1764.a=1", "a.py"])
    assert used_rules == [
        {"python:S1764": {"level": "off", "parameters": {"a": "1"}}, "python:S107": {"parameters": {"max": "2"}}},
        {"python:S1764": {"level": "on", "parameters": {"a": "1"}}},
    ]


def test_cli_rejects_malformed_rule_param(used_rules: list[dict[str, Any]], capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exc:
        cli.main(["--rule-param", "python:S107=5", "a.py"])
    assert exc.value.code == 2
    assert "argument --rule-param: 'python:S107=5' should look like RULE.NAME=VALUE" in capsys.readouterr().err
    assert used_rules == []
