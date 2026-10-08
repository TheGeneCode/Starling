from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from starling.config import ConfigError
from starling.pronunciations import (
    EMPTY_GUIDE,
    PronunciationGuide,
    load_pronunciations,
    parse_pronunciations,
)

if TYPE_CHECKING:
    from pathlib import Path


def test_apply_replaces_acronym() -> None:
    """Test that a whole-word acronym is replaced with its spoken form."""
    guide = PronunciationGuide.from_mapping({"SCOTUS": "Scotus"})
    assert guide.apply("SCOTUS ruled.") == "Scotus ruled."


def test_apply_is_case_sensitive() -> None:
    """Test that a key only matches the exact casing it was written with."""
    guide = PronunciationGuide.from_mapping({"SCOTUS": "Scotus"})
    assert guide.apply("scotus and Scotus") == "scotus and Scotus"


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("SCOTUSblog", "SCOTUSblog"),
        ("SCOTUS's", "Scotus's"),
        ("(SCOTUS)", "(Scotus)"),
        ("SCOTUS.", "Scotus."),
        ("XSCOTUS", "XSCOTUS"),
    ],
)
def test_apply_whole_word_boundaries(text: str, expected: str) -> None:
    """Test that a key is replaced only at word edges, not inside a longer word."""
    guide = PronunciationGuide.from_mapping({"SCOTUS": "Scotus"})
    assert guide.apply(text) == expected


def test_apply_longest_key_wins() -> None:
    """Test that the longer of two overlapping keys is the one replaced."""
    guide = PronunciationGuide.from_mapping({"NASA": "Nasa", "NASA JPL": "Nasa J P L"})
    assert guide.apply("NASA JPL and NASA") == "Nasa J P L and Nasa"


def test_apply_single_pass_does_not_cascade() -> None:
    """Test that a replacement's output is not matched again by another key."""
    guide = PronunciationGuide.from_mapping({"A1": "B2", "B2": "C3"})
    assert guide.apply("A1 B2") == "B2 C3"


def test_apply_punctuated_key() -> None:
    """Test that a key ending in punctuation matches at a word edge."""
    guide = PronunciationGuide.from_mapping({"C++": "C plus plus"})
    assert guide.apply("I like C++.") == "I like C plus plus."


def test_apply_regex_metachars_are_literal() -> None:
    """Test that regex metacharacters in a key match literally, not as patterns."""
    guide = PronunciationGuide.from_mapping({"a.b": "x"})
    assert guide.apply("aXb a.b") == "aXb x"


@pytest.mark.parametrize(
    ("key", "spoken", "text", "expected"),
    [
        # Leading punctuation, word-char right edge: only the right edge is bounded.
        ("#1", "one", "#10 #1", "#10 one"),
        # Non-ASCII word char at both edges: \w is Unicode-aware, so "café" is not "é".
        ("é", "e", "café é", "café e"),
        # Single-character word key must not fire inside other words.
        ("I", "one", "I In I.", "one In one."),
    ],
)
def test_apply_key_edge_handling(key: str, spoken: str, text: str, expected: str) -> None:
    """Test that boundaries are applied only on the edges of a key that are word chars."""
    guide = PronunciationGuide.from_mapping({key: spoken})
    assert guide.apply(text) == expected


def test_apply_mixed_bounded_and_unbounded_keys_longest_first() -> None:
    """Test that a longer word-edged key beats a shorter unbounded key that is its suffix."""
    guide = PronunciationGuide.from_mapping({"™": "", "Brand™": "B"})
    assert guide.apply("Brand™ x™") == "B x"


def test_apply_replacement_backslashes_are_literal() -> None:
    """Test that backslash sequences in a spoken form are not treated as regex group references."""
    guide = PronunciationGuide.from_mapping({"A": r"\1 \g<0>"})
    assert guide.apply("A") == r"\1 \g<0>"


def test_apply_empty_value_deletes_word() -> None:
    """Test that an empty spoken form removes the word from the text."""
    guide = PronunciationGuide.from_mapping({"™": ""})
    assert guide.apply("Brand™ name") == "Brand name"


