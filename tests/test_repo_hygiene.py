"""
Repo-hygiene checks.

These should not depend on someone remembering to run the pre-publish checklist again for
the next release. The git-invoking tests skip when there is no ``.git`` directory (an sdist
install has no history to inspect) rather than failing.
"""

from __future__ import annotations

import re
import subprocess
import tomllib
from pathlib import Path
from typing import Final

import pytest

REPO_ROOT: Final = Path(__file__).resolve().parents[1]

_CREDENTIAL_NAMES: Final = frozenset({".env", "tts-service-account.json", "SGU.py"})
_CREDENTIAL_SUFFIXES: Final = frozenset({".pem", ".key", ".p12"})


def _run_git(*args: str) -> subprocess.CompletedProcess[str]:
    # S603/S607: args are fixed, repo-internal git subcommands, never user input; git is
    # resolved from PATH deliberately, matching capture.py's subprocess.Popen precedent.
    return subprocess.run(  # noqa: S603
        ["git", *args],  # noqa: S607
        check=False,
        capture_output=True,
        text=True,
        cwd=REPO_ROOT,
    )


def _require_git() -> None:
    if _run_git("rev-parse", "--git-dir").returncode != 0:
        pytest.skip("no .git directory available (e.g. an sdist install)")


def _changelog_text() -> str:
    return (REPO_ROOT / "CHANGELOG.md").read_text(encoding="utf-8")


def test_changelog_has_no_duplicate_version_headings() -> None:
    headings = re.findall(r"^## \[(.+?)\]", _changelog_text(), flags=re.MULTILINE)
    assert len(headings) == len(set(headings)), f"duplicate changelog headings: {headings}"


def test_changelog_has_no_duplicate_link_definitions() -> None:
    labels = re.findall(r"^\[(.+?)\]: ", _changelog_text(), flags=re.MULTILINE)
    assert len(labels) == len(set(labels)), f"duplicate changelog link definitions: {labels}"


def test_every_changelog_version_has_a_link_definition() -> None:
    text = _changelog_text()
    headings = set(re.findall(r"^## \[(.+?)\]", text, flags=re.MULTILINE)) - {"Unreleased"}
    labels = set(re.findall(r"^\[(.+?)\]: ", text, flags=re.MULTILINE)) - {"Unreleased"}
    assert headings == labels


def test_changelog_has_a_section_for_the_packaged_version() -> None:
    pyproject = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    version = pyproject["project"]["version"]
    assert f"## [{version}]" in _changelog_text()


def test_tracked_docs_contain_no_real_home_directory() -> None:
    _require_git()
    result = _run_git("ls-files", "*.md")
    tracked_md = [REPO_ROOT / line for line in result.stdout.splitlines() if line]
    assert tracked_md, "expected at least one tracked markdown file"

    windows_marker = f"C:\\Users\\{Path.home().name}"
    posix_marker = f"/home/{Path.home().name}"
    offenders = [
        str(path)
        for path in tracked_md
        if windows_marker in path.read_text(encoding="utf-8")
        or posix_marker in path.read_text(encoding="utf-8")
    ]
    assert not offenders, f"real home directory leaked into: {offenders}"


def test_no_credential_files_are_tracked() -> None:
    _require_git()
    result = _run_git("ls-files")
    tracked = result.stdout.splitlines()
    offenders = [
        line
        for line in tracked
        if Path(line).name in _CREDENTIAL_NAMES or Path(line).suffix in _CREDENTIAL_SUFFIXES
    ]
    assert not offenders, f"credential-shaped files are tracked: {offenders}"


def test_sgu_is_absent_from_all_history() -> None:
    _require_git()
    result = _run_git("log", "--all", "--name-only", "--pretty=format:")
    hits = [line for line in result.stdout.splitlines() if line.strip() == "SGU.py"]
    assert not hits, "SGU.py reappeared in history"


def test_env_example_documents_the_update_check_optout() -> None:
    from starling.update_check import UPDATE_CHECK_VAR

    env_example = (REPO_ROOT / ".env.example").read_text(encoding="utf-8")
    assert UPDATE_CHECK_VAR in env_example
