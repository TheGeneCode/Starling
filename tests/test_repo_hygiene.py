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
from typing import TYPE_CHECKING, Final

import pytest

if TYPE_CHECKING:
    from collections.abc import Callable

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


def _run_git_checked(*args: str) -> str:
    """
    Run a git subcommand that is expected to succeed once ``_require_git`` has passed.

    ``_run_git`` uses ``check=False`` deliberately so ``_require_git`` can distinguish "no
    .git directory" (skip) from other failures without an exception. But that means a git
    call which fails for a *different* reason after ``_require_git`` already passed --
    a corrupted index, a permission error, a detached/bare-repo edge case -- would otherwise
    hand back an empty ``stdout`` that reads exactly like "nothing to report", making the
    hygiene test it feeds pass vacuously instead of failing loudly. Assert success here so
    that failure mode surfaces as a test failure, not a silent green check.
    """
    result = _run_git(*args)
    assert result.returncode == 0, f"git {' '.join(args)} failed: {result.stderr}"
    return result.stdout


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
    stdout = _run_git_checked("ls-files", "*.md")
    tracked_md = [REPO_ROOT / line for line in stdout.splitlines() if line]
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
    tracked = _run_git_checked("ls-files").splitlines()
    offenders = [
        line
        for line in tracked
        if Path(line).name in _CREDENTIAL_NAMES or Path(line).suffix in _CREDENTIAL_SUFFIXES
    ]
    assert not offenders, f"credential-shaped files are tracked: {offenders}"


def test_sgu_is_absent_from_all_history() -> None:
    _require_git()
    stdout = _run_git_checked("log", "--all", "--name-only", "--pretty=format:")
    hits = [line for line in stdout.splitlines() if line.strip() == "SGU.py"]
    assert not hits, "SGU.py reappeared in history"


def test_env_example_documents_the_update_check_optout() -> None:
    from starling.update_check import UPDATE_CHECK_VAR

    env_example = (REPO_ROOT / ".env.example").read_text(encoding="utf-8")
    assert UPDATE_CHECK_VAR in env_example


# ---------------------------------------------------------------------------
# _require_git / _run_git_checked -- the git-invoking tests must fail loudly,
# not silently pass, when git itself is broken rather than merely absent.
# ---------------------------------------------------------------------------


def _fake_subprocess_run(
    *, git_dir_ok: bool, other_returncode: int, other_stdout: str = "", other_stderr: str = "boom"
) -> Callable[..., subprocess.CompletedProcess[str]]:
    """
    Build a fake ``subprocess.run`` that answers ``rev-parse --git-dir`` and other git calls differently.

    Models a repo that *has* a ``.git`` directory (so ``_require_git`` never skips) but
    where some other git invocation fails -- a corrupted index, a permission error, a
    detached-HEAD or bare-repo quirk. That is exactly the failure mode ``check=False``
    cannot distinguish from "nothing to report" without an explicit returncode check.
    """

    def _fake(cmd: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
        if "rev-parse" in cmd:
            returncode = 0 if git_dir_ok else 128
            return subprocess.CompletedProcess(cmd, returncode, stdout=".git", stderr="")
        return subprocess.CompletedProcess(
            cmd, other_returncode, stdout=other_stdout, stderr=other_stderr
        )

    return _fake


def test_require_git_skips_when_no_git_dir(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        subprocess, "run", _fake_subprocess_run(git_dir_ok=False, other_returncode=0)
    )
    with pytest.raises(pytest.skip.Exception):
        _require_git()


def test_require_git_does_not_skip_when_git_dir_present(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        subprocess, "run", _fake_subprocess_run(git_dir_ok=True, other_returncode=0)
    )
    _require_git()  # must not raise or skip


def test_run_git_checked_returns_stdout_on_success(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        subprocess,
        "run",
        _fake_subprocess_run(git_dir_ok=True, other_returncode=0, other_stdout="a.py\nb.py\n"),
    )
    assert _run_git_checked("ls-files") == "a.py\nb.py\n"


def test_run_git_checked_raises_loudly_when_git_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    """
    Test the boundary this helper exists for: a non-``rev-parse`` git call returning nonzero.

    Before ``_run_git_checked`` existed, this exact scenario (git present, ``.git`` dir
    found, but ``ls-files``/``log`` failing) made the credential-scan and history-scan
    hygiene tests pass vacuously on empty ``stdout`` -- see the two regression tests below,
    which reproduce that failure mode against the actual hygiene test functions.
    """
    monkeypatch.setattr(
        subprocess,
        "run",
        _fake_subprocess_run(git_dir_ok=True, other_returncode=128, other_stderr="fatal: boom"),
    )
    with pytest.raises(AssertionError, match="fatal: boom"):
        _run_git_checked("ls-files")


def test_no_credential_files_are_tracked_fails_loudly_when_git_ls_files_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Regression test: a broken `git ls-files` must no longer read as "zero credential files"."""
    monkeypatch.setattr(
        subprocess, "run", _fake_subprocess_run(git_dir_ok=True, other_returncode=128)
    )
    with pytest.raises(AssertionError):
        test_no_credential_files_are_tracked()


def test_sgu_is_absent_from_all_history_fails_loudly_when_git_log_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Regression test: a broken `git log --all` must no longer read as "SGU.py never existed"."""
    monkeypatch.setattr(
        subprocess, "run", _fake_subprocess_run(git_dir_ok=True, other_returncode=128)
    )
    with pytest.raises(AssertionError):
        test_sgu_is_absent_from_all_history()