def test_empty_guide_is_identity_and_falsy() -> None:
    """Test that EMPTY_GUIDE leaves text unchanged and reports zero entries."""
    text = "Nothing to see here."
    assert EMPTY_GUIDE.apply(text) == text
    assert not EMPTY_GUIDE
    assert len(EMPTY_GUIDE) == 0


def test_guide_replacements_are_read_only() -> None:
    """Test that the replacements mapping cannot be mutated after compilation."""
    guide = PronunciationGuide.from_mapping({"SCOTUS": "Scotus"})
    with pytest.raises(TypeError):
        guide.replacements["NASA"] = "Nasa"  # type: ignore[index]


def test_parse_valid_file() -> None:
    """Test that a well-formed guide parses into one entry per TOML key."""
    guide = parse_pronunciations('SCOTUS = "Scotus"\n"C++" = "C plus plus"\n', source="p.toml")
    assert len(guide) == 2


def test_parse_invalid_toml_raises() -> None:
    """Test that unquoted TOML values raise a ConfigError naming the file."""
    with pytest.raises(ConfigError) as exc:
        parse_pronunciations("SCOTUS = Scotus", source="p.toml")
    assert "p.toml" in str(exc.value)
    assert "not valid TOML" in str(exc.value)


def test_parse_duplicate_key_raises() -> None:
    """Test that a key written twice in the TOML raises a ConfigError."""
    with pytest.raises(ConfigError):
        parse_pronunciations('A = "x"\nA = "y"', source="p.toml")


@pytest.mark.parametrize(
    "raw",
    [
        "SCOTUS = 1",
        'SCOTUS = ["a"]',
        '[SCOTUS]\nx = "y"',
    ],
)
def test_parse_non_string_value_raises(raw: str) -> None:
    """Test that a non-string value raises a ConfigError naming the key."""
    with pytest.raises(ConfigError, match="'SCOTUS'"):
        parse_pronunciations(raw, source="p.toml")


def test_parse_blank_key_raises() -> None:
    """Test that a key containing only whitespace raises a ConfigError."""
    with pytest.raises(ConfigError):
        parse_pronunciations('"  " = "x"', source="p.toml")


def test_parse_duplicate_after_strip_raises() -> None:
    """Test that keys colliding after whitespace is stripped raise a ConfigError."""
    with pytest.raises(ConfigError, match="twice"):
        parse_pronunciations('"SCOTUS" = "a"\n" SCOTUS " = "b"', source="p.toml")


def test_parse_empty_file_is_empty_guide() -> None:
    """Test that an empty TOML file yields a falsy guide rather than an error."""
    guide = parse_pronunciations("", source="p.toml")
    assert not guide


def test_load_missing_optional_returns_empty(tmp_path: Path) -> None:
    """Test that a missing optional guide file loads as EMPTY_GUIDE."""
    assert load_pronunciations(tmp_path / "none.toml", required=False) is EMPTY_GUIDE


def test_load_missing_required_raises_without_full_path(tmp_path: Path) -> None:
    """Test that a missing required guide raises an error showing only the file name."""
    with pytest.raises(ConfigError) as exc:
        load_pronunciations(tmp_path / "none.toml", required=True)
    message = str(exc.value)
    assert "none.toml" in message
    assert str(tmp_path) not in message


def test_load_tolerates_utf8_bom(tmp_path: Path) -> None:
    """Test that a guide saved with a UTF-8 byte order mark still parses."""
    path = tmp_path / "pronunciations.toml"
    path.write_text('SCOTUS = "Scotus"\n', encoding="utf-8-sig")
    assert len(load_pronunciations(path, required=True)) == 1


def test_load_directory_raises_config_error(tmp_path: Path) -> None:
    """Test that a directory at the guide path raises a ConfigError."""
    path = tmp_path / "dir.toml"
    path.mkdir()
    with pytest.raises(ConfigError):
        load_pronunciations(path, required=True)


def test_load_invalid_utf8_raises_config_error(tmp_path: Path) -> None:
    """Test that a guide that is not valid UTF-8 raises a ConfigError."""
    path = tmp_path / "pronunciations.toml"
    path.write_bytes(b"\xff\xfe\x00bad")
    with pytest.raises(ConfigError):
        load_pronunciations(path, required=True)
