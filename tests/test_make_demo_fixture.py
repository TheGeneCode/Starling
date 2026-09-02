"""
Tests for scripts/make_demo_fixture.py.

scripts/ is not an importable package (see the ``import_script`` fixture in
conftest.py), so every test here loads the module fresh from its file path.

Focus areas: the fixture's chunk-count invariants are re-verified against the
*real* ``starling.reader.split_text_into_chunks`` (not hand-computed) so a
future change to the chunking regex or byte cap is caught here rather than
silently producing a boring/broken demo screenshot; and the usage-log date
arithmetic is checked across month boundaries and leap years.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

import pytest

from starling import reader

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path
    from types import ModuleType

# Designed chunk counts per _ARTICLES entry, in declaration order. Pinned here
# independently of the module's own docstring claim so a regression in either
# the fixture's text-generation helpers or reader.split_text_into_chunks trips
# this test, not just the docstring comment.
_EXPECTED_CHUNK_COUNTS: dict[str, int] = {
    "civic-primer": 1,
    "reading-notes": 1,
    "seasonal-almanac": 3,
}


@pytest.fixture
def demo_fixture(import_script: Callable[[str], ModuleType]) -> ModuleType:
    """Load and return the make_demo_fixture module, freshly."""
    return import_script("make_demo_fixture.py")


# ---------------------------------------------------------------------------
# build_fixture
# ---------------------------------------------------------------------------


def test_build_fixture_creates_all_directories(tmp_path: Path, demo_fixture: ModuleType) -> None:
    """Test that input/output/archive/logs are all created under root."""
    demo_fixture.build_fixture(tmp_path)
    for name in ("input", "output", "archive", "logs"):
        assert (tmp_path / name).is_dir()


def test_build_fixture_returns_the_root_it_was_given(
    tmp_path: Path, demo_fixture: ModuleType
) -> None:
    """Test that the return value is the root Path itself, not a copy or subpath."""
    result = demo_fixture.build_fixture(tmp_path)
    assert result == tmp_path


def test_build_fixture_writes_exactly_the_three_designed_articles(
    tmp_path: Path, demo_fixture: ModuleType
) -> None:
    """Test that input/ contains exactly the three named .txt articles, no more."""
    demo_fixture.build_fixture(tmp_path)
    stems = {p.stem for p in (tmp_path / "input").glob("*.txt")}
    assert stems == {"civic-primer", "reading-notes", "seasonal-almanac"}


def test_build_fixture_chunk_counts_match_designed_invariant(
    tmp_path: Path, demo_fixture: ModuleType
) -> None:
    """
    Pin the fixture's core design invariant: chunk counts of 1, 1, 3.

    This is the test the implementer specifically asked for: re-run the real
    ``split_text_into_chunks`` (default 4,500-byte cap) against the generated
    article bodies, not a hand-computed expectation, so a future change to
    the chunking regex or byte cap that would make the demo screenshot boring
    (or wrong) fails here.
    """
    demo_fixture.build_fixture(tmp_path)
    for stem, expected_count in _EXPECTED_CHUNK_COUNTS.items():
        body = (tmp_path / "input" / f"{stem}.txt").read_text(encoding="utf-8")
        chunks = reader.split_text_into_chunks(body)
        assert len(chunks) == expected_count, f"{stem}: expected {expected_count} chunk(s)"


def test_build_fixture_civic_primer_exploits_the_oversized_single_sentence_quirk(
    tmp_path: Path, demo_fixture: ModuleType
) -> None:
    """
    Confirm *why* civic-primer stays at 1 chunk: its single "sentence" exceeds the cap.

    If a future fix to split_text_into_chunks started sub-splitting oversized
    lone sentences, this fixture's civic-primer chunk would stop being an
    intentional demonstration of the quirk (and the chunk-count test above
    would also start failing) -- this test documents the mechanism.
    """
    demo_fixture.build_fixture(tmp_path)
    body = (tmp_path / "input" / "civic-primer.txt").read_text(encoding="utf-8")
    chunks = reader.split_text_into_chunks(body)
    assert len(chunks) == 1
    assert len(chunks[0].encode("utf-8")) > 4500


def test_build_fixture_wav_placeholder_is_an_empty_file(
    tmp_path: Path, demo_fixture: ModuleType
) -> None:
    """Test that the pre-synthesized .wav is a zero-byte placeholder, not real audio."""
    demo_fixture.build_fixture(tmp_path)
    wav_path = tmp_path / "output" / "civic-primer.wav"
    assert wav_path.is_file()
    assert wav_path.stat().st_size == 0


def test_build_fixture_is_idempotent_when_called_twice_on_the_same_root(
    tmp_path: Path, demo_fixture: ModuleType
) -> None:
    """Test the repeated-call state boundary: a second call must not raise or corrupt state."""
    demo_fixture.build_fixture(tmp_path)
    first_bodies = {
        p.name: p.read_text(encoding="utf-8") for p in (tmp_path / "input").glob("*.txt")
    }

    demo_fixture.build_fixture(tmp_path)

    second_bodies = {
        p.name: p.read_text(encoding="utf-8") for p in (tmp_path / "input").glob("*.txt")
    }
    assert second_bodies == first_bodies
    assert (tmp_path / "output" / "civic-primer.wav").is_file()


def test_build_fixture_leaks_no_real_username_or_home_path_into_generated_content(
    tmp_path: Path, demo_fixture: ModuleType
) -> None:
    """
    Confirm the fixture's own content never embeds real personal data.

    The implementer specifically avoided $env:TEMP for this reason; this test
    checks the generated *content* itself (article bodies and usage log)
    contains neither the current OS username nor the real home directory
    path, independent of where the test happens to write the fixture.
    """
    import getpass
    from pathlib import Path

    demo_fixture.build_fixture(tmp_path)

    username = getpass.getuser()
    home = str(Path.home())
    all_text = "\n".join(
        p.read_text(encoding="utf-8")
        for p in tmp_path.rglob("*")
        if p.is_file() and p.suffix in {".txt", ".log"}
    )
    assert username not in all_text
    assert home not in all_text


# ---------------------------------------------------------------------------
# _write_usage_log
# ---------------------------------------------------------------------------


def test_write_usage_log_produces_well_formed_ascending_lines(
    tmp_path: Path, demo_fixture: ModuleType
) -> None:
    """Test line count, field shape, and that each field parses as documented."""
    log_path = tmp_path / "usage.log"
    demo_fixture._write_usage_log(log_path)

    content = log_path.read_text(encoding="utf-8")
    assert content.endswith("\n")
    lines = content.splitlines()
    assert len(lines) == len(demo_fixture._PRIOR_USAGE)

    for line, (_, time_str, stem, voice, chars, total) in zip(
        lines, demo_fixture._PRIOR_USAGE, strict=True
    ):
        fields = line.split(" | ")
        assert len(fields) == 5
        date_part, time_part = fields[0].split(" ")
        datetime.strptime(date_part, "%Y-%m-%d").replace(tzinfo=UTC)  # raises if malformed
        assert time_part == time_str
        assert fields[1] == stem
        assert fields[2] == f"voice: {voice}"
        assert fields[3] == f"characters: {chars:,}"
        assert fields[4] == f"monthly total: {total:,}"


def test_write_usage_log_running_totals_are_internally_consistent(
    tmp_path: Path, demo_fixture: ModuleType
) -> None:
    """Test that each running total equals the prior total plus that entry's characters."""
    log_path = tmp_path / "usage.log"
    demo_fixture._write_usage_log(log_path)

    running = 0
    for _, _, _, _, chars, total in demo_fixture._PRIOR_USAGE:
        running += chars
        assert total == running


