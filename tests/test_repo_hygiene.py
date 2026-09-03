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


_FREE_TIER_HEADING: Final = "## Staying on the Free Tier"


def _readme_text() -> str:
    return (REPO_ROOT / "README.md").read_text(encoding="utf-8")


def _github_anchor(heading_text: str) -> str:
    """Slugify a markdown heading the way GitHub does for its auto-generated anchors."""
    slug = heading_text.strip().lower()
    slug = re.sub(r"[^\w\s-]", "", slug)
    return re.sub(r"\s+", "-", slug)


# ``## `` / ``### `` / ``#### `` at column 0 only -- deliberately excludes ``# `` (h1, the
# document title, never gets a TOC entry) and ``##### ``/``###### `` (h5/h6, never used in this
# README), and excludes a heading nested inside a blockquote (e.g. ``> ### like this``) since
# that line does not start with ``#``. GitHub's autolink-header extension does anchor
# blockquoted headings too, so this is a known, deliberate scope limit, not a fixed gap.
_HEADING_PATTERN: Final = re.compile(r"^#{2,4} (.+)$", re.MULTILINE)

# A TOC entry, optionally indented (a nested/sub-bullet TOC entry is still a TOC entry), whose
# link target is an in-page anchor (``(#...)``). A bullet linking to a full URL
# (``- [text](https://...)``) deliberately does not match: it has no ``#`` immediately after
# the opening paren.
_TOC_LINK_PATTERN: Final = re.compile(r"^\s*- \[.+?\]\(#(.+?)\)$", re.MULTILINE)


def _readme_headings(text: str) -> list[str]:
    return _HEADING_PATTERN.findall(text)


def _readme_heading_anchors(text: str) -> dict[str, list[str]]:
    """Map each GitHub anchor to the (possibly several) heading texts that slugify to it."""
    anchors: dict[str, list[str]] = {}
    for heading in _readme_headings(text):
        anchors.setdefault(_github_anchor(heading), []).append(heading)
    return anchors


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


def test_readme_documents_staying_on_the_free_tier() -> None:
    text = _readme_text()
    assert text.count(_FREE_TIER_HEADING) == 1
    assert "(#staying-on-the-free-tier)" in text


def test_every_readme_toc_link_resolves_to_a_heading() -> None:
    text = _readme_text()
    toc_anchors = _TOC_LINK_PATTERN.findall(text)
    assert toc_anchors, "expected at least one TOC link in README.md"

    heading_anchors = set(_readme_heading_anchors(text))
    unresolved = [anchor for anchor in toc_anchors if anchor not in heading_anchors]
    assert not unresolved, f"TOC anchors with no matching heading: {unresolved}"


def test_readme_headings_have_unique_anchors() -> None:
    collisions = {
        anchor: names
        for anchor, names in _readme_heading_anchors(_readme_text()).items()
        if len(names) > 1
    }
    assert not collisions, f"headings collide on the same anchor: {collisions}"


def test_every_readme_top_level_heading_has_a_toc_entry() -> None:
    """
    Reverse direction from ``test_every_readme_toc_link_resolves_to_a_heading``.

    That test catches a stale/typo'd TOC link. It does not catch the opposite mistake: a new
    ``##`` section added without ever adding it to the Table of Contents, which would silently
    ship an undiscoverable section rather than fail any check.
    """
    text = _readme_text()
    toc_anchors = set(_TOC_LINK_PATTERN.findall(text))
    top_level_headings = re.findall(r"^## (.+)$", text, flags=re.MULTILINE)
    orphaned = [
        heading
        for heading in top_level_headings
        if heading != "Table of Contents" and _github_anchor(heading) not in toc_anchors
    ]
    assert not orphaned, f"top-level headings missing a TOC entry: {orphaned}"


def test_github_anchor_pins_the_real_code_span_heading() -> None:
    """
    Pin risk area 1 (an inline code span in a heading) against the real README.

    Uses the one heading that actually has this shape:
    ``### 2. Preview every batch with `--dry-run` ``. The backticks are stripped like any other
    punctuation, and the surrounding space collapses to a hyphen adjacent to the two literal
    hyphens already in ``--dry-run``, producing a run of three hyphens -- not a bug, just the
    documented, non-collapsing behavior of the second ``re.sub`` call.
    """
    text = _readme_text()
    headings = _readme_headings(text)
    matches = [h for h in headings if "--dry-run" in h]
    assert len(matches) == 1, f"expected exactly one heading mentioning --dry-run, got {matches}"
    anchor = _github_anchor(matches[0])
    assert anchor == "2-preview-every-batch-with---dry-run"
    assert anchor in _readme_heading_anchors(text)


