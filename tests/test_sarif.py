import json
from pathlib import Path

import jsonschema
import pytest

from exolot import __version__, cli, sarif
from exolot.analyze import Issue, Location
from tests.test_analyze import FakeServer

# From https://github.com/oasis-tcs/sarif-spec (sarif-2.1/schema), the OASIS standard's schema with its errata.
SCHEMA = json.loads(Path(__file__).with_name("data").joinpath("sarif-schema-2.1.0.json").read_text())


def validate(log):
    jsonschema.validate(log, SCHEMA)


def issue(path="/r/a.py", rule="python:S1", severity="warning", line=2, related=()):
    return Issue(
        path=Path(path),
        line=line,
        column=3,
        end_line=line,
        end_column=5,
        rule=rule,
        message=f"{rule} message",
        severity=severity,
        raw={},
        related=list(related),
    )


def relative(path):
    return {"uri": path.name, "uriBaseId": "%SRCROOT%"}


def test_log_maps_issues_to_results():
    other = Location(Path("/r/b.py"), 7, 1, 8, 2, "see here")
    unnamed = Location(Path("/r/a.py"), 1, 1, 1, 1, "")
    issues = [
        issue(rule="python:S2", severity="error", related=[other, unnamed]),
        issue(severity="info"),
        issue(severity="hint"),
        issue(severity="warning"),
    ]
    log = sarif.log(issues, "1.2.3", {"python:S1": "Rule one", "python:S2": ""}, relative)
    validate(log)
    (run,) = log["runs"]
    assert run["tool"]["driver"]["version"] == "1.2.3"
    assert run["tool"]["driver"]["rules"] == [
        {"id": "python:S1", "shortDescription": {"text": "Rule one"}},
        {"id": "python:S2"},
    ]
    results = run["results"]
    assert [(r["ruleId"], r["ruleIndex"], r["level"]) for r in results] == [
        ("python:S2", 1, "error"),
        ("python:S1", 0, "note"),
        ("python:S1", 0, "note"),
        ("python:S1", 0, "warning"),
    ]
    assert results[0]["message"] == {"text": "python:S2 message"}
    assert results[0]["locations"] == [
        {
            "physicalLocation": {
                "artifactLocation": {"uri": "a.py", "uriBaseId": "%SRCROOT%"},
                "region": {"startLine": 2, "startColumn": 3, "endLine": 2, "endColumn": 5},
            }
        }
    ]
    assert results[0]["relatedLocations"] == [
        {
            "id": 1,
            "physicalLocation": {
                "artifactLocation": {"uri": "b.py", "uriBaseId": "%SRCROOT%"},
                "region": {"startLine": 7, "startColumn": 1, "endLine": 8, "endColumn": 2},
            },
            "message": {"text": "see here"},
        },
        {
            "id": 2,
            "physicalLocation": {
                "artifactLocation": {"uri": "a.py", "uriBaseId": "%SRCROOT%"},
                "region": {"startLine": 1, "startColumn": 1, "endLine": 1, "endColumn": 1},
            },
        },
    ]
    assert "relatedLocations" not in results[1]


def test_log_with_no_issues():
    log = sarif.log([], "1.2.3", {}, relative)
    validate(log)
    assert log["runs"][0]["results"] == []
    assert log["runs"][0]["tool"]["driver"]["rules"] == []


def _run(tmp_path, monkeypatch, capsys, *texts, flags=()):
    """Analyze one file per text in a git repo, from a subdirectory of it."""
    monkeypatch.setattr(cli, "ensure_server", lambda *args: FakeServer(root=tmp_path, java=Path("java")))
    repo = tmp_path / "repo"
    sub = repo / "sub dir"
    sub.mkdir(parents=True)
    (repo / ".git").mkdir()
    for name, text in zip("abc", texts):
        (sub / f"{name}.py").write_text(text + "\n")
    monkeypatch.chdir(sub)
    status = cli.main(["--format", "sarif", *flags, "--workspace", str(repo), "."])
    captured = capsys.readouterr()
    log = json.loads(captured.out)
    validate(log)
    return status, log, captured.err