def test_write_usage_log_dates_stay_within_the_current_calendar_month(
    tmp_path: Path, demo_fixture: ModuleType
) -> None:
    """Test (against the real system clock) that no entry's date rolls into next month."""
    log_path = tmp_path / "usage.log"
    demo_fixture._write_usage_log(log_path)

    now = datetime.now(UTC)
    for line in log_path.read_text(encoding="utf-8").splitlines():
        date_part = line.split(" ")[0]
        entry_date = datetime.strptime(date_part, "%Y-%m-%d").replace(tzinfo=UTC)
        assert entry_date.year == now.year
        assert entry_date.month == now.month


@pytest.mark.parametrize(
    "frozen_now",
    [
        pytest.param(datetime(2026, 1, 15, tzinfo=UTC), id="january"),
        pytest.param(datetime(2026, 2, 27, tzinfo=UTC), id="february_non_leap_year"),
        pytest.param(datetime(2028, 2, 27, tzinfo=UTC), id="february_leap_year"),
        pytest.param(datetime(2026, 4, 30, tzinfo=UTC), id="thirty_day_month"),
        pytest.param(datetime(2026, 12, 31, tzinfo=UTC), id="december_no_year_rollover"),
    ],
)
def test_write_usage_log_offsets_never_reach_day_29_in_any_month(
    tmp_path: Path,
    demo_fixture: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    frozen_now: datetime,
) -> None:
    """
    Test the day-offset arithmetic across short months, leap years, and year-end.

    _write_usage_log always resolves ``month_start`` to the 1st of the current
    month before applying offsets of 0/5/10 days, so the highest date it can
    ever produce is the 11th -- nowhere near the 29th/30th/31st where a
    same-month assumption would break. This freezes "now" to several
    boundary-adjacent months (a non-leap February, a leap February, a 30-day
    month, and December) and confirms every written date stays in that same
    calendar month, with day <= 11.
    """

    class _FrozenDateTime(datetime):
        @classmethod
        def now(cls, tz: object = None) -> datetime:  # noqa: ARG003
            return frozen_now

    monkeypatch.setattr(demo_fixture, "datetime", _FrozenDateTime)

    log_path = tmp_path / "usage.log"
    demo_fixture._write_usage_log(log_path)

    for line in log_path.read_text(encoding="utf-8").splitlines():
        date_part = line.split(" ")[0]
        entry_date = datetime.strptime(date_part, "%Y-%m-%d").replace(tzinfo=UTC)
        assert entry_date.year == frozen_now.year
        assert entry_date.month == frozen_now.month
        assert entry_date.day <= 11


