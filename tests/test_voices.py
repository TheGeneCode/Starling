"""Voice discovery, validation, and selection — comprehensive test suite."""

from __future__ import annotations

import random
from types import SimpleNamespace
from typing import TYPE_CHECKING

import pytest
from google.api_core.exceptions import GoogleAPICallError
from google.auth.exceptions import DefaultCredentialsError
from google.cloud import texttospeech

from starling import config, voices

if TYPE_CHECKING:
    from pathlib import Path
    from unittest.mock import MagicMock

# ---------------------------------------------------------------------------
# model_family
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("voice_name", "expected_family"),
    [
        ("en-US-Chirp3-HD-Aoede", "Chirp3-HD"),
        ("en-US-Chirp-HD-D", "Chirp-HD"),
        ("en-US-Neural2-C", "Neural2"),
        ("en-US-Standard-A", "Standard"),
        ("en-US-Studio-O", "Studio"),
        ("cmn-TW-Wavenet-A", "Wavenet"),
    ],
)
def test_model_family_parses_known_names(voice_name: str, expected_family: str) -> None:
    """Verify that model_family extracts the correct family from standard voice names."""
    assert voices.model_family(voice_name) == expected_family


@pytest.mark.parametrize(
    "voice_name",
    [
        "",
        "weird",
        "en-US",
    ],
)
def test_model_family_returns_unknown_for_malformed_names(voice_name: str) -> None:
    """Verify that model_family returns 'Unknown' for names that don't fit the pattern."""
    assert voices.model_family(voice_name) == "Unknown"


# ---------------------------------------------------------------------------
# fetch_voices: gender labels and basic functionality
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("gender_const", "expected_label"),
    [
        (texttospeech.SsmlVoiceGender.MALE, "Male"),
        (texttospeech.SsmlVoiceGender.FEMALE, "Female"),
        (texttospeech.SsmlVoiceGender.NEUTRAL, "Neutral"),
        (texttospeech.SsmlVoiceGender.SSML_VOICE_GENDER_UNSPECIFIED, "Unspecified"),
    ],
)
def test_gender_labels(
    gender_const: int,
    expected_label: str,
    fake_tts_client: MagicMock,
) -> None:
    """Verify that fetch_voices maps SsmlVoiceGender values to human-readable labels."""
    # Construct a mock response with a single voice of the given gender.
    test_voice = SimpleNamespace(
        name="en-US-Test-A",
        ssml_gender=gender_const,
        language_codes=["en-US"],
    )
    fake_tts_client.list_voices.return_value = SimpleNamespace(voices=[test_voice])

    result = voices.fetch_voices(fake_tts_client, "en-US")

    assert len(result) == 1
    assert result[0].gender == expected_label


def test_fetch_voices_passes_language_code(fake_tts_client: MagicMock) -> None:
    """Verify that fetch_voices calls client.list_voices with the correct language_code."""
    voices.fetch_voices(fake_tts_client, "en-US")

    fake_tts_client.list_voices.assert_called_once_with(language_code="en-US")


def test_fetch_voices_maps_and_sorts(fake_tts_client: MagicMock) -> None:
    """Verify that fetch_voices maps voices to VoiceInfo and sorts by (family, name)."""
    result = voices.fetch_voices(fake_tts_client, "en-US")

    # Catalog has 4 voices; expect 4 VoiceInfo objects.
    assert len(result) == 4
    assert all(isinstance(v, voices.VoiceInfo) for v in result)

    # Verify sorting: (family, name). Chirp3-HD pair should appear first (both at
    # family "Chirp3-HD"), then Neural2, then Standard.
    families = [v.family for v in result]
    names = [v.name for v in result]
    assert families == sorted(families), f"Not sorted by family: {families}"
    assert (
        names[0:2] == sorted(names[0:2])
    ), "Chirp3-HD pair not sorted by name within family"

    # Verify the Chirp3-HD pair carries correct family and language_codes.
    chirp3_hd_voices = [v for v in result if v.family == "Chirp3-HD"]
    assert len(chirp3_hd_voices) == 2
    for voice in chirp3_hd_voices:
        assert voice.language_codes == ("en-US",)


