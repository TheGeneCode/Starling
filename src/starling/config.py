"""Configuration loading and validation for Starling."""

from __future__ import annotations

import os
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Final

from dotenv import load_dotenv

ENV_PREFIX: Final = "STARLING_"

# Named in every credential error message so the user has somewhere to go.
README_CREDENTIALS_SECTION: Final = "Set Up Google Cloud Credentials"

DEFAULT_LANGUAGE_CODE: Final = "en-US"
DEFAULT_VOICE_NAME: Final = "en-US-Chirp3-HD-Enceladus"

# The 22 Chirp 3: HD voices reader.py hardcoded before this phase (21 literals
# plus the env-provided default that was prepended to them). Google's voice
# catalog is the real source of truth -- `starling voices` (Phase 2b) lists it
# live. This tuple only supplies a default.
DEFAULT_VOICE_POOL: Final[tuple[str, ...]] = (
    "en-US-Chirp3-HD-Algenib",
    "en-US-Chirp3-HD-Algieba",
    "en-US-Chirp3-HD-Alnilam",
    "en-US-Chirp3-HD-Aoede",
    "en-US-Chirp3-HD-Autonoe",
    "en-US-Chirp3-HD-Callirrhoe",
    "en-US-Chirp3-HD-Charon",
    "en-US-Chirp3-HD-Despina",
    "en-US-Chirp3-HD-Enceladus",
    "en-US-Chirp3-HD-Erinome",
    "en-US-Chirp3-HD-Iapetus",
    "en-US-Chirp3-HD-Laomedeia",
    "en-US-Chirp3-HD-Leda",
    "en-US-Chirp3-HD-Orus",
    "en-US-Chirp3-HD-Puck",
    "en-US-Chirp3-HD-Pulcherrima",
    "en-US-Chirp3-HD-Rasalgethi",
    "en-US-Chirp3-HD-Sadachbia",
    "en-US-Chirp3-HD-Schedar",
    "en-US-Chirp3-HD-Umbriel",
    "en-US-Chirp3-HD-Vindemiatrix",
    "en-US-Chirp3-HD-Zephyr",
)

# The values that switch a STARLING_* boolean off, matching update_check.py's
# _DISABLED_VALUES so one .env convention covers every flag Starling reads.
FALSEY_VALUES: Final[frozenset[str]] = frozenset({"0", "false", "no", "off"})
TRUTHY_VALUES: Final[frozenset[str]] = frozenset({"1", "true", "yes", "on"})


class ConfigError(RuntimeError):
    """Raised when Starling's configuration is missing, malformed, or unusable."""


class VoiceMode(StrEnum):
    FIXED = "fixed"  # always STARLING_VOICE_NAME
    RANDOM = "random"  # pick from STARLING_VOICE_POOL, once per file


@dataclass(frozen=True, slots=True)
class StarlingConfig:
    home_dir: Path
    input_dir: Path
    output_dir: Path
    archive_dir: Path
    credentials_path: Path | None
    language_code: str
    voice_mode: VoiceMode
    voice_name: str
    voice_pool: tuple[str, ...]
    usage_log_path: Path
    error_log_path: Path
    capture_confirm: bool


def _env(name: str) -> str | None:
    """Return the raw value of a STARLING_-prefixed variable, unchanged."""
    return os.getenv(ENV_PREFIX + name)


def _env_str(name: str, default: str) -> str:
    """Return a stripped environment string, falling back to ``default`` when blank."""
    value = (_env(name) or "").strip()
    return value or default


def _env_path(name: str, default: Path) -> Path:
    """Return an environment path with ``~`` expanded, falling back when blank."""
    value = (_env(name) or "").strip()
    if not value:
        return default
    return Path(value).expanduser()


def _env_voice_mode(default: VoiceMode) -> VoiceMode:
    """Return the configured voice mode, falling back to ``default`` when blank."""
    raw = (_env("VOICE_MODE") or "").strip()
    if not raw:
        return default
    normalized = raw.casefold()
    for mode in VoiceMode:
        if mode.value == normalized:
            return mode
    msg = f"STARLING_VOICE_MODE={raw!r} is not valid. Use one of: fixed, random."
    raise ConfigError(msg)


def _env_flag(name: str, *, default: bool) -> bool:
    """
    Return a boolean STARLING_* flag. Blank or unset yields ``default``.

    Accepts the same spellings as STARLING_UPDATE_CHECK (1/true/yes/on and
    0/false/no/off, case-insensitive). An unrecognized value is a ConfigError
    rather than a silent fallback -- a typo in a flag that gates billing must
    not read as "off".
    """
    raw = (_env(name) or "").strip().casefold()
    if not raw:
        return default
    if raw in TRUTHY_VALUES:
        return True
    if raw in FALSEY_VALUES:
        return False
    msg = (
        f"{ENV_PREFIX}{name}={raw!r} is not valid. Use one of: "
        "true, false, 1, 0, yes, no, on, off."
    )
    raise ConfigError(msg)


