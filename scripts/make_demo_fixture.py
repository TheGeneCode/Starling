"""
Seed a throwaway Starling home for generating docs/screenshot.png.

Creates a self-contained directory with three sample .txt articles, a plausible
prior usage log, and one already-synthesized .wav -- enough for
`starling read --dry-run` to produce an interesting, realistic report without any
credentials, network access, or real user data. See docs/DEMO.md for how the
resulting captured output is turned into the header image.
"""

from __future__ import annotations

import argparse
import re
import tempfile
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Final

# US Constitution, Preamble -- public domain, no copyright. Repeated/truncated
# below as filler text rather than embedding long original prose.
_PASSAGE: Final = (
    "We the People of the United States, in Order to form a more perfect Union, "
    "establish Justice, insure domestic Tranquility, provide for the common "
    "defence, promote the general Welfare, and secure the Blessings of Liberty "
    "to ourselves and our Posterity, do ordain and establish this Constitution "
    "for the United States of America."
)

# (filename stem, target character count). The first article's body is built as
# one giant run-on sentence (see _words_without_periods) so it lands as a single
# chunk despite exceeding the 4,500-byte chunk limit -- split_text_into_chunks
# never sub-splits a single sentence, a pre-existing quirk this fixture leans on
# to produce a realistic 1-chunk / 1-chunk / multi-chunk demo report.
_ARTICLES: Final[tuple[tuple[str, int], ...]] = (
    ("civic-primer", 5_900),
    ("reading-notes", 3_200),
    ("seasonal-almanac", 12_400),
)

# (days after the 1st of the month, time-of-day, stem, voice, characters, running
# monthly total). Ascending order matters: get_monthly_total keeps the *last*
# matching "monthly total:" field it sees.
_PRIOR_USAGE: Final[tuple[tuple[int, str, str, str, int, int], ...]] = (
    (0, "08:14:02", "morning-briefing", "en-US-Chirp3-HD-Aoede", 42_318, 42_318),
    (5, "09:41:37", "weekend-longread", "en-US-Chirp3-HD-Puck", 38_552, 80_870),
    (10, "14:52:19", "quarterly-outlook", "en-US-Chirp3-HD-Charon", 44_830, 125_700),
)


def _words_without_periods(passage: str, target_len: int) -> str:
    """Repeat passage's words, punctuation stripped, as one run-on sentence."""
    words = re.sub(r"[.,;:!?]", "", passage).split()
    pieces: list[str] = []
    length = 0
    i = 0
    while length < target_len:
        word = words[i % len(words)]
        pieces.append(word)
        length += len(word) + 1
        i += 1
    return " ".join(pieces)[:target_len]


def _repeated_sentences(passage: str, target_len: int) -> str:
    """Repeat passage as ordinary punctuated sentences until target_len characters."""
    unit = passage.strip()
    pieces: list[str] = []
    length = 0
    while length < target_len:
        pieces.append(unit)
        length += len(unit) + 1
    return " ".join(pieces)[:target_len]


def _article_body(stem: str, target_len: int) -> str:
    """Build one article's body; only the first article uses the single-chunk trick."""
    if stem == _ARTICLES[0][0]:
        return _words_without_periods(_PASSAGE, target_len)
    return _repeated_sentences(_PASSAGE, target_len)


def _write_usage_log(path: Path) -> None:
    """Write plausible prior entries, in ascending order, for the current calendar month."""
    month_start = datetime.now(UTC).replace(
        day=1,
        hour=0,
        minute=0,
        second=0,
        microsecond=0,
    )
    lines = [
        (
            f"{(month_start + timedelta(days=day_offset)).strftime('%Y-%m-%d')} "
            f"{time_str} | {stem} | voice: {voice} | characters: {chars:,} | "
            f"monthly total: {total:,}"
        )
        for day_offset, time_str, stem, voice, chars, total in _PRIOR_USAGE
    ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def build_fixture(root: Path) -> Path:
    """Create a throwaway Starling home at root, seeded with demo data. Returns root."""
    input_dir = root / "input"
    output_dir = root / "output"
    archive_dir = root / "archive"
    logs_dir = root / "logs"
    for directory in (input_dir, output_dir, archive_dir, logs_dir):
        directory.mkdir(parents=True, exist_ok=True)

    for stem, target_len in _ARTICLES:
        (input_dir / f"{stem}.txt").write_text(
            _article_body(stem, target_len),
            encoding="utf-8",
        )

    _write_usage_log(logs_dir / "usage.log")

    first_stem = _ARTICLES[0][0]
    (output_dir / f"{first_stem}.wav").touch()

    return root


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--root",
        type=Path,
        default=None,
        help="Directory to seed (default: a new directory under the system temp dir)",
    )
    args = parser.parse_args()

    root = (
        args.root
        if args.root is not None
        else Path(tempfile.mkdtemp(prefix="starling-demo-"))
    )
    build_fixture(root)
    print(root)


if __name__ == "__main__":
    main()
