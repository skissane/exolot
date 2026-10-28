import subprocess
import sys
from pathlib import Path

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