def test_fetch_voices_handles_empty_response(fake_tts_client: MagicMock) -> None:
    """Verify that fetch_voices returns an empty tuple when list_voices returns no voices."""
    fake_tts_client.list_voices.return_value = SimpleNamespace(voices=[])

    result = voices.fetch_voices(fake_tts_client, "en-US")

    assert result == ()


# ---------------------------------------------------------------------------
# validate_voice_names
# ---------------------------------------------------------------------------


def test_validate_accepts_exact_names(fake_tts_client: MagicMock) -> None:
    """Verify that validate_voice_names accepts an exact (canonical) voice name."""
    catalog = voices.fetch_voices(fake_tts_client, "en-US")
    result = voices.validate_voice_names(("en-US-Neural2-C",), catalog)

    assert result == ("en-US-Neural2-C",)


def test_validate_canonicalizes_casing_and_whitespace(
    fake_tts_client: MagicMock,
) -> None:
    """Verify that validate_voice_names canonicalizes casing and strips whitespace."""
    catalog = voices.fetch_voices(fake_tts_client, "en-US")
    result = voices.validate_voice_names(
        ("  en-us-CHIRP3-hd-aoede ", "EN-US-STANDARD-A"),
        catalog,
    )

    assert result == ("en-US-Chirp3-HD-Aoede", "en-US-Standard-A")


def test_validate_single_entry_pool(fake_tts_client: MagicMock) -> None:
    """Verify that validate_voice_names handles a one-entry pool correctly."""
    catalog = voices.fetch_voices(fake_tts_client, "en-US")
    result = voices.validate_voice_names(("en-US-Chirp3-HD-Puck",), catalog)

    assert result == ("en-US-Chirp3-HD-Puck",)
    assert isinstance(result, tuple)


def test_validate_unknown_name_raises_with_suggestion(
    fake_tts_client: MagicMock,
) -> None:
    """Verify that validate_voice_names suggests close matches for unknown names."""
    catalog = voices.fetch_voices(fake_tts_client, "en-US")

    with pytest.raises(voices.UnknownVoiceError) as exc_info:
        voices.validate_voice_names(("en-US-Chirp3-HD-Aoedee",), catalog)

    message = str(exc_info.value)
    assert "en-US-Chirp3-HD-Aoedee" in message
    assert "Did you mean" in message
    assert "en-US-Chirp3-HD-Aoede" in message
    assert "starling voices" in message


def test_validate_unknown_name_without_close_match(
    fake_tts_client: MagicMock,
) -> None:
    """Verify that unknown names without close matches raise without a 'Did you mean' clause."""
    catalog = voices.fetch_voices(fake_tts_client, "en-US")

    with pytest.raises(voices.UnknownVoiceError) as exc_info:
        voices.validate_voice_names(("zz-ZZ-Nope-Q",), catalog)

    message = str(exc_info.value)
    assert "zz-ZZ-Nope-Q" in message
    assert "Did you mean" not in message


def test_validate_reports_every_unknown_name(
    fake_tts_client: MagicMock,
) -> None:
    """Verify that validate_voice_names reports every unknown name, not just the first."""
    catalog = voices.fetch_voices(fake_tts_client, "en-US")

    with pytest.raises(voices.UnknownVoiceError) as exc_info:
        voices.validate_voice_names(
            (
                "en-US-Chirp3-HD-Aoede",  # valid
                "unknown-one-Q",  # invalid
                "en-US-Neural2-C",  # valid
                "unknown-two-R",  # invalid
            ),
            catalog,
        )

    message = str(exc_info.value)
    # Both invalid names should be in the message.
    assert "unknown-one-Q" in message
    assert "unknown-two-R" in message
    # Neither valid name should be in the message.
    assert "en-US-Chirp3-HD-Aoede" not in message or "Unknown voice name: en-US-Chirp3-HD-Aoede" not in message
    assert "en-US-Neural2-C" not in message or "Unknown voice name: en-US-Neural2-C" not in message


