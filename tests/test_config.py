"""Configuration loading and validation for Starling — comprehensive test suite."""

from __future__ import annotations

import os
from typing import TYPE_CHECKING

import pytest

from starling import config

if TYPE_CHECKING:
    from pathlib import Path


# ---------------------------------------------------------------------------
# load_config defaults
# ---------------------------------------------------------------------------


def test_defaults_when_nothing_is_set(
    clean_env: None, fake_home: Path
) -> None:
    """Verify all defaults when no env vars or .env file are present."""
    cfg = config.load_config(use_dotenv=False)

    assert cfg.home_dir == fake_home / "Starling"
    assert cfg.input_dir == fake_home / "Starling" / "input"
    assert cfg.output_dir == fake_home / "Starling" / "output"
    assert cfg.archive_dir == fake_home / "Starling" / "archive"
    assert cfg.usage_log_path == fake_home / "Starling" / "logs" / "usage.log"
    assert cfg.error_log_path == fake_home / "Starling" / "logs" / "errors.log"
    assert cfg.language_code == "en-US"
    assert cfg.voice_mode is config.VoiceMode.RANDOM
    assert cfg.voice_name == config.DEFAULT_VOICE_NAME
    assert cfg.voice_pool == config.DEFAULT_VOICE_POOL
    assert len(cfg.voice_pool) == 22
    assert cfg.credentials_path is None


