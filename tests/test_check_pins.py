"""
Tests for ``scripts/check_pins.py``, the monthly maintenance check.

Every external seam (HTTP, git, the clock) is injected, so nothing here touches the network
or a real repository.
"""

from __future__ import annotations

import io
import json
from datetime import date
from pathlib import Path
from typing import TYPE_CHECKING, Any, Final

import pytest

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence
    from types import ModuleType

_GENEKIT_DEP: Final = (
    "genekit @ git+https://github.com/TheGeneCode/genekit@py-v0.4.0#subdirectory=python"
)
_TOY_PYPROJECT: Final = f"""
[project]
dependencies = [
  "google-cloud-texttospeech>=2.33.0,<3",
  "{_GENEKIT_DEP}",
]
classifiers = [
  "Programming Language :: Python :: 3.12",
  "Programming Language :: Python :: 3.14",
]
"""
_TOY_README: Final = "Prices were checked on **2 September 2026** against the pricing page.\n"
_TODAY: Final = date(2026, 11, 8)


@pytest.fixture
def check_pins(import_script: Callable[[str], ModuleType]) -> Any:
    """Load ``scripts/check_pins.py``."""
    return import_script("check_pins.py")


def _pyproject(deps: Sequence[str], classifiers: Sequence[str] = ()) -> dict[str, object]:
    return {"project": {"dependencies": list(deps), "classifiers": list(classifiers)}}


def _fake_fetch(responses: dict[str, object]) -> Callable[[str], object]:
    def _fetch(url: str) -> object:
        if url not in responses:
            msg = "offline"
            raise OSError(msg)
        return responses[url]

    return _fetch


def _fake_git(describe: str, diff: str) -> Callable[[Sequence[str]], str]:
    def _git(args: Sequence[str]) -> str:
        return describe if args[0] == "describe" else diff

    return _git


def _offline(url: str) -> object:
    msg = "offline"
    raise OSError(msg)


def _repo(tmp_path: Path) -> Path:
    (tmp_path / "pyproject.toml").write_text(_TOY_PYPROJECT, encoding="utf-8")
    (tmp_path / "README.md").write_text(_TOY_README, encoding="utf-8")
    return tmp_path


# ------------------------------------------------------------------------------ genekit


def test_genekit_pin_parses_dependency(check_pins: Any) -> None:
    assert check_pins.genekit_pin(_pyproject(["x>=1", _GENEKIT_DEP])) == "0.4.0"


def test_genekit_pin_missing_raises(check_pins: Any) -> None:
    with pytest.raises(ValueError, match="genekit"):
        check_pins.genekit_pin(_pyproject(["x>=1"]))


def test_latest_py_tag_ignores_other_prefixes(check_pins: Any) -> None:
    names = ["py-v0.4.0", "py-v0.10.0", "ts-v9.0.0", "py-v0.5.0rc1", "v1.0.0"]
    assert check_pins.latest_py_tag(names) == "0.10.0"
    assert check_pins.latest_py_tag(["ts-v1.0.0"]) is None


def test_check_genekit_flags_newer_tag(check_pins: Any) -> None:
    fetch = _fake_fetch({check_pins.GENEKIT_TAGS_URL: [{"name": "py-v0.5.0"}]})
    finding = check_pins.check_genekit(_pyproject([_GENEKIT_DEP]), fetch)
    assert finding.check == "genekit-pin"
    assert "py-v0.4.0" in finding.message
    assert "py-v0.5.0" in finding.message


def test_check_genekit_silent_when_current(check_pins: Any) -> None:
    fetch = _fake_fetch({check_pins.GENEKIT_TAGS_URL: [{"name": "py-v0.5.0"}]})
    pyproject = _pyproject([_GENEKIT_DEP.replace("0.4.0", "0.5.0")])
    assert check_pins.check_genekit(pyproject, fetch) is None


# ------------------------------------------------------------------------------- python


def _classifiers(*minors: int) -> list[str]:
    return [f"Programming Language :: Python :: 3.{m}" for m in minors]


def test_python_ceiling_reads_highest_classifier(check_pins: Any) -> None:
    assert check_pins.python_ceiling(_pyproject([], _classifiers(12, 13, 14))) == 14


def test_check_python_ceiling_flags_new_minor(check_pins: Any) -> None:
    releases = [{"name": "Python 3.15.0"}, {"name": "Python 3.14.2"}, {"name": "Python 2.7.18"}]
    fetch = _fake_fetch({check_pins.PYTHON_RELEASES_URL: releases})
    finding = check_pins.check_python_ceiling(_pyproject([], _classifiers(12, 14)), fetch)
    assert finding.check == "python-ceiling"
    assert "3.15" in finding.message


def test_check_python_ceiling_silent_at_ceiling(check_pins: Any) -> None:
    fetch = _fake_fetch({check_pins.PYTHON_RELEASES_URL: [{"name": "Python 3.14.2"}]})
    assert check_pins.check_python_ceiling(_pyproject([], _classifiers(14)), fetch) is None