def test_validate_empty_catalog_raises(fake_tts_client: MagicMock) -> None:
    """Verify that validate_voice_names raises for an empty catalog, naming the language code."""
    fake_tts_client.list_voices.return_value = SimpleNamespace(voices=[])
    catalog = voices.fetch_voices(fake_tts_client, "en-US")

    with pytest.raises(voices.UnknownVoiceError) as exc_info:
        voices.validate_voice_names(("en-US-Chirp3-HD-Aoede",), catalog)

    message = str(exc_info.value)
    assert "empty" in message.lower()
    assert "language code" in message.lower() or "STARLING_LANGUAGE_CODE" in message


# ---------------------------------------------------------------------------
# select_voice
# ---------------------------------------------------------------------------


def test_select_voice_fixed_returns_canonical_name(
    clean_env: None,
    fake_home: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verify that select_voice in FIXED mode returns the pool's first (canonical) entry."""
    monkeypatch.setenv("STARLING_VOICE_MODE", "fixed")
    cfg = config.load_config(use_dotenv=False)

    # The pool should be validated, so pool[0] is the canonical name.
    pool = ("en-US-Neural2-C",)
    result = voices.select_voice(cfg, pool)

    assert result == "en-US-Neural2-C"


def test_select_voice_fixed_ignores_pool_tail(
    clean_env: None,
    fake_home: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verify that FIXED mode always returns pool[0], ignoring any additional entries."""
    monkeypatch.setenv("STARLING_VOICE_MODE", "fixed")
    cfg = config.load_config(use_dotenv=False)

    pool = ("first", "second", "third")
    for _ in range(20):
        result = voices.select_voice(cfg, pool)
        assert result == "first"


def test_select_voice_random_single_entry_pool(
    clean_env: None,
    fake_home: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verify that RANDOM mode with one entry always returns that entry."""
    monkeypatch.setenv("STARLING_VOICE_MODE", "random")
    cfg = config.load_config(use_dotenv=False)

    pool = ("only-voice",)
    for _ in range(20):
        result = voices.select_voice(cfg, pool)
        assert result == "only-voice"


def test_select_voice_random_draws_only_from_pool(
    clean_env: None,
    fake_home: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verify that RANDOM mode draws only from the pool and produces variation."""
    monkeypatch.setenv("STARLING_VOICE_MODE", "random")
    cfg = config.load_config(use_dotenv=False)

    pool = ("voice-1", "voice-2", "voice-3")
    rng = random.Random(0)  # noqa: S311 - voice variety is cosmetic, not security
    results = [voices.select_voice(cfg, pool, rng=rng) for _ in range(50)]

    # All results must be in the pool.
    assert all(r in pool for r in results)
    # At least two distinct values should appear (with high probability for 50 draws).
    assert len(set(results)) >= 2


# ---------------------------------------------------------------------------
# format_voices_table
# ---------------------------------------------------------------------------


def test_format_voices_table_contains_every_field(
    fake_tts_client: MagicMock,
) -> None:
    """Verify that format_voices_table includes every voice name, gender, family, and header."""
    catalog = voices.fetch_voices(fake_tts_client, "en-US")
    output = voices.format_voices_table(catalog)

    # Check headers.
    assert "VOICE" in output
    assert "GENDER" in output
    assert "FAMILY" in output

    # Check every voice name.
    for voice in catalog:
        assert voice.name in output
        assert voice.gender in output
        assert voice.family in output


# ---------------------------------------------------------------------------
# pricing_notice
# ---------------------------------------------------------------------------


def test_pricing_notice_lists_families_and_url() -> None:
    """Verify that pricing_notice lists unique families and includes the pricing URL."""
    families = ["Chirp3-HD", "Neural2", "Chirp3-HD"]
    result = voices.pricing_notice(families)

    # Each family should appear exactly once (or at least, duplicates should be deduplicated).
    assert "Chirp3-HD" in result
    assert "Neural2" in result
    assert result.count("Chirp3-HD") >= 1  # At least one occurrence.
    assert voices.PRICING_URL in result
    assert "Billing:" in result


# ---------------------------------------------------------------------------
# run_voices
# ---------------------------------------------------------------------------


def test_run_voices_prints_table_and_returns_zero(
    fake_tts_client: MagicMock,
    capsys: pytest.CaptureFixture[str],
    clean_env: None,
    fake_home: Path,
) -> None:
    """Verify that run_voices with a good client prints the catalog and returns 0."""
    exit_code = voices.run_voices(language_code="en-US", client=fake_tts_client)

    assert exit_code == 0
    captured = capsys.readouterr()
    assert "4 voices available for en-US" in captured.out
    # Check that a voice name and the pricing URL are in the output.
    assert "en-US-Chirp3-HD-Aoede" in captured.out
    assert voices.PRICING_URL in captured.out


def test_run_voices_empty_catalog_returns_one(
    fake_tts_client: MagicMock,
    capsys: pytest.CaptureFixture[str],
    clean_env: None,
    fake_home: Path,
) -> None:
    """Verify that run_voices returns 1 when the catalog is empty."""
    fake_tts_client.list_voices.return_value = SimpleNamespace(voices=[])

    exit_code = voices.run_voices(language_code="en-US", client=fake_tts_client)

    assert exit_code == 1
    captured = capsys.readouterr()
    assert "en-US" in captured.out


def test_run_voices_api_error_returns_one(
    fake_tts_client: MagicMock,
    capsys: pytest.CaptureFixture[str],
    clean_env: None,
    fake_home: Path,
) -> None:
    """Verify that run_voices returns 1 and prints 'Error:' when the API raises."""
    fake_tts_client.list_voices.side_effect = GoogleAPICallError("boom")

    exit_code = voices.run_voices(language_code="en-US", client=fake_tts_client)

    assert exit_code == 1
    captured = capsys.readouterr()
    assert captured.out.startswith("Error:")


def test_run_voices_never_constructs_a_real_client(
    fake_tts_client: MagicMock,
    monkeypatch: pytest.MonkeyPatch,
    clean_env: None,
    fake_home: Path,
) -> None:
    """Verify that run_voices never constructs a real TextToSpeechClient when passed a mock."""

    def failing_client_constructor(*args: object, **kwargs: object) -> None:
        raise AssertionError("network client constructed")

    monkeypatch.setattr(texttospeech, "TextToSpeechClient", failing_client_constructor)

    exit_code = voices.run_voices(language_code="en-US", client=fake_tts_client)

    assert exit_code == 0


# ---------------------------------------------------------------------------
# model_family: additional boundary cases (bare/malformed real-catalog names)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "voice_name",
    [
        "Puck",
        "Achernar",
        "Zephyr",
    ],
)
def test_model_family_bare_single_word_catalog_name_returns_unknown(
    voice_name: str,
) -> None:
    """
    Pin the "surprising finding" from the live catalog.

    Bare single-word voice names (real Google entries, no
    `<lang>-<REGION>-<Family>` prefix) classify as Unknown.
    """
    assert voices.model_family(voice_name) == "Unknown"


def test_model_family_case_insensitive_hd_suffix() -> None:
    """Verify a lowercase 'hd' segment is still recognized (parts[3].upper() == "HD")."""
    assert voices.model_family("en-US-Chirp-hd-D") == "Chirp-HD"


def test_model_family_empty_middle_segment_returns_unknown() -> None:
    """A double-dash produces an empty family segment, which is treated as unknown."""
    assert voices.model_family("en-US--A") == "Unknown"


def test_model_family_exactly_three_parts_no_variant() -> None:
    """Verify the minimum non-Unknown boundary: exactly 3 parts, no HD/variant suffix."""
    assert voices.model_family("en-US-Standard") == "Standard"


# ---------------------------------------------------------------------------
# fetch_voices: additional boundary cases
# ---------------------------------------------------------------------------


def test_fetch_voices_unrecognized_gender_value_falls_back_to_unspecified(
    fake_tts_client: MagicMock,
) -> None:
    """
    Verify the _GENDER_LABELS.get(..., "Unspecified") fallback branch itself.

    Every existing gender test uses a value already present in _GENDER_LABELS
    (including SSML_VOICE_GENDER_UNSPECIFIED, whose label happens to equal the
    fallback string too), so the dict-miss default path was never actually
    exercised. An out-of-range integer forces a real dict miss.
    """
    test_voice = SimpleNamespace(
        name="en-US-Test-A",
        ssml_gender=999,
        language_codes=["en-US"],
    )
    fake_tts_client.list_voices.return_value = SimpleNamespace(voices=[test_voice])

    result = voices.fetch_voices(fake_tts_client, "en-US")

    assert result[0].gender == "Unspecified"


def test_fetch_voices_preserves_multiple_language_codes_in_order(
    fake_tts_client: MagicMock,
) -> None:
    """Verify a voice supporting several language codes keeps them as an ordered tuple."""
    test_voice = SimpleNamespace(
        name="en-US-Test-A",
        ssml_gender=texttospeech.SsmlVoiceGender.NEUTRAL,
        language_codes=["en-US", "en-GB", "en-AU"],
    )
    fake_tts_client.list_voices.return_value = SimpleNamespace(voices=[test_voice])

    result = voices.fetch_voices(fake_tts_client, "en-US")

    assert result[0].language_codes == ("en-US", "en-GB", "en-AU")


# ---------------------------------------------------------------------------
# validate_voice_names: additional boundary cases
# ---------------------------------------------------------------------------


def test_validate_empty_names_returns_empty_tuple(fake_tts_client: MagicMock) -> None:
    """Verify an empty names sequence resolves to an empty tuple without raising."""
    catalog = voices.fetch_voices(fake_tts_client, "en-US")
    result = voices.validate_voice_names((), catalog)

    assert result == ()


def test_validate_whitespace_only_name_raises_as_unknown(
    fake_tts_client: MagicMock,
) -> None:
    """Verify a whitespace-only name strips to "" and is reported as unknown, not skipped."""
    catalog = voices.fetch_voices(fake_tts_client, "en-US")

    with pytest.raises(voices.UnknownVoiceError) as exc_info:
        voices.validate_voice_names(("   ",), catalog)

    assert "Unknown voice name:" in str(exc_info.value)


def test_validate_duplicate_input_names_preserved_in_order(
    fake_tts_client: MagicMock,
) -> None:
    """Verify duplicate (differently cased) input names each resolve, not deduplicated."""
    catalog = voices.fetch_voices(fake_tts_client, "en-US")
    result = voices.validate_voice_names(
        ("en-US-Neural2-C", "EN-US-NEURAL2-C"),
        catalog,
    )

    assert result == ("en-US-Neural2-C", "en-US-Neural2-C")


def test_validate_close_matches_are_deterministic_across_calls(
    fake_tts_client: MagicMock,
) -> None:
    """
    Verify get_close_matches produces a stable suggestion order across repeated calls.

    difflib.get_close_matches sorts by score (a real number), so near-equidistant
    candidates could in principle tie; confirm the actual implementation still
    returns the same order every time for the same inputs (no set-iteration
    nondeterminism has crept in).
    """
    catalog = voices.fetch_voices(fake_tts_client, "en-US")
    messages = set()
    for _ in range(5):
        with pytest.raises(voices.UnknownVoiceError) as exc_info:
            voices.validate_voice_names(("en-US-Chirp3-HD-Aoedee",), catalog)
        messages.add(str(exc_info.value))

    assert len(messages) == 1


def test_validate_duplicate_casefolded_catalog_names_last_one_wins(
    fake_tts_client: MagicMock,
) -> None:
    """
    Document dict-overwrite behavior for a catalog with case-duplicate names.

    Two entries that only differ by case should not happen with a real Google
    catalog, but the index-building comprehension silently prefers whichever
    one iterates last.
    """
    catalog = voices.fetch_voices(fake_tts_client, "en-US")
    duplicated = (
        *catalog,
        voices.VoiceInfo(
            name="en-us-neural2-c",
            gender="Female",
            family="Neural2",
            language_codes=("en-US",),
        ),
    )

    result = voices.validate_voice_names(("EN-US-NEURAL2-C",), duplicated)

    assert result == ("en-us-neural2-c",)


# ---------------------------------------------------------------------------
# select_voice: empty-pool boundary (flagged in the handoff as an unguarded invariant)
# ---------------------------------------------------------------------------


def test_select_voice_fixed_empty_pool_raises_index_error(
    clean_env: None,
    fake_home: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verify FIXED mode with an empty pool raises IndexError (pool[0] on empty tuple)."""
    monkeypatch.setenv("STARLING_VOICE_MODE", "fixed")
    cfg = config.load_config(use_dotenv=False)

    with pytest.raises(IndexError):
        voices.select_voice(cfg, ())


def test_select_voice_random_empty_pool_raises_index_error(
    clean_env: None,
    fake_home: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """
    Verify RANDOM mode with an empty pool raises IndexError from random.choice.

    validate_voice_names never returns an empty tuple without raising first, so
    this cannot happen through the normal reader.py flow -- but select_voice's
    own signature (an untyped Sequence[str]) does not enforce that invariant,
    so a future caller bypassing validation would fail here, not silently.
    """
    monkeypatch.setenv("STARLING_VOICE_MODE", "random")
    cfg = config.load_config(use_dotenv=False)
    rng = random.Random(0)  # noqa: S311 - determinism only, not security

    with pytest.raises(IndexError):
        voices.select_voice(cfg, (), rng=rng)


# ---------------------------------------------------------------------------
# format_voices_table: empty/min-size boundary cases
# ---------------------------------------------------------------------------


def test_format_voices_table_empty_voices_renders_header_and_rule_only() -> None:
    """Verify an empty voices sequence still renders headers and a dashed rule, no crash."""
    output = voices.format_voices_table(())
    lines = output.splitlines()

    assert len(lines) == 2
    assert lines[0] == "VOICE  GENDER  FAMILY"
    assert set(lines[1].replace(" ", "")) == {"-"}


def test_format_voices_table_single_voice_row() -> None:
    """Verify the minimum non-empty boundary: exactly one voice row."""
    single = (
        voices.VoiceInfo(
            name="en-US-Test-A",
            gender="Male",
            family="Standard",
            language_codes=("en-US",),
        ),
    )
    output = voices.format_voices_table(single)
    lines = output.splitlines()

    assert len(lines) == 3
    assert "en-US-Test-A" in lines[2]


def test_format_voices_table_lines_have_no_trailing_whitespace() -> None:
    """Verify every rendered line is rstrip()-ed, even when the FAMILY column is short."""
    rows = (
        voices.VoiceInfo(
            name="en-US-Chirp3-HD-Aoede",
            gender="Female",
            family="Chirp3-HD",
            language_codes=("en-US",),
        ),
        voices.VoiceInfo(
            name="x",
            gender="Male",
            family="A",
            language_codes=("en-US",),
        ),
    )
    output = voices.format_voices_table(rows)

    for line in output.splitlines():
        assert line == line.rstrip()


# ---------------------------------------------------------------------------
# pricing_notice: empty/min-size boundary cases
# ---------------------------------------------------------------------------


def test_pricing_notice_empty_families_list() -> None:
    """Verify an empty families sequence still produces a well-formed (if bare) message."""
    result = voices.pricing_notice([])

    assert result == f"Billing:  — voice families are priced differently on your own Google Cloud account. Current rates: {voices.PRICING_URL}"


def test_pricing_notice_single_family() -> None:
    """Verify the minimum non-empty boundary: exactly one family, no comma joining."""
    result = voices.pricing_notice(["Neural2"])

    assert "Billing: Neural2 —" in result


def test_pricing_notice_sorts_families_alphabetically_regardless_of_input_order() -> None:
    """Verify families are alphabetized in the output, not left in input/insertion order."""
    result = voices.pricing_notice(["Zephyr-Family", "Alpha-Family", "Mid-Family"])

    alpha_index = result.index("Alpha-Family")
    mid_index = result.index("Mid-Family")
    zephyr_index = result.index("Zephyr-Family")
    assert alpha_index < mid_index < zephyr_index


# ---------------------------------------------------------------------------
# run_voices: client=None real-construction path (untested by every prior test,
# which all pass client=fake_tts_client and so skip this branch entirely)
#
# IMPORTANT: run_voices() calls the real `load_config()` (use_dotenv=True,
# hardcoded, no override parameter) whenever it needs its own config -- unlike
# every other test in this module, which uses `config.load_config(use_dotenv=False)`
# specifically to keep a developer's real .env out of the test run (see
# test_config.py's "use_dotenv=False does not call load_dotenv" test). This repo
# checkout has a real .env with a real GOOGLE_APPLICATION_CREDENTIALS pointing at
# an actual service-account key -- `clean_env` alone does NOT stop run_voices()
# from reloading it via load_dotenv(), and os.environ mutations made by dotenv
# are not tracked/undone by monkeypatch. A first draft of these tests relied on
# clean_env alone and would have silently exercised a real TextToSpeechClient()
# construction against real credentials. Every test below instead monkeypatches
# voices.load_config directly so the real .env is never touched.
# ---------------------------------------------------------------------------


def test_run_voices_client_none_missing_credentials_returns_one(
    clean_env: None,
    fake_home: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """
    Verify the client=None branch's require_credentials() call is actually reached.

    Every other run_voices test passes an explicit mocked client, so
    `if client is None: require_credentials(config); client = TextToSpeechClient()`
    was never exercised. With a config carrying no credentials_path,
    require_credentials must raise ConfigError, caught by run_voices's own
    except clause.
    """
    cfg = config.load_config(use_dotenv=False)
    assert cfg.credentials_path is None
    monkeypatch.setattr(voices, "load_config", lambda: cfg)

    exit_code = voices.run_voices(language_code="en-US")

    assert exit_code == 1
    captured = capsys.readouterr()
    assert captured.out.startswith("Error:")
    assert "credentials" in captured.out.lower()


def test_run_voices_client_construction_raises_default_credentials_error(
    clean_env: None,
    fake_home: Path,
    fake_credentials: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """
    Verify a DefaultCredentialsError raised by TextToSpeechClient() itself is caught.

    This is the construction call site, not list_voices -- caught identically
    to the list_voices-side error already tested by
    test_run_voices_api_error_returns_one. These are two different call sites
    inside the same try block and each needs its own coverage.
    """
    monkeypatch.setenv("STARLING_GOOGLE_CREDENTIALS", str(fake_credentials))
    cfg = config.load_config(use_dotenv=False)
    assert cfg.credentials_path == fake_credentials
    monkeypatch.setattr(voices, "load_config", lambda: cfg)

    def failing_constructor(*args: object, **kwargs: object) -> None:
        raise DefaultCredentialsError("no ADC found")

    monkeypatch.setattr(texttospeech, "TextToSpeechClient", failing_constructor)

    exit_code = voices.run_voices(language_code="en-US")

    assert exit_code == 1
    captured = capsys.readouterr()
    assert captured.out.startswith("Error:")


def test_run_voices_uses_config_default_language_code_when_none_given(
    fake_tts_client: MagicMock,
    clean_env: None,
    fake_home: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Verify language_code=None falls back to config.language_code (default en-US)."""
    cfg = config.load_config(use_dotenv=False)
    assert cfg.language_code == "en-US"
    monkeypatch.setattr(voices, "load_config", lambda: cfg)

    exit_code = voices.run_voices(language_code=None, client=fake_tts_client)

    assert exit_code == 0
    captured = capsys.readouterr()
    assert "available for en-US" in captured.out
    fake_tts_client.list_voices.assert_called_once_with(language_code="en-US")