def test_home_override_relocates_every_derived_path(
    clean_env: None, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Verify that STARLING_HOME relocates all five derived paths together."""
    custom_home = tmp_path / "custom"
    monkeypatch.setenv("STARLING_HOME", str(custom_home))

    cfg = config.load_config(use_dotenv=False)

    # All five derived paths must be under the custom home.
    assert cfg.input_dir.is_relative_to(custom_home)
    assert cfg.output_dir.is_relative_to(custom_home)
    assert cfg.archive_dir.is_relative_to(custom_home)
    assert cfg.usage_log_path.is_relative_to(custom_home)
    assert cfg.error_log_path.is_relative_to(custom_home)


def test_explicit_dir_override_beats_home(
    clean_env: None, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Verify that explicit dir env vars override STARLING_HOME."""
    home_path = tmp_path / "home"
    elsewhere_path = tmp_path / "elsewhere"
    monkeypatch.setenv("STARLING_HOME", str(home_path))
    monkeypatch.setenv("STARLING_INPUT_DIR", str(elsewhere_path))

    cfg = config.load_config(use_dotenv=False)

    assert cfg.input_dir == elsewhere_path
    assert cfg.output_dir.is_relative_to(home_path)


def test_tilde_is_expanded(
    clean_env: None, fake_home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Verify that ~ in paths is expanded to the fake home."""
    from pathlib import Path as PathClass

    # Patch expanduser to use fake_home instead of the real user home.
    def fake_expanduser(path_self: PathClass) -> PathClass:
        parts = path_self.parts
        if parts and parts[0] == "~":
            return fake_home / PathClass(*parts[1:])
        return path_self

    monkeypatch.setattr(PathClass, "expanduser", fake_expanduser)
    monkeypatch.setenv("STARLING_INPUT_DIR", "~/box")

    cfg = config.load_config(use_dotenv=False)

    assert cfg.input_dir == fake_home / "box"
    assert "~" not in str(cfg.input_dir)


def test_blank_value_falls_back_to_default(
    clean_env: None, fake_home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Verify that blank or whitespace-only values fall back to defaults."""
    monkeypatch.setenv("STARLING_OUTPUT_DIR", "")
    monkeypatch.setenv("STARLING_LANGUAGE_CODE", "   ")

    cfg = config.load_config(use_dotenv=False)

    assert cfg.output_dir == fake_home / "Starling" / "output"
    assert cfg.language_code == "en-US"


# ---------------------------------------------------------------------------
# ensure_directories
# ---------------------------------------------------------------------------


def test_ensure_directories_creates_all_five(
    clean_env: None, fake_home: Path
) -> None:
    """Verify that ensure_directories creates all five required directories."""
    cfg = config.load_config(use_dotenv=False)

    # Verify none exist yet (they are under fake_home which is a fresh temp dir).
    assert not cfg.input_dir.exists()
    assert not cfg.output_dir.exists()
    assert not cfg.archive_dir.exists()
    assert not cfg.usage_log_path.parent.exists()
    assert not cfg.error_log_path.parent.exists()

    config.ensure_directories(cfg)

    # After calling ensure_directories, all five must exist and be directories.
    assert cfg.input_dir.is_dir()
    assert cfg.output_dir.is_dir()
    assert cfg.archive_dir.is_dir()
    assert cfg.usage_log_path.parent.is_dir()
    assert cfg.error_log_path.parent.is_dir()


def test_ensure_directories_is_idempotent(
    clean_env: None, fake_home: Path
) -> None:
    """Verify that calling ensure_directories twice does not raise."""
    cfg = config.load_config(use_dotenv=False)

    config.ensure_directories(cfg)
    config.ensure_directories(cfg)  # Call again; no exception expected.


def test_ensure_directories_wraps_oserror(
    clean_env: None, fake_home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Verify that mkdir OSErrors are wrapped in ConfigError and name the path."""
    from pathlib import Path as PathClass

    def failing_mkdir(self: PathClass, *args: object, **kwargs: object) -> None:
        raise PermissionError("denied")

    monkeypatch.setattr(PathClass, "mkdir", failing_mkdir)
    cfg = config.load_config(use_dotenv=False)

    with pytest.raises(config.ConfigError) as exc_info:
        config.ensure_directories(cfg)

    # The error message must name one of the five target paths.
    message = str(exc_info.value)
    paths_mentioned = [
        str(cfg.input_dir) in message,
        str(cfg.output_dir) in message,
        str(cfg.archive_dir) in message,
        str(cfg.usage_log_path.parent) in message,
        str(cfg.error_log_path.parent) in message,
    ]
    assert any(paths_mentioned)


# ---------------------------------------------------------------------------
# resolve_credentials_path (direct unit tests; require_credentials tests above
# only exercise it indirectly through the full load_config -> require pipeline)
# ---------------------------------------------------------------------------


def test_resolve_credentials_path_returns_none_when_both_vars_unset(
    clean_env: None,
) -> None:
    """Verify that resolve_credentials_path returns None with no env vars set."""
    assert config.resolve_credentials_path() is None


def test_resolve_credentials_path_whitespace_only_starling_var_falls_through(
    clean_env: None, fake_credentials: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """
    Verify a whitespace-only STARLING_GOOGLE_CREDENTIALS is treated as unset.

    resolve_credentials_path strips each candidate before checking truthiness, so a
    variable set to spaces (e.g. from a templated .env) must fall through to
    GOOGLE_APPLICATION_CREDENTIALS rather than being treated as a configured
    (but empty) path.
    """
    monkeypatch.setenv("STARLING_GOOGLE_CREDENTIALS", "   ")
    monkeypatch.setenv("GOOGLE_APPLICATION_CREDENTIALS", str(fake_credentials))

    assert config.resolve_credentials_path() == fake_credentials


def test_resolve_credentials_path_expands_tilde(
    clean_env: None, fake_home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Verify that a ~-relative STARLING_GOOGLE_CREDENTIALS value is tilde-expanded."""
    from pathlib import Path as PathClass

    def fake_expanduser(path_self: PathClass) -> PathClass:
        parts = path_self.parts
        if parts and parts[0] == "~":
            return fake_home / PathClass(*parts[1:])
        return path_self

    monkeypatch.setattr(PathClass, "expanduser", fake_expanduser)
    monkeypatch.setenv("STARLING_GOOGLE_CREDENTIALS", "~/keys/service-account.json")

    result = config.resolve_credentials_path()

    assert result == fake_home / "keys" / "service-account.json"
    assert "~" not in str(result)


# ---------------------------------------------------------------------------
# parse_voice_pool (direct unit tests of the pure function; load_config's
# raise-on-empty-after-parse behavior lives in the caller, tested separately)
# ---------------------------------------------------------------------------


def test_parse_voice_pool_empty_string_returns_empty_tuple() -> None:
    """Verify that parse_voice_pool("") returns an empty tuple, not the default pool."""
    assert config.parse_voice_pool("") == ()


def test_parse_voice_pool_whitespace_only_returns_empty_tuple() -> None:
    """Verify that whitespace-only input returns an empty tuple (caller applies default)."""
    assert config.parse_voice_pool("   ") == ()


def test_parse_voice_pool_separators_only_returns_empty_tuple() -> None:
    """
    Verify that parse_voice_pool itself never raises -- it just returns ().

    load_config is the one that turns "raw had separators but no names" into a
    ConfigError; parse_voice_pool's own contract is purely mechanical.
    """
    assert config.parse_voice_pool(",,,") == ()


def test_parse_voice_pool_single_entry_no_trailing_comma() -> None:
    """Verify the boundary of exactly one name with no separator at all."""
    assert config.parse_voice_pool("solo-voice") == ("solo-voice",)


def test_ensure_directories_stops_after_first_failure(
    clean_env: None, fake_home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """
    Verify ensure_directories aborts on the first failing target and stops there.

    ensure_directories iterates (input_dir, output_dir, archive_dir,
    usage_log_path.parent, error_log_path.parent) and wraps the first OSError it
    hits in a ConfigError -- it does not aggregate failures across all five
    targets. This test makes input_dir fail while leaving mkdir itself intact for
    every other path, then asserts output_dir/archive_dir/the two log dirs were
    never created.
    """
    from pathlib import Path as PathClass

    cfg = config.load_config(use_dotenv=False)
    real_mkdir = PathClass.mkdir

    def selective_failing_mkdir(
        self: PathClass, *args: object, **kwargs: object
    ) -> None:
        if self == cfg.input_dir:
            raise PermissionError("denied")
        real_mkdir(self, *args, **kwargs)

    monkeypatch.setattr(PathClass, "mkdir", selective_failing_mkdir)

    with pytest.raises(config.ConfigError) as exc_info:
        config.ensure_directories(cfg)

    assert str(cfg.input_dir) in str(exc_info.value)
    assert not cfg.output_dir.exists()
    assert not cfg.archive_dir.exists()
    assert not cfg.usage_log_path.parent.exists()
    assert not cfg.error_log_path.parent.exists()


def test_ensure_directories_handles_duplicate_target_paths(
    clean_env: None, fake_home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """
    Verify that ensure_directories does not raise when two targets share a path.

    mkdir(parents=True, exist_ok=True) is idempotent, so pointing STARLING_INPUT_DIR
    and STARLING_OUTPUT_DIR at the same directory (a plausible misconfiguration)
    must not raise on the second, redundant mkdir call.
    """
    shared = fake_home / "shared"
    monkeypatch.setenv("STARLING_INPUT_DIR", str(shared))
    monkeypatch.setenv("STARLING_OUTPUT_DIR", str(shared))
    cfg = config.load_config(use_dotenv=False)

    config.ensure_directories(cfg)

    assert cfg.input_dir == cfg.output_dir == shared
    assert shared.is_dir()


def test_voice_mode_rejects_numeric_looking_value(
    clean_env: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Verify that a numeric-looking (but non-enum) voice mode value is rejected."""
    monkeypatch.setenv("STARLING_VOICE_MODE", "1")

    with pytest.raises(config.ConfigError) as exc_info:
        config.load_config(use_dotenv=False)

    assert "1" in str(exc_info.value)


# ---------------------------------------------------------------------------
# require_credentials
# ---------------------------------------------------------------------------


def test_credentials_prefer_starling_variable(
    clean_env: None, fake_credentials: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Verify that STARLING_GOOGLE_CREDENTIALS is preferred over GOOGLE_APPLICATION_CREDENTIALS."""
    other_path = tmp_path / "other.json"
    monkeypatch.setenv("STARLING_GOOGLE_CREDENTIALS", str(fake_credentials))
    monkeypatch.setenv("GOOGLE_APPLICATION_CREDENTIALS", str(other_path))

    cfg = config.load_config(use_dotenv=False)
    result = config.require_credentials(cfg)

    assert result == fake_credentials


def test_credentials_fall_back_to_google_variable(
    clean_env: None, fake_credentials: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Verify that GOOGLE_APPLICATION_CREDENTIALS is used when STARLING_ is not set."""
    monkeypatch.setenv("GOOGLE_APPLICATION_CREDENTIALS", str(fake_credentials))

    cfg = config.load_config(use_dotenv=False)
    result = config.require_credentials(cfg)

    assert result == fake_credentials


def test_require_credentials_exports_google_variable(
    clean_env: None, fake_credentials: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Verify that require_credentials sets GOOGLE_APPLICATION_CREDENTIALS in os.environ."""
    monkeypatch.setenv("STARLING_GOOGLE_CREDENTIALS", str(fake_credentials))

    cfg = config.load_config(use_dotenv=False)
    config.require_credentials(cfg)

    assert os.environ["GOOGLE_APPLICATION_CREDENTIALS"] == str(fake_credentials)


def test_missing_credentials_names_readme_section(
    clean_env: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Verify that missing credentials error names the README section and env vars."""
    cfg = config.load_config(use_dotenv=False)

    with pytest.raises(config.ConfigError) as exc_info:
        config.require_credentials(cfg)

    message = str(exc_info.value)
    assert config.README_CREDENTIALS_SECTION in message
    assert "STARLING_GOOGLE_CREDENTIALS" in message
    assert "GOOGLE_APPLICATION_CREDENTIALS" in message


def test_nonexistent_credentials_file_names_the_path(
    clean_env: None, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Verify that a nonexistent credentials file is named in the error."""
    missing_path = tmp_path / "nope.json"
    monkeypatch.setenv("STARLING_GOOGLE_CREDENTIALS", str(missing_path))

    cfg = config.load_config(use_dotenv=False)

    with pytest.raises(config.ConfigError) as exc_info:
        config.require_credentials(cfg)

    assert "nope.json" in str(exc_info.value)


def test_credentials_pointing_at_a_directory_raises(
    clean_env: None, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Verify that credentials pointing at a directory (not a file) names the key."""
    monkeypatch.setenv("STARLING_GOOGLE_CREDENTIALS", str(tmp_path))

    cfg = config.load_config(use_dotenv=False)

    with pytest.raises(config.ConfigError) as exc_info:
        config.require_credentials(cfg)

    assert "is not a file" in str(exc_info.value)


# ---------------------------------------------------------------------------
# voice_mode
# ---------------------------------------------------------------------------


def test_voice_mode_is_case_insensitive(
    clean_env: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Verify that voice mode matching is case-insensitive."""
    monkeypatch.setenv("STARLING_VOICE_MODE", "  Fixed ")

    cfg = config.load_config(use_dotenv=False)

    assert cfg.voice_mode is config.VoiceMode.FIXED


def test_unknown_voice_mode_lists_valid_values(
    clean_env: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Verify that invalid voice mode error lists valid options."""
    monkeypatch.setenv("STARLING_VOICE_MODE", "shuffle")

    with pytest.raises(config.ConfigError) as exc_info:
        config.load_config(use_dotenv=False)

    message = str(exc_info.value)
    assert "fixed" in message
    assert "random" in message


# ---------------------------------------------------------------------------
# voice_pool
# ---------------------------------------------------------------------------


def test_pool_strips_whitespace_and_dedupes_case_insensitively(
    clean_env: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Verify that voice pool deduplication is case-insensitive and preserves first spelling."""
    pool_str = " en-US-Chirp3-HD-Aoede , EN-US-CHIRP3-HD-AOEDE ,, en-US-Chirp3-HD-Puck "
    monkeypatch.setenv("STARLING_VOICE_POOL", pool_str)

    cfg = config.load_config(use_dotenv=False)

    assert cfg.voice_pool == ("en-US-Chirp3-HD-Aoede", "en-US-Chirp3-HD-Puck")


def test_single_entry_pool(
    clean_env: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Verify that a single-entry pool is preserved as a one-element tuple."""
    monkeypatch.setenv("STARLING_VOICE_POOL", "en-US-Chirp3-HD-Puck")

    cfg = config.load_config(use_dotenv=False)

    assert cfg.voice_pool == ("en-US-Chirp3-HD-Puck",)


def test_pool_with_only_separators_raises(
    clean_env: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Verify that a pool containing only separators raises with a suggestion."""
    monkeypatch.setenv("STARLING_VOICE_POOL", ",,,")

    with pytest.raises(config.ConfigError) as exc_info:
        config.load_config(use_dotenv=False)

    message = str(exc_info.value)
    assert "default pool" in message


def test_whitespace_only_pool_uses_default(
    clean_env: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Verify that whitespace-only pool falls back to the default."""
    monkeypatch.setenv("STARLING_VOICE_POOL", "   ")

    cfg = config.load_config(use_dotenv=False)

    assert cfg.voice_pool == config.DEFAULT_VOICE_POOL


# ---------------------------------------------------------------------------
# load_config dotenv behavior
# ---------------------------------------------------------------------------


def test_load_config_skips_dotenv_when_disabled(
    clean_env: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Verify that use_dotenv=False does not call load_dotenv and use_dotenv=True does."""
    call_count = {"dotenv": 0}

    def tracked_load_dotenv(*args: object, **kwargs: object) -> None:
        call_count["dotenv"] += 1
        raise AssertionError("dotenv should not be called")

    monkeypatch.setattr(config, "load_dotenv", tracked_load_dotenv)

    # With use_dotenv=False, load_dotenv must not be called.
    config.load_config(use_dotenv=False)
    assert call_count["dotenv"] == 0

    # With use_dotenv=True (the default), load_dotenv is called and raises.
    with pytest.raises(AssertionError, match="dotenv should not be called"):
        config.load_config(use_dotenv=True)
    assert call_count["dotenv"] == 1


# ---------------------------------------------------------------------------
# capture_confirm
# ---------------------------------------------------------------------------


def test_capture_confirm_defaults_to_false(
    clean_env: None,
) -> None:
    """Verify that capture_confirm defaults to False when STARLING_CAPTURE_CONFIRM is unset."""
    cfg = config.load_config(use_dotenv=False)

    assert cfg.capture_confirm is False


@pytest.mark.parametrize(
    "value",
    [
        pytest.param("true", id="true"),
        pytest.param("TRUE", id="uppercase"),
        pytest.param("1", id="one"),
        pytest.param("yes", id="yes"),
        pytest.param("on", id="on"),
        pytest.param(" true ", id="whitespace_trimmed"),
    ],
)
def test_capture_confirm_accepts_truthy_spellings(
    clean_env: None, monkeypatch: pytest.MonkeyPatch, value: str
) -> None:
    """Verify that capture_confirm accepts true/TRUE/1/yes/on with whitespace trimming."""
    monkeypatch.setenv("STARLING_CAPTURE_CONFIRM", value)

    cfg = config.load_config(use_dotenv=False)

    assert cfg.capture_confirm is True


@pytest.mark.parametrize(
    "value",
    [
        pytest.param("false", id="false"),
        pytest.param("0", id="zero"),
        pytest.param("no", id="no"),
        pytest.param("off", id="off"),
        pytest.param("", id="empty_string"),
    ],
)
def test_capture_confirm_accepts_falsey_spellings(
    clean_env: None, monkeypatch: pytest.MonkeyPatch, value: str
) -> None:
    """Verify that capture_confirm accepts false/0/no/off and blank as False."""
    monkeypatch.setenv("STARLING_CAPTURE_CONFIRM", value)

    cfg = config.load_config(use_dotenv=False)

    assert cfg.capture_confirm is False


def test_capture_confirm_rejects_unknown_value(
    clean_env: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Verify that an unrecognized STARLING_CAPTURE_CONFIRM value raises ConfigError."""
    monkeypatch.setenv("STARLING_CAPTURE_CONFIRM", "maybe")

    with pytest.raises(config.ConfigError) as exc_info:
        config.load_config(use_dotenv=False)

    assert "STARLING_CAPTURE_CONFIRM" in str(exc_info.value)


@pytest.mark.parametrize(
    "value",
    [
        pytest.param("tr ue", id="internal_whitespace_in_truthy_lookalike"),
        pytest.param("fal se", id="internal_whitespace_in_falsey_lookalike"),
        pytest.param("2", id="numeric_but_not_one_or_zero"),
        pytest.param("-1", id="negative_number"),
        pytest.param("1.0", id="float_looking_value"),
        pytest.param(chr(0x0661), id="arabic_indic_digit_one_lookalike"),
        pytest.param("y" * 5000, id="very_long_garbage_string"),
    ],
)
def test_capture_confirm_rejects_boundary_garbage_values(
    clean_env: None, monkeypatch: pytest.MonkeyPatch, value: str
) -> None:
    """
    Verify _env_flag rejects near-miss values rather than silently defaulting.

    TRUTHY_VALUES/FALSEY_VALUES are frozensets of exact ASCII spellings, so anything
    that merely *looks* like a valid flag -- a stray internal space, a numeral other
    than 1/0, a Unicode digit that ``str.casefold()`` does not normalize to ASCII "1",
    or a long garbage string -- must raise ConfigError rather than silently falling
    back to a boolean. A typo in a flag that gates billing must not read as "off".
    """
    monkeypatch.setenv("STARLING_CAPTURE_CONFIRM", value)

    with pytest.raises(config.ConfigError) as exc_info:
        config.load_config(use_dotenv=False)

    assert "STARLING_CAPTURE_CONFIRM" in str(exc_info.value)
