"""Voice discovery, validation, and selection against Google's live catalog."""

from __future__ import annotations

import difflib
import random
import sys
from dataclasses import dataclass
from typing import TYPE_CHECKING, Final

from google.api_core.exceptions import GoogleAPICallError
from google.auth.exceptions import DefaultCredentialsError
from google.cloud import texttospeech

from starling.config import (
    ConfigError,
    StarlingConfig,
    VoiceMode,
    load_config,
    require_credentials,
)

if TYPE_CHECKING:
    from collections.abc import Sequence

PRICING_URL: Final = "https://cloud.google.com/text-to-speech/pricing"

_GENDER_LABELS: Final[dict[int, str]] = {
    texttospeech.SsmlVoiceGender.MALE: "Male",
    texttospeech.SsmlVoiceGender.FEMALE: "Female",
    texttospeech.SsmlVoiceGender.NEUTRAL: "Neutral",
    texttospeech.SsmlVoiceGender.SSML_VOICE_GENDER_UNSPECIFIED: "Unspecified",
}


class UnknownVoiceError(ConfigError):
    """Raised when a configured voice name is not in Google's catalog."""


@dataclass(frozen=True, slots=True)
class VoiceInfo:
    name: str
    gender: str
    family: str
    language_codes: tuple[str, ...]


def model_family(voice_name: str) -> str:
    """
    Derive the model family from a Google voice name.

    Google names voices "<language>-<REGION>-<Family>[-HD]-<Variant>", so
    "en-US-Chirp3-HD-Aoede" is Chirp3-HD and "en-US-Neural2-C" is Neural2. The API
    does not return the family as a field, and family is what determines price.

    Returns "Unknown" for a name that does not fit the pattern.
    """
    parts = voice_name.split("-")
    if len(parts) < 3 or not parts[2]:
        return "Unknown"
    family = parts[2]
    if len(parts) > 3 and parts[3].upper() == "HD":
        family = f"{parts[2]}-HD"
    return family


def _gender_label(ssml_gender: int) -> str:
    """Return the human-readable label for an SsmlVoiceGender value."""
    return _GENDER_LABELS.get(ssml_gender, "Unspecified")


def fetch_voices(
    client: texttospeech.TextToSpeechClient,
    language_code: str,
) -> tuple[VoiceInfo, ...]:
    """
    Query Google's ListVoices API and return the catalog for one language code.

    ListVoices is not billed; synthesize_speech is. Calling this before synthesis is
    what makes early validation free.
    """
    response = client.list_voices(language_code=language_code)
    voices = [
        VoiceInfo(
            name=voice.name,
            gender=_gender_label(voice.ssml_gender),
            family=model_family(voice.name),
            language_codes=tuple(voice.language_codes),
        )
        for voice in response.voices
    ]
    return tuple(sorted(voices, key=lambda voice: (voice.family, voice.name)))


def validate_voice_names(
    names: Sequence[str],
    available: Sequence[VoiceInfo],
) -> tuple[str, ...]:
    """
    Resolve configured voice names against the live catalog, case-insensitively.

    Returns the names in Google's canonical spelling, in the order given. Raises
    UnknownVoiceError naming every unrecognized voice, with close-match suggestions.
    """
    if not available:
        msg = (
            "Google's voice catalog came back empty, so no voice name can be "
            "checked. The configured language code is probably wrong -- check "
            "STARLING_LANGUAGE_CODE."
        )
        raise UnknownVoiceError(msg)

    index = {voice.name.casefold(): voice.name for voice in available}
    catalog = [voice.name for voice in available]

    resolved: list[str] = []
    unknown: list[str] = []
    for raw_name in names:
        name = raw_name.strip()
        canonical = index.get(name.casefold())
        if canonical is None:
            unknown.append(name)
        else:
            resolved.append(canonical)

    if unknown:
        lines = []
        for name in unknown:
            line = f"Unknown voice name: {name}"
            matches = difflib.get_close_matches(name, catalog, n=3, cutoff=0.6)
            if matches:
                line += f" Did you mean: {', '.join(matches)}?"
            lines.append(line)
        lines.append(
            "Run `starling voices` to list every voice Google offers for this language.",
        )
        msg = "\n".join(lines)
        raise UnknownVoiceError(msg)

    return tuple(resolved)


def select_voice(
    config: StarlingConfig,
    pool: Sequence[str],
    rng: random.Random | None = None,
) -> str:
    """
    Pick the voice for one file: the fixed voice, or a random draw from the pool.

    `pool` is the validated, canonically spelled pool -- not config.voice_pool -- so a
    caller cannot accidentally synthesize with an unvalidated name.
    """
    if config.voice_mode is VoiceMode.FIXED:
        # The caller validates the fixed voice as a one-element sequence, so pool[0]
        # is its canonical spelling. Returning config.voice_name would bypass that.
        return pool[0]
    return (rng or random).choice(pool)


def format_voices_table(voices: Sequence[VoiceInfo]) -> str:
    """Render the voice catalog as an aligned three-column table."""
    headers = ("VOICE", "GENDER", "FAMILY")
    rows = [(voice.name, voice.gender, voice.family) for voice in voices]
    widths = [
        max(len(cell) for cell in column)
        for column in zip(headers, *rows, strict=True)
    ]

    def render(cells: Sequence[str]) -> str:
        return "  ".join(
            cell.ljust(width) for cell, width in zip(cells, widths, strict=True)
        ).rstrip()

    lines = [render(headers), render(["-" * width for width in widths])]
    lines.extend(render(row) for row in rows)
    return "\n".join(lines)


def pricing_notice(families: Sequence[str]) -> str:
    """
    Return the one-line billing warning for a set of model families.

    Deliberately quotes no prices: ROADMAP.md records that the README's existing
    free-tier numbers are unverified for Chirp 3: HD, and Phase 6 owns verifying them.
    """
    return (
        f"Billing: {', '.join(sorted(set(families)))} — voice families are priced "
        f"differently on your own Google Cloud account. Current rates: {PRICING_URL}"
    )


def run_voices(
    language_code: str | None = None,
    client: texttospeech.TextToSpeechClient | None = None,
) -> int:
    """
    Print the available voices for a language code. Returns a process exit code.

    Both parameters exist for testing: tests always pass a mocked client, so no test
    constructs a real one or needs credentials.
    """
    config = load_config()
    code = language_code or config.language_code
    try:
        if client is None:
            require_credentials(config)
            client = texttospeech.TextToSpeechClient()
        voices = fetch_voices(client, code)
    except (ConfigError, DefaultCredentialsError, GoogleAPICallError) as exc:
        print(f"Error: {exc}")
        return 1

    if not voices:
        print(f"No voices found for language code {code!r}. Check the code and try again.")
        return 1

    print(f"{len(voices)} voices available for {code}:\n")
    print(format_voices_table(voices))
    print()
    print(pricing_notice([voice.family for voice in voices]))
    return 0


if __name__ == "__main__":
    sys.exit(run_voices(sys.argv[1] if len(sys.argv) > 1 else None))
