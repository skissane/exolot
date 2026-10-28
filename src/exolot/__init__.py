"""Run SonarQube for IDE's language server from the command line."""

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("exolot")
except PackageNotFoundError:
    __version__ = "0.0.0"
