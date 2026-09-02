"""Starling — read saved articles aloud with Google Cloud Text-to-Speech."""

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("starling")
except PackageNotFoundError:  # pragma: no cover - source checkout without an install
    __version__ = "dev"

__all__ = ["__version__"]