@pytest.mark.parametrize(
    ("heading_text", "expected_anchor"),
    [
        pytest.param("Preview `--dry-run`", "preview---dry-run", id="inline_code_span"),
        pytest.param("Starling's Voice", "starlings-voice", id="apostrophe"),
        pytest.param("APIs & Services", "apis-services", id="ampersand"),
        pytest.param("Step 2: Enable Billing", "step-2-enable-billing", id="numbers_and_colon"),
        pytest.param("Café Résumé", "café-résumé", id="unicode_accented"),
        pytest.param("", "", id="empty_string"),
        pytest.param("   ", "", id="whitespace_only"),
        pytest.param("Choosing   a   Voice", "choosing-a-voice", id="multiple_consecutive_spaces"),
        pytest.param("Wrap-up!", "wrap-up", id="trailing_punctuation"),
        pytest.param("ALL CAPS Heading", "all-caps-heading", id="mixed_case_is_lowered"),
        pytest.param("Already-Hyphenated", "already-hyphenated", id="existing_hyphen_preserved"),
    ],
)
def test_github_anchor_examples(heading_text: str, expected_anchor: str) -> None:
    assert _github_anchor(heading_text) == expected_anchor


def test_github_anchor_empty_and_whitespace_only_headings_collide() -> None:
    """
    Document risk area 5: a fully empty heading and a whitespace-only one collide.

    Both slugify to ``""``. Neither shape exists in the real README today (a bare ``## `` with
    nothing after it does not even satisfy the heading regex's required ``(.+)``, so it is
    never captured at all), but a whitespace-only heading such as ``##  `` (two spaces) *does*
    satisfy ``(.+)`` and would collide with any other degenerate heading. Isolated so the edge
    case has coverage independent of what the README currently contains.
    """
    assert _github_anchor("") == _github_anchor("   ") == ""


def test_readme_heading_anchors_detects_a_manufactured_collision() -> None:
    """
    Positive control for ``test_readme_headings_have_unique_anchors``.

    The real README has no colliding headings today, which means that test could be green
    either because the detection logic works or because it never runs against a colliding
    case. Feed ``_readme_heading_anchors`` synthetic text with two headings that differ only in
    case and trailing punctuation -- both slugify to ``setup`` -- and confirm the collision is
    actually reported.
    """
    text = "## Setup\n\nsome text\n\n### setup!\n\nmore text\n"
    anchors = _readme_heading_anchors(text)
    assert anchors["setup"] == ["Setup", "setup!"]


def test_toc_link_pattern_allows_indentation_but_not_external_links() -> None:
    """
    Risk area 2: the TOC-link regex must accept indentation but not an external link.

    It must resolve a nested/indented TOC entry (a sub-bullet under a top-level TOC item) the
    same as a flat one, and must not pick up an unrelated bullet that links to a full URL
    rather than an in-page anchor. The real README currently has neither shape (confirmed: no
    indented ``- [`` bullet and no other ``- [text](url)`` bullet exists outside the flat TOC),
    so this is exercised in isolation rather than depending on the README happening to contain
    one.
    """
    text = (
        "- [Top Entry](#top-entry)\n"
        "  - [Nested Entry](#nested-entry)\n"
        "- [External Link](https://example.com)\n"
        "- Plain bullet, no link at all\n"
    )
    assert _TOC_LINK_PATTERN.findall(text) == ["top-entry", "nested-entry"]


def test_heading_pattern_excludes_h1_h5_and_blockquoted_headings() -> None:
    """
    Document the deliberate scope of ``_HEADING_PATTERN``.

    An h1 (the document title, which never gets a TOC entry), an h5, and a heading nested
    inside a blockquote (``> ### ...``, which the real README actually has at the
    JSON-key-is-a-credential callout) are all outside what this check considers. The
    blockquoted case is a known, un-fixed limitation -- GitHub's real anchor generation does
    cover blockquoted headings -- called out here rather than silently assumed.
    """
    text = (
        "# Document Title\n"
        "## Included Section\n"
        "##### Also Excluded\n"
        "> ### Blockquoted Heading\n"
    )
    assert _readme_headings(text) == ["Included Section"]


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


def test_env_example_documents_capture_confirm() -> None:
    """Verify that .env.example and README.md both mention STARLING_CAPTURE_CONFIRM."""
    env_example = (REPO_ROOT / ".env.example").read_text(encoding="utf-8")
    readme = (REPO_ROOT / "README.md").read_text(encoding="utf-8")
    assert "STARLING_CAPTURE_CONFIRM" in env_example
    assert "STARLING_CAPTURE_CONFIRM" in readme


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
