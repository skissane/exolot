import subprocess
import sys
from pathlib import Path

import pytest

from exolot import cli
from exolot.analyze import AnalysisSession, collect_files, language_id
from exolot.server import Server

FAKE_SERVER = Path(__file__).with_name("fake_server.py")


class FakeServer(Server):
    def command(self, jvm_args=None):
        return [sys.executable, str(FAKE_SERVER)]


def test_language_id():
    assert language_id(Path("a.py")) == "python"
    assert language_id(Path("A.TSX")) == "typescriptreact"
    assert language_id(Path("Dockerfile")) == "dockerfile"
    assert language_id(Path("notes.txt")) == "plaintext"


def test_collect_files_skips_binary_and_ignored(tmp_path):
    (tmp_path / "a.py").write_text("x = 1\n")
    (tmp_path / "blob.bin").write_bytes(b"\0\1\2")
    (tmp_path / "node_modules").mkdir()
    (tmp_path / "node_modules" / "dep.js").write_text("x\n")
    files = collect_files([tmp_path])
    assert files == [(tmp_path / "a.py").resolve()]


def test_collect_files_respects_gitignore(tmp_path):
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    (tmp_path / ".gitignore").write_text("ignored.py\n")
    (tmp_path / "ignored.py").write_text("x = 1\n")
    (tmp_path / "kept.py").write_text("x = 1\n")
    names = {f.name for f in collect_files([tmp_path])}
    assert names == {".gitignore", "kept.py"}


def test_session_collects_final_diagnostics(tmp_path):
    a = tmp_path / "a.py"
    a.write_text("x = 1\n")
    b = tmp_path / "b.js"
    b.write_text("var x\n")
    server = FakeServer(root=tmp_path, java=Path("java"))
    with AnalysisSession(server, tmp_path) as session:
        issues = session.analyze([a, b], settle=0.2, timeout=10)
    issues.sort(key=lambda i: i.path.name)
    assert [(i.path.name, i.line, i.column, i.rule, i.message) for i in issues] == [
        ("a.py", 1, 3, "fake:S1", "python issue"),
        ("b.js", 1, 3, "fake:S1", "javascript issue"),
    ]


def test_session_raises_when_a_file_is_never_published(tmp_path):
    a = tmp_path / "a.py"
    a.write_text("SILENT\n")
    server = FakeServer(root=tmp_path, java=Path("java"))
    with AnalysisSession(server, tmp_path) as session:
        with pytest.raises(RuntimeError, match="never reported results"):
            session.analyze([a], settle=0.1, stall=0.5, timeout=10)


def test_session_closes_server_pipes(tmp_path):
    server = FakeServer(root=tmp_path, java=Path("java"))
    with AnalysisSession(server, tmp_path) as session:
        proc = session._proc
    assert proc.returncode is not None
    assert proc.stdin.closed and proc.stdout.closed


def test_session_closes_pipes_of_a_server_that_died(tmp_path):
    server = FakeServer(root=tmp_path, java=Path("java"))
    with AnalysisSession(server, tmp_path) as session:
        proc = session._proc
        proc.kill()
        proc.wait()
    assert proc.stdin.closed and proc.stdout.closed


def test_closing_an_unstarted_session_does_nothing(tmp_path):
    AnalysisSession(FakeServer(root=tmp_path, java=Path("java")), tmp_path).close()


def test_collect_files_rejects_missing_path(tmp_path):
    with pytest.raises(FileNotFoundError):
        collect_files([tmp_path / "nope"])


def test_cli_input_errors_exit_2_without_downloading(tmp_path, monkeypatch, capsys):
    def fail(*args, **kwargs):
        raise AssertionError("should not download")

    monkeypatch.setattr(cli, "ensure_server", fail)
    (tmp_path / "a.py").write_text("x = 1\n")
    bad_rules = tmp_path / "rules.json"
    bad_rules.write_text("{not json")
    assert cli.main([str(tmp_path / "nope")]) == 2
    assert cli.main(["--rules", str(bad_rules), str(tmp_path)]) == 2
    assert cli.main(["--rules", str(tmp_path / "missing.json"), str(tmp_path)]) == 2
    empty = tmp_path / "empty"
    empty.mkdir()
    assert cli.main([str(empty)]) == 0


@pytest.mark.parametrize(("flags", "expected"), [([], 1), (["--exit-zero"], 0), (["-e"], 0)])
def test_cli_exit_status_with_issues(tmp_path, monkeypatch, capsys, flags, expected):
    monkeypatch.setattr(cli, "ensure_server", lambda *args: FakeServer(root=tmp_path, java=Path("java")))
    (tmp_path / "a.py").write_text("x = 1\n")
    assert cli.main([*flags, "--workspace", str(tmp_path), str(tmp_path / "a.py")]) == expected
    assert "fake:S1" in capsys.readouterr().out


def test_cli_exit_zero_still_reports_a_failed_analysis(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(cli, "ensure_server", lambda *args: FakeServer(root=tmp_path, java=Path("java")))
    (tmp_path / "a.py").write_text("SILENT\n")
    assert cli.main(["--exit-zero", "--timeout", "1", "--workspace", str(tmp_path), str(tmp_path / "a.py")]) == 2
    assert "did not finish in time" in capsys.readouterr().err