# ------------------------------------------------------------------------------ pricing


@pytest.mark.parametrize(
    ("today", "flagged"),
    [(date(2026, 12, 1), False), (date(2026, 12, 2), True)],
    ids=["90-days", "91-days"],
)
def test_check_pricing_date_boundary(check_pins: Any, today: date, flagged: bool) -> None:
    finding = check_pins.check_pricing_date(_TOY_README, today)
    assert (finding is not None) is flagged
    if finding is not None:
        assert finding.check == "pricing-date"
        assert "2 September 2026" in finding.message


def test_pricing_checked_on_parses_real_readme(check_pins: Any) -> None:
    """Guards README wording drift: the check must keep finding its date."""
    readme = Path(__file__).resolve().parents[1] / "README.md"
    assert isinstance(check_pins.pricing_checked_on(readme.read_text(encoding="utf-8")), date)


# --------------------------------------------------------------------------- release due


def test_check_release_due_flags_lock_change(check_pins: Any) -> None:
    finding = check_pins.check_release_due(_fake_git("v0.2.1\n", "uv.lock\n"))
    assert finding.check == "release-due"
    assert "v0.2.1" in finding.message


def test_check_release_due_silent_without_lock_change(check_pins: Any) -> None:
    assert check_pins.check_release_due(_fake_git("v0.2.1\n", "")) is None


# ----------------------------------------------------------------------------- tts major


def test_check_tts_major_flags_at_cap(check_pins: Any) -> None:
    fetch = _fake_fetch({check_pins.TTS_PYPI_URL: {"info": {"version": "3.0.0"}}})
    pyproject = _pyproject(["google-cloud-texttospeech>=2.33.0,<3"])
    finding = check_pins.check_tts_major(pyproject, fetch)
    assert finding.check == "tts-major"
    assert "3.0.0" in finding.message


@pytest.mark.parametrize(
    ("dep", "latest", "fetches"),
    [
        ("google-cloud-texttospeech>=2.33.0,<3", "2.40.1", 1),
        ("google-cloud-texttospeech>=2.33.0", "3.0.0", 0),
    ],
    ids=["below-cap", "uncapped"],
)
def test_check_tts_major_silent_below_cap_or_uncapped(
    check_pins: Any,
    dep: str,
    latest: str,
    fetches: int,
) -> None:
    calls: list[str] = []

    def _fetch(url: str) -> object:
        calls.append(url)
        return {"info": {"version": latest}}

    assert check_pins.check_tts_major(_pyproject([dep]), _fetch) is None
    assert len(calls) == fetches


# ------------------------------------------------------------- malformed payloads (no silent pass)


@pytest.mark.parametrize(
    ("check", "url_attr", "payload"),
    [
        ("check_genekit", "GENEKIT_TAGS_URL", {"message": "rate limited"}),
        ("check_genekit", "GENEKIT_TAGS_URL", []),
        ("check_genekit", "GENEKIT_TAGS_URL", [{"name": "ts-v9.0.0"}, {"nope": 1}, "py-v9.0.0"]),
        ("check_python_ceiling", "PYTHON_RELEASES_URL", {"detail": "bad"}),
        ("check_python_ceiling", "PYTHON_RELEASES_URL", []),
        ("check_python_ceiling", "PYTHON_RELEASES_URL", [{"name": "Python 2.7.18"}, {"x": 1}]),
        ("check_tts_major", "TTS_PYPI_URL", []),
        ("check_tts_major", "TTS_PYPI_URL", {}),
        ("check_tts_major", "TTS_PYPI_URL", {"info": {}}),
        ("check_tts_major", "TTS_PYPI_URL", {"info": {"version": 3}}),
        ("check_tts_major", "TTS_PYPI_URL", {"info": {"version": "dev"}}),
    ],
)
def test_check_raises_on_unexpected_response_shape(
    check_pins: Any,
    check: str,
    url_attr: str,
    payload: object,
) -> None:
    url = getattr(check_pins, url_attr)
    pyproject = _pyproject(
        [_GENEKIT_DEP, "google-cloud-texttospeech>=2.33.0,<3"],
        _classifiers(14),
    )
    with pytest.raises((ValueError, TypeError)):
        getattr(check_pins, check)(pyproject, _fake_fetch({url: payload}))


@pytest.mark.parametrize(
    "readme",
    ["No date here.\n", "checked on **2 Septembre 2026**\n", "checked on **31 September 2026**\n"],
    ids=["absent", "unknown-month", "impossible-day"],
)
def test_pricing_checked_on_raises_on_unusable_date(check_pins: Any, readme: str) -> None:
    with pytest.raises(ValueError, match=r"checked on|month|day|match"):
        check_pins.pricing_checked_on(readme)