def test_cli_sarif(tmp_path, monkeypatch, capsys):
    status, log, err = _run(tmp_path, monkeypatch, capsys, "FLOW", "x = 1")
    assert status == 1
    assert "3 issue(s) in 2 file(s) analyzed" in err
    (run,) = log["runs"]
    assert run["tool"]["driver"]["name"] == "exolot"
    assert run["tool"]["driver"]["version"] == __version__
    assert run["tool"]["driver"]["rules"] == [
        {"id": "fake:S1", "shortDescription": {"text": "Fake rule one"}},
        {"id": "fake:S3"},
    ]
    results = run["results"]
    assert [(r["ruleId"], r["message"]["text"]) for r in results] == [
        ("fake:S3", "flow issue"),
        ("fake:S1", "python issue"),
        ("fake:S1", "python issue"),
    ]
    location = results[1]["locations"][0]["physicalLocation"]
    assert location == {
        "artifactLocation": {"uri": "sub%20dir/a.py", "uriBaseId": "%SRCROOT%"},
        "region": {"startLine": 1, "startColumn": 3, "endLine": 1, "endColumn": 6},
    }
    assert results[0]["level"] == "error"
    related = results[0]["relatedLocations"]
    assert [(r["physicalLocation"]["artifactLocation"]["uri"], r.get("message")) for r in related] == [
        ("sub%20dir/a.py", {"text": "the other one"}),
        ("sub%20dir/a.py", None),
    ]
    assert related[0]["physicalLocation"]["region"] == {"startLine": 1, "startColumn": 5, "endLine": 1, "endColumn": 7}


@pytest.mark.parametrize("env", [{}, {"FAKE_SERVER_CODE_ACTIONS_FAIL": "1"}])
def test_cli_sarif_keeps_the_message_without_the_locations(tmp_path, monkeypatch, capsys, env):
    for name, value in env.items():
        monkeypatch.setenv(name, value)
    _, log, _ = _run(tmp_path, monkeypatch, capsys, "FLOW NOLOCATIONS")
    (flow,) = [r for r in log["runs"][0]["results"] if r["ruleId"] == "fake:S3"]
    assert flow["message"]["text"] == "flow issue [+1 location]"
    assert "relatedLocations" not in flow


def test_cli_sarif_file_outside_a_repo(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(cli, "ensure_server", lambda *args: FakeServer(root=tmp_path, java=Path("java")))
    source = tmp_path / "a.py"
    source.write_text("x = 1\n")
    cli.main(["--format", "sarif", "--exit-zero", "--workspace", str(tmp_path), str(source)])
    log = json.loads(capsys.readouterr().out)
    validate(log)
    location = log["runs"][0]["results"][0]["locations"][0]["physicalLocation"]
    assert location["artifactLocation"] == {"uri": source.resolve().as_uri()}


def test_cli_sarif_with_no_issues(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(cli.AnalysisSession, "analyze", lambda self, files, timeout=None: [])

    def unneeded(self, *args):
        raise AssertionError("not needed when there are no issues")

    monkeypatch.setattr(cli.AnalysisSession, "rule_names", unneeded)
    monkeypatch.setattr(cli.AnalysisSession, "add_related_locations", unneeded)
    status, log, err = _run(tmp_path, monkeypatch, capsys, "x = 1")
    assert status == 0
    assert log["runs"][0]["results"] == []
    assert "0 issue(s) in 1 file(s) analyzed" in err


def test_cli_rejects_statistics_with_sarif(tmp_path, monkeypatch, capsys):
    def fail(*args, **kwargs):
        raise AssertionError("should not download")

    monkeypatch.setattr(cli, "ensure_server", fail)
    with pytest.raises(SystemExit) as exc:
        cli.main(["--format", "sarif", "--statistics", str(tmp_path)])
    assert exc.value.code == 2
    assert "--statistics can't be used with --format sarif" in capsys.readouterr().err