# ---------------------------------------------------------------------------
# Integration with starling.reader.get_monthly_total
# ---------------------------------------------------------------------------


def test_usage_log_is_correctly_parsed_by_reader_get_monthly_total(
    tmp_path: Path, demo_fixture: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    """
    Test that the fixture's usage log round-trips through the real reader parser.

    Confirms the log format isn't just well-formed in isolation, but actually
    produces the intended "realistic prior usage" report when read by the
    same code the demo screenshot exercises.
    """
    log_path = tmp_path / "usage.log"
    demo_fixture._write_usage_log(log_path)
    monkeypatch.setattr(reader, "USAGE_LOG_PATH", log_path)

    result = reader.get_monthly_total()

    assert result["total_chars"] == 125_700
    assert len(result["entries"]) == 3


# ---------------------------------------------------------------------------
# main / CLI wiring
# ---------------------------------------------------------------------------


def test_main_writes_to_the_explicit_root_argument(
    tmp_path: Path,
    demo_fixture: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """
    Test that --root is honored end to end and printed, never the system temp default.

    Deliberately never invokes main() without --root: the argparse default
    falls back to tempfile.mkdtemp() under the real system temp directory,
    which this suite must not touch.
    """
    root = tmp_path / "demo-root"
    monkeypatch.setattr("sys.argv", ["make_demo_fixture.py", "--root", str(root)])

    demo_fixture.main()

    captured = capsys.readouterr()
    assert captured.out.strip() == str(root)
    assert (root / "input").is_dir()
    assert list((root / "input").glob("*.txt"))