@pytest.mark.parametrize(
    ("dep", "expected"),
    [
        ("google-cloud-texttospeech>=2.33.0,<3", 3),
        ("google-cloud-texttospeech >=2.33.0, < 10", 10),
        ("google-cloud-texttospeech>=2.33.0", None),
        ("google-cloud-texttospeech>=2.33.0; python_version < '3.13'", None),
    ],
    ids=["tight", "spaced-two-digit", "uncapped", "marker-lt-not-a-cap"],
)
def test_tts_cap_parses_upper_bound(check_pins: Any, dep: str, expected: int | None) -> None:
    assert check_pins.tts_cap(_pyproject(["other<9", dep])) == expected


# --------------------------------------------------------------------------- git wiring


def test_check_release_due_diffs_lock_from_latest_v_tag(check_pins: Any) -> None:
    calls: list[list[str]] = []

    def _git(args: Sequence[str]) -> str:
        calls.append(list(args))
        return "v0.2.1\n" if args[0] == "describe" else ""

    check_pins.check_release_due(_git)
    describe, diff = calls
    assert "v*" in describe
    assert "v0.2.1..HEAD" in diff
    assert diff[-1] == "uv.lock"


def test_run_git_cli_runs_checked_git_in_cwd(
    check_pins: Any,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen: dict[str, Any] = {}

    def _run(argv: list[str], **kwargs: Any) -> Any:
        seen["argv"] = argv
        seen.update(kwargs)
        return type("Done", (), {"stdout": "out"})()

    monkeypatch.setattr(check_pins.subprocess, "run", _run)
    assert check_pins.run_git_cli(["status"], cwd=tmp_path) == "out"
    assert seen["argv"] == ["git", "status"]
    assert seen["cwd"] == tmp_path
    assert seen["check"] is True


# ------------------------------------------------------------------------- run_checks


def test_failed_check_becomes_error_finding(check_pins: Any, tmp_path: Path) -> None:
    findings = check_pins.run_checks(
        repo_root=_repo(tmp_path),
        fetch_json=_offline,
        run_git=_fake_git("v0.2.1\n", ""),
        today=_TODAY,
    )
    by_check = {f.check: f for f in findings}
    for check_id in ("genekit-error", "python-ceiling-error", "tts-major-error"):
        assert check_id in by_check
        assert "offline" in by_check[check_id].message


def test_missing_pyproject_is_a_finding_not_a_crash(check_pins: Any, tmp_path: Path) -> None:
    findings = check_pins.run_checks(
        repo_root=tmp_path,
        fetch_json=_offline,
        run_git=_fake_git("v0.2.1\n", ""),
        today=_TODAY,
    )
    assert {f.check for f in findings} >= {
        "genekit-error",
        "python-ceiling-error",
        "tts-major-error",
        "pricing-date-error",
    }


# ---------------------------------------------------------------------------- real seams


def test_token_sent_only_to_github_api(
    check_pins: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen: dict[str, Any] = {}

    def _urlopen(request: Any, timeout: float) -> io.StringIO:
        seen[request.full_url] = request.get_header("Authorization")
        return io.StringIO(json.dumps([]))

    monkeypatch.setattr(check_pins.urllib.request, "urlopen", _urlopen)
    check_pins.fetch_json_url(check_pins.GENEKIT_TAGS_URL, token="t")  # noqa: S106
    check_pins.fetch_json_url(check_pins.TTS_PYPI_URL, token="t")  # noqa: S106
    assert seen[check_pins.GENEKIT_TAGS_URL] == "Bearer t"
    assert seen[check_pins.TTS_PYPI_URL] is None


# ------------------------------------------------------------------------------- main


def test_main_writes_report_only_with_findings(
    check_pins: Any,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    repo = _repo(tmp_path)
    report = tmp_path / "report.md"
    git = _fake_git("v0.2.1\n", "")
    common = ["--repo-root", str(repo), "--report", str(report)]

    dirty = _fake_fetch(
        {
            check_pins.GENEKIT_TAGS_URL: [{"name": "py-v0.5.0"}],
            check_pins.PYTHON_RELEASES_URL: [{"name": "Python 3.14.2"}],
            check_pins.TTS_PYPI_URL: {"info": {"version": "2.40.1"}},
        },
    )
    assert check_pins.main(common, fetch_json=dirty, run_git=git, today=_TODAY) == 0
    assert "- [ ] **genekit-pin**" in report.read_text(encoding="utf-8")

    clean = _fake_fetch(
        {
            check_pins.GENEKIT_TAGS_URL: [{"name": "py-v0.4.0"}],
            check_pins.PYTHON_RELEASES_URL: [{"name": "Python 3.14.2"}],
            check_pins.TTS_PYPI_URL: {"info": {"version": "2.40.1"}},
        },
    )
    capsys.readouterr()
    assert check_pins.main(common, fetch_json=clean, run_git=git, today=_TODAY) == 0
    assert not report.exists()
    assert "No findings." in capsys.readouterr().out
