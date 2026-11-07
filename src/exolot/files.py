"""Find the files to analyze, and the language the server should analyze
each one as."""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

from .exclude import Exclude, is_excluded

# VS Code language ids, which is what the server expects in didOpen.
LANGUAGE_IDS = {
    ".py": "python",
    ".pyi": "python",
    ".js": "javascript",
    ".mjs": "javascript",
    ".cjs": "javascript",
    ".jsx": "javascriptreact",
    ".ts": "typescript",
    ".mts": "typescript",
    ".cts": "typescript",
    ".tsx": "typescriptreact",
    ".vue": "vue",
    ".css": "css",
    ".scss": "scss",
    ".less": "less",
    ".html": "html",
    ".htm": "html",
    ".xml": "xml",
    ".java": "java",
    ".php": "php",
    ".go": "go",
    ".cs": "csharp",
    ".c": "c",
    ".h": "c",
    ".cpp": "cpp",
    ".cc": "cpp",
    ".cxx": "cpp",
    ".hpp": "cpp",
    ".m": "objective-c",
    ".mm": "objective-cpp",
    ".yaml": "yaml",
    ".yml": "yaml",
    ".json": "json",
    ".tf": "terraform",
    ".bicep": "bicep",
    ".sh": "shellscript",
    ".bash": "shellscript",
    ".properties": "properties",
}

SKIP_DIRS = {".git", ".hg", ".svn", "node_modules", "__pycache__", ".venv", "venv", ".tox", ".mypy_cache"}
MAX_FILE_SIZE = 2 * 1024 * 1024


def language_id(path: Path) -> str:
    if path.name == "Dockerfile" or path.name.startswith("Dockerfile."):
        return "dockerfile"
    return LANGUAGE_IDS.get(path.suffix.lower(), "plaintext")


def collect_files(paths: list[Path], exclude: list[Exclude] | tuple[Exclude, ...] = ()) -> list[Path]:
    """Expand directories into the files under them, skipping ignored and
    binary files and those that exclude skips, including ones named in paths."""
    result: list[Path] = []
    seen: set[Path] = set()
    for path in paths:
        if not path.exists():
            raise FileNotFoundError(f"no such file or directory: {path}")
        candidates = [path] if path.is_file() else _list_dir(path)
        for f in candidates:
            # Match both the path as listed and its target, so that neither
            # a symlink nor a symlinked directory slips past a glob.
            listed = f.absolute()
            f = f.resolve()
            if f in seen or is_excluded(listed, exclude) or is_excluded(f, exclude):
                continue
            if _is_analyzable(f):
                seen.add(f)
                result.append(f)
    return result


def _list_dir(directory: Path) -> list[Path]:
    git = shutil.which("git")
    if git:
        proc = subprocess.run(
            [git, "ls-files", "-z", "--cached", "--others", "--exclude-standard"],
            cwd=directory,
            capture_output=True,
        )
        if proc.returncode == 0:
            # Names as the filesystem has them, which needn't be UTF-8.
            return [directory / os.fsdecode(name) for name in proc.stdout.split(b"\0") if name]
    files: list[Path] = []
    for dirpath, dirnames, filenames in os.walk(directory):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS and not d.startswith(".")]
        files.extend(Path(dirpath) / name for name in filenames)
    return files


def _is_analyzable(path: Path) -> bool:
    try:
        if not path.is_file() or path.stat().st_size > MAX_FILE_SIZE:
            return False
        with open(path, "rb") as f:
            return b"\0" not in f.read(8192)
    except OSError:
        return False