def parse_voice_pool(raw: str) -> tuple[str, ...]:
    """
    Split a comma-separated voice pool, dropping whitespace and case-insensitive duplicates.

    The first spelling of a duplicate wins; casing is preserved as written, because
    Google's canonical spelling is resolved later against the live voice list
    (see starling.voices.validate_voice_names, Phase 2b).
    """
    seen: set[str] = set()
    names: list[str] = []
    for item in raw.split(","):
        name = item.strip()
        if not name:
            continue
        key = name.casefold()
        if key in seen:
            continue
        seen.add(key)
        names.append(name)
    return tuple(names)


def resolve_credentials_path() -> Path | None:
    """
    Return the configured service-account key path, or None if neither variable is set.

    Checks STARLING_GOOGLE_CREDENTIALS first, then Google's own standard
    GOOGLE_APPLICATION_CREDENTIALS. Does not check that the file exists --
    require_credentials() does that.
    """
    candidates = (
        _env("GOOGLE_CREDENTIALS"),
        os.getenv("GOOGLE_APPLICATION_CREDENTIALS"),
    )
    for candidate in candidates:
        value = (candidate or "").strip()
        if value:
            return Path(value).expanduser()
    return None


def load_config(*, use_dotenv: bool = True) -> StarlingConfig:
    """
    Build a StarlingConfig from the environment (and, by default, a .env file).

    Pass use_dotenv=False to read os.environ only, so a developer's real .env
    can never leak into a test run.
    """
    if use_dotenv:
        # load_dotenv() does not override variables already in os.environ.
        load_dotenv()

    home_dir = _env_path("HOME", Path.home() / "Starling")
    input_dir = _env_path("INPUT_DIR", home_dir / "input")
    output_dir = _env_path("OUTPUT_DIR", home_dir / "output")
    archive_dir = _env_path("ARCHIVE_DIR", home_dir / "archive")
    usage_log_path = _env_path("USAGE_LOG", home_dir / "logs" / "usage.log")
    error_log_path = _env_path("ERROR_LOG", home_dir / "logs" / "errors.log")

    credentials_path = resolve_credentials_path()
    language_code = _env_str("LANGUAGE_CODE", DEFAULT_LANGUAGE_CODE)
    voice_mode = _env_voice_mode(VoiceMode.RANDOM)
    voice_name = _env_str("VOICE_NAME", DEFAULT_VOICE_NAME)

    raw_pool = (_env("VOICE_POOL") or "").strip()
    if not raw_pool:
        voice_pool = DEFAULT_VOICE_POOL
    else:
        voice_pool = parse_voice_pool(raw_pool)
        if not voice_pool:
            msg = (
                "STARLING_VOICE_POOL is set but lists no voice names. "
                "Give a comma-separated list of voice names, or remove the "
                "variable to use Starling's default pool."
            )
            raise ConfigError(msg)

    capture_confirm = _env_flag("CAPTURE_CONFIRM", default=False)

    return StarlingConfig(
        home_dir=home_dir,
        input_dir=input_dir,
        output_dir=output_dir,
        archive_dir=archive_dir,
        credentials_path=credentials_path,
        language_code=language_code,
        voice_mode=voice_mode,
        voice_name=voice_name,
        voice_pool=voice_pool,
        usage_log_path=usage_log_path,
        error_log_path=error_log_path,
        capture_confirm=capture_confirm,
    )


def ensure_directories(config: StarlingConfig) -> None:
    """Create the input, output, archive, and log directories if they are absent."""
    targets = (
        config.input_dir,
        config.output_dir,
        config.archive_dir,
        config.usage_log_path.parent,
        config.error_log_path.parent,
    )
    for target in targets:
        try:
            target.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            msg = f"Could not create directory {target}: {exc}"
            raise ConfigError(msg) from exc


def require_credentials(config: StarlingConfig) -> Path:
    """
    Validate the Google service-account key and export it for google.auth.

    Returns the key path. Raises ConfigError when no key is configured, the path does
    not exist, or it is not a file.
    """
    path = config.credentials_path
    if path is None:
        msg = (
            "No Google Cloud credentials configured. Set STARLING_GOOGLE_CREDENTIALS "
            "(or GOOGLE_APPLICATION_CREDENTIALS) to the path of your service-account "
            f"JSON key. See the README section '{README_CREDENTIALS_SECTION}' for how "
            "to create one."
        )
        raise ConfigError(msg)

    if not path.exists():
        msg = (
            f"Google Cloud credentials file not found: {path}. Check "
            f"STARLING_GOOGLE_CREDENTIALS. See the README section "
            f"'{README_CREDENTIALS_SECTION}'."
        )
        raise ConfigError(msg)

    if not path.is_file():
        msg = (
            f"Google Cloud credentials path is not a file: {path}. Point it at the "
            "service-account JSON key itself, not its folder."
        )
        raise ConfigError(msg)

    # Mandatory: google.auth only reads its own standard variable, so a config that
    # sets only STARLING_GOOGLE_CREDENTIALS would otherwise fail at client creation.
    os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = str(path)
    return path
