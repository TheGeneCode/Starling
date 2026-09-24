"""Starling — read saved articles aloud with Google Cloud Text-to-Speech."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    __version__: str

__all__ = ["__version__"]


def __getattr__(name: str) -> str:
    """
    Resolve `__version__` on first access (PEP 562), then cache it as a real attribute.

    `importlib.metadata` costs ~60 ms to import, and every `starling.*` import runs this
    module; only `--version` and the update check need the answer.
    """
    if name != "__version__":
        msg = f"module {__name__!r} has no attribute {name!r}"
        raise AttributeError(msg)
    from importlib.metadata import PackageNotFoundError, version  # noqa: PLC0415

    try:
        resolved = version("starling")
    except PackageNotFoundError:  # pragma: no cover - source checkout without an install
        resolved = "dev"
    globals()["__version__"] = resolved
    return resolved
