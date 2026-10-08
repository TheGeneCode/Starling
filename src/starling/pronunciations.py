"""
The user's pronunciation guide: rewrite words the voice gets wrong before synthesis.

The guide is a TOML file of `"written form" = "spoken form"` pairs, e.g.
`SCOTUS = "Scotus"`. Matching is case-sensitive and whole-word, one pass, longest key
first, so one replacement is never re-matched by another key.
"""

from __future__ import annotations

import re
import tomllib
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import TYPE_CHECKING, Final

from starling.config import ConfigError

if TYPE_CHECKING:
    from collections.abc import Mapping
    from pathlib import Path


def _key_pattern(key: str) -> str:
    """
    Return the regex for one key, with a word boundary only where its edge is a word char.

    "C++" must not match inside "AC++", but "™" has no word edges and must still match
    in "Brand™". Lookarounds rather than a regex word-boundary so punctuation edges behave.
    """
    start = r"(?<!\w)" if re.match(r"\w", key[0]) else ""
    end = r"(?!\w)" if re.match(r"\w", key[-1]) else ""
    return f"{start}{re.escape(key)}{end}"


@dataclass(frozen=True, slots=True)
class PronunciationGuide:
    """Written-form -> spoken-form replacements, compiled into one alternation."""

    replacements: Mapping[str, str] = field(default_factory=lambda: MappingProxyType({}))
    pattern: re.Pattern[str] | None = None

    def __len__(self) -> int:
        """Return the number of entries, so an empty guide is falsy."""
        return len(self.replacements)

    @classmethod
    def from_mapping(cls, replacements: Mapping[str, str]) -> PronunciationGuide:
        """Compile ``replacements`` into a guide; an empty mapping yields an empty guide."""
        if not replacements:
            return cls()
        # Longest first: "NASA JPL" must win over "NASA" when both are keys.
        keys = sorted(replacements, key=len, reverse=True)
        alternation = "|".join(_key_pattern(key) for key in keys)
        return cls(
            MappingProxyType(dict(replacements)),
            re.compile(alternation),
        )

    def apply(self, text: str) -> str:
        """Return ``text`` with every guide entry replaced in a single pass."""
        if self.pattern is None:
            return text
        return self.pattern.sub(lambda m: self.replacements[m.group(0)], text)


EMPTY_GUIDE: Final = PronunciationGuide()


def parse_pronunciations(raw: str, *, source: str) -> PronunciationGuide:
    """
    Parse the guide's TOML text into a PronunciationGuide.

    ``source`` is the file name only (never the full path) and appears in every error
    message. Raises ConfigError for invalid TOML, non-string values, blank keys, and
    keys that collide after surrounding whitespace is stripped. An empty value is
    allowed: it deletes the word.
    """
    try:
        data = tomllib.loads(raw)
    except tomllib.TOMLDecodeError as exc:
        msg = f"{source} is not valid TOML: {exc}"
        raise ConfigError(msg) from exc

    result: dict[str, str] = {}
    for key, value in data.items():
        if not isinstance(value, str):
            msg = f'{source}: {key!r} must map to a quoted string, e.g. SCOTUS = "Scotus".'
            raise ConfigError(msg)
        stripped = key.strip()
        if not stripped:
            msg = f"{source} has a blank entry; every entry needs the word as written on the left."
            raise ConfigError(msg)
        if stripped in result:
            msg = f"{source} lists {stripped!r} twice."
            raise ConfigError(msg)
        result[stripped] = value
    return PronunciationGuide.from_mapping(result)


def load_pronunciations(path: Path, *, required: bool) -> PronunciationGuide:
    """
    Load the guide at ``path``.

    A missing file is an empty guide unless ``required`` (the user named the path
    explicitly), in which case it is a ConfigError. Unreadable files, including a
    directory at the path, are also a ConfigError.
    """
    if not path.exists():
        if required:
            msg = (
                f"STARLING_PRONUNCIATIONS points at {path.name}, which does not exist. "
                "Create it, or unset the variable."
            )
            raise ConfigError(msg)
        return EMPTY_GUIDE
    try:
        # utf-8-sig: Windows Notepad can save a BOM, which tomllib rejects.
        raw = path.read_text(encoding="utf-8-sig")
    except (OSError, UnicodeDecodeError) as exc:
        msg = f"Could not read {path.name}: {exc}"
        raise ConfigError(msg) from exc
    return parse_pronunciations(raw, source=path.name)
