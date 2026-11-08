"""Tests for scripts/release_notes.py, which builds the GitHub Release body."""

from __future__ import annotations

import tomllib
from pathlib import Path
from typing import TYPE_CHECKING, Final

import pytest

if TYPE_CHECKING:
    from collections.abc import Callable
    from types import ModuleType

REPO_ROOT: Final = Path(__file__).resolve().parents[1]

_CHANGELOG: Final = """\
# Changelog

## [Unreleased]

- pending

## [0.2.1] - 2026-01-02

### Fixed

- fixed a thing

## [0.2.0] - 2026-01-01

- older

[Unreleased]: https://example.invalid/compare/v0.2.1...HEAD
[0.2.1]: https://example.invalid/compare/v0.2.0...v0.2.1
"""

_SUMS: Final = "abc  starling-0.2.1-py3-none-any.whl\n"


@pytest.fixture
def release_notes(import_script: Callable[[str], ModuleType]) -> ModuleType:
    return import_script("release_notes.py")


def test_extract_section_returns_body_between_headings(release_notes: ModuleType) -> None:
    body = release_notes.extract_section(_CHANGELOG, "0.2.1")
    assert body == "### Fixed\n\n- fixed a thing"


def test_extract_section_stops_at_link_definitions(release_notes: ModuleType) -> None:
    changelog = "## [0.2.0] - d\n\n- older\n\n[0.2.0]: https://example.invalid/x\n"
    body = release_notes.extract_section(changelog, "0.2.0")
    assert body == "- older"


def test_extract_section_does_not_match_a_longer_version(release_notes: ModuleType) -> None:
    with pytest.raises(ValueError, match=r"no '## \[0\.2\.1\]' section"):
        release_notes.extract_section("## [0.2.10]\n\n- x\n", "0.2.1")


def test_extract_section_treats_version_dots_literally(release_notes: ModuleType) -> None:
    with pytest.raises(ValueError, match="no '## "):
        release_notes.extract_section("## [0x2x1]\n\n- x\n", "0.2.1")


def test_extract_section_crlf_last_section_without_link_definitions(
    release_notes: ModuleType,
) -> None:
    changelog = "## [0.3.0] - d\r\n\r\n- a\r\n\r\n## [0.2.1] - d\r\n\r\n- b\r\n- c\r\n"
    assert release_notes.extract_section(changelog, "0.3.0") == "- a"
    assert release_notes.extract_section(changelog, "0.2.1") == "- b\r\n- c"


def test_extract_section_rejects_empty_section(release_notes: ModuleType) -> None:
    with pytest.raises(ValueError, match="is empty"):
        release_notes.extract_section("## [0.3.0]\n\n## [0.2.1]\n\n- x\n", "0.3.0")


def test_render_notes_includes_checksums_and_verify_commands(release_notes: ModuleType) -> None:
    checksums = "abc  starling-1.2.3-py3-none-any.whl\n"
    notes = release_notes.render_notes("- x", version="1.2.3", repo="o/r", checksums=checksums)
    assert notes.startswith("- x\n")
    assert f"```\n{checksums.strip()}\n```" in notes
    assert "gh attestation verify starling-1.2.3-py3-none-any.whl --repo o/r" in notes
    assert notes.endswith("\n")


def test_main_writes_notes_file(release_notes: ModuleType, tmp_path: Path) -> None:
    changelog = tmp_path / "CHANGELOG.md"
    changelog.write_text(_CHANGELOG, encoding="utf-8")
    sums = tmp_path / "SHA256SUMS"
    sums.write_text(_SUMS, encoding="utf-8")
    out = tmp_path / "notes.md"
    code = release_notes.main(
        [
            "--version=0.2.1",
            f"--changelog={changelog}",
            f"--checksums={sums}",
            "--repo=o/r",
            f"--out={out}",
        ],
    )
    assert code == 0
    assert out.read_text(encoding="utf-8").startswith("### Fixed\n\n- fixed a thing")


def test_main_reports_missing_section_as_workflow_error(
    release_notes: ModuleType,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    changelog = tmp_path / "CHANGELOG.md"
    changelog.write_text(_CHANGELOG, encoding="utf-8")
    sums = tmp_path / "SHA256SUMS"
    sums.write_text(_SUMS, encoding="utf-8")
    out = tmp_path / "notes.md"
    code = release_notes.main(
        [
            "--version=9.9.9",
            f"--changelog={changelog}",
            f"--checksums={sums}",
            "--repo=o/r",
            f"--out={out}",
        ],
    )
    assert code == 1
    assert capsys.readouterr().out.startswith("::error::")
    assert not out.exists()


def test_real_changelog_packaged_version_section_extracts(release_notes: ModuleType) -> None:
    """Guards CHANGELOG format drift: the version being packaged must have a body."""
    pyproject = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    version = pyproject["project"]["version"]
    changelog = (REPO_ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    assert release_notes.extract_section(changelog, version)
