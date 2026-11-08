"""
Check the pins Dependabot cannot see and write a markdown report of what is due.

``.github/workflows/maintenance-check.yml`` runs this monthly. It checks the genekit git
tag pinned in ``pyproject.toml``, the CPython ceiling in ``classifiers``, the
``google-cloud-texttospeech`` major cap, the README pricing "checked on" date, and whether
``uv.lock`` has moved since the last ``v*`` tag. Every check is a pure function over parsed
inputs plus injected ``fetch_json`` / ``run_git`` / ``today`` seams. A check that raises
becomes a ``<id>-error`` finding, so a network or parse failure is visible in the issue and
never reads as a pass. The report is written only when there are findings; the workflow
turns it into one tracking issue. Findings are not failures: the exit code is always 0.
"""

from __future__ import annotations

import argparse
import functools
import json
import os
import re
import subprocess
import tomllib
import urllib.request
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Final

from starling.update_check import is_update_available, normalize_version

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable, Sequence

GENEKIT_TAGS_URL: Final = "https://api.github.com/repos/TheGeneCode/genekit/tags?per_page=100"
PYTHON_RELEASES_URL: Final = (
    "https://www.python.org/api/v2/downloads/release/?is_published=true&pre_release=false"
)
TTS_PYPI_URL: Final = "https://pypi.org/pypi/google-cloud-texttospeech/json"
PRICING_URL: Final = "https://cloud.google.com/text-to-speech/pricing"
PRICING_MAX_AGE_DAYS: Final = 90
_TIMEOUT_SECONDS: Final = 20
_GENEKIT_PIN: Final = re.compile(
    r"genekit @ git\+https://github\.com/TheGeneCode/genekit@py-v(\d+\.\d+\.\d+)"
)
_PY_TAG: Final = re.compile(r"^py-v(\d+\.\d+\.\d+)$")
_PY_CLASSIFIER: Final = re.compile(r"^Programming Language :: Python :: 3\.(\d+)$")
_PY_RELEASE_NAME: Final = re.compile(r"^Python 3\.(\d+)\.(\d+)$")
_PRICING_DATE: Final = re.compile(r"checked on \*\*(\d{1,2} [A-Z][a-z]+ \d{4})\*\*")
_TTS_CAP: Final = re.compile(r"^google-cloud-texttospeech\b[^;]*<\s*(\d+)")
_GITHUB_API_PREFIX: Final = "https://api.github.com/"

type FetchJson = Callable[[str], object]
type RunGit = Callable[[Sequence[str]], str]


@dataclass(frozen=True, slots=True)
class Finding:
    """One due item; ``message`` lands in a public issue, so it carries no local paths."""

    # Stable id: "genekit-pin" | "python-ceiling" | "pricing-date" | "release-due" |
    # "tts-major" | "<guard id>-error".
    check: str
    # One markdown sentence.
    message: str


# --------------------------------------------------------------------------- parsing


def _project_strings(pyproject: dict[str, object], key: str) -> list[str]:
    """Return ``[project].<key>`` as a list of strings; ``ValueError`` on any other shape."""
    project = pyproject.get("project")
    values = project.get(key) if isinstance(project, dict) else None
    if not isinstance(values, list) or not all(isinstance(v, str) for v in values):
        msg = f"pyproject.toml has no [project].{key} list of strings"
        raise ValueError(msg)
    return values


def _read_pyproject(repo_root: Path) -> dict[str, object]:
    with (repo_root / "pyproject.toml").open("rb") as handle:
        return tomllib.load(handle)


def _read_readme(repo_root: Path) -> str:
    return (repo_root / "README.md").read_text(encoding="utf-8")


# --------------------------------------------------------------------------- genekit


def genekit_pin(pyproject: dict[str, object]) -> str:
    """Return the pinned genekit version (``"0.4.0"`` for ``...@py-v0.4.0``)."""
    for dependency in _project_strings(pyproject, "dependencies"):
        if match := _GENEKIT_PIN.search(dependency):
            return match.group(1)
    raise ValueError("pyproject.toml has no genekit @ git+...@py-vX.Y.Z dependency")


def latest_py_tag(names: Iterable[str]) -> str | None:
    """Return the newest ``py-vX.Y.Z`` version among ``names`` (numeric order), or None."""
    versions = [match.group(1) for name in names if (match := _PY_TAG.match(name))]
    return max(versions, key=normalize_version, default=None)


def check_genekit(pyproject: dict[str, object], fetch_json: FetchJson) -> Finding | None:
    pin = genekit_pin(pyproject)
    tags = fetch_json(GENEKIT_TAGS_URL)
    if not isinstance(tags, list):
        msg = f"GitHub tags response is a {type(tags).__name__}, not a list"
        raise TypeError(msg)
    names = [
        name for tag in tags if isinstance(tag, dict) and isinstance(name := tag.get("name"), str)
    ]
    latest = latest_py_tag(names)
    if latest is None:
        # No py-v* tag at all means the response is not what this check expects.
        raise ValueError("GitHub tags response has no py-vX.Y.Z tag")
    if not is_update_available(pin, latest):
        return None
    return Finding(
        "genekit-pin",
        f"genekit is pinned at `py-v{pin}`; the newest tag is `py-v{latest}`. "
        "Bump the pin in pyproject.toml and run `uv lock`.",
    )


# --------------------------------------------------------------------------- python


def python_ceiling(pyproject: dict[str, object]) -> int:
    """Return the highest Python 3 minor listed in ``classifiers``."""
    minors = [
        int(match.group(1))
        for classifier in _project_strings(pyproject, "classifiers")
        if (match := _PY_CLASSIFIER.match(classifier))
    ]
    if not minors:
        raise ValueError("pyproject.toml has no 'Programming Language :: Python :: 3.N' classifier")
    return max(minors)


def newest_stable_minor(releases: object) -> int | None:
    """Return the highest minor among python.org release names ``Python 3.N.M``, or None."""
    if not isinstance(releases, list):
        msg = f"python.org releases response is a {type(releases).__name__}, not a list"
        raise TypeError(msg)
    minors = [
        int(match.group(1))
        for release in releases
        if isinstance(release, dict)
        and isinstance(name := release.get("name"), str)
        and (match := _PY_RELEASE_NAME.match(name))
    ]
    return max(minors, default=None)


def check_python_ceiling(pyproject: dict[str, object], fetch_json: FetchJson) -> Finding | None:
    ceiling = python_ceiling(pyproject)
    newest = newest_stable_minor(fetch_json(PYTHON_RELEASES_URL))
    if newest is None:
        # No "Python 3.N.M" name at all means the response shape changed.
        raise ValueError("python.org releases response has no 'Python 3.N.M' release")
    if newest <= ceiling:
        return None
    return Finding(
        "python-ceiling",
        f"`classifiers` and the CI matrix stop at Python 3.{ceiling}; "
        f"Python 3.{newest} is released. Add it to both once the suite passes on it.",
    )


# --------------------------------------------------------------------------- pricing


def pricing_checked_on(readme: str) -> date:
    """Return the README pricing ``checked on **D Month YYYY**`` date."""
    match = _PRICING_DATE.search(readme)
    if match is None:
        raise ValueError("README.md has no 'checked on **D Month YYYY**' pricing date")
    return datetime.strptime(match.group(1), "%d %B %Y").replace(tzinfo=UTC).date()


def check_pricing_date(readme: str, today: date) -> Finding | None:
    checked = pricing_checked_on(readme)
    age = (today - checked).days
    if age <= PRICING_MAX_AGE_DAYS:
        return None
    # checked.day, not %-d: Windows strftime rejects %-d.
    return Finding(
        "pricing-date",
        f"README § What It Costs was last checked on {checked.day} {checked:%B %Y} "
        f"({age} days ago). Re-check {PRICING_URL} and update the date.",
    )


# --------------------------------------------------------------------------- release


def check_release_due(run_git: RunGit) -> Finding | None:
    tag = run_git(["describe", "--tags", "--abbrev=0", "--match", "v*"]).strip()
    changed = run_git(["diff", "--name-only", f"{tag}..HEAD", "--", "uv.lock"]).strip()
    if not changed:
        return None
    return Finding(
        "release-due",
        f"`uv.lock` has changed since `{tag}`; a release would ship the updated dependency set.",
    )


# --------------------------------------------------------------------------- tts


def tts_cap(pyproject: dict[str, object]) -> int | None:
    """Return N for ``google-cloud-texttospeech...<N``, or None when uncapped."""
    for dependency in _project_strings(pyproject, "dependencies"):
        if match := _TTS_CAP.match(dependency):
            return int(match.group(1))
    return None


def check_tts_major(pyproject: dict[str, object], fetch_json: FetchJson) -> Finding | None:
    cap = tts_cap(pyproject)
    if cap is None:
        return None
    payload = fetch_json(TTS_PYPI_URL)
    info = payload.get("info") if isinstance(payload, dict) else None
    latest = info.get("version") if isinstance(info, dict) else None
    if not isinstance(latest, str) or not normalize_version(latest):
        # An unparseable version would compare as () and read as a silent pass.
        msg = f"PyPI response has no parseable info.version (got {latest!r})"
        raise ValueError(msg)
    if normalize_version(latest)[:1] < (cap,):
        return None
    return Finding(
        "tts-major",
        f"`google-cloud-texttospeech` is capped below {cap}, and {latest} is on PyPI. "
        "Test against it, then raise the cap and run `uv lock`.",
    )


# --------------------------------------------------------------------------- orchestration


def _guard(check_id: str, thunk: Callable[[], Finding | None]) -> Finding | None:
    """Run ``thunk``; any exception becomes a ``<check_id>-error`` finding, never a pass."""
    try:
        return thunk()
    except Exception as exc:
        return Finding(
            f"{check_id}-error",
            f"Check `{check_id}` could not run: {type(exc).__name__}: {exc}",
        )


def run_checks(
    *, repo_root: Path, fetch_json: FetchJson, run_git: RunGit, today: date
) -> list[Finding]:
    """Run every check in a fixed order; files are read inside the guards."""
    checks: list[tuple[str, Callable[[], Finding | None]]] = [
        ("genekit", lambda: check_genekit(_read_pyproject(repo_root), fetch_json)),
        ("python-ceiling", lambda: check_python_ceiling(_read_pyproject(repo_root), fetch_json)),
        ("tts-major", lambda: check_tts_major(_read_pyproject(repo_root), fetch_json)),
        ("pricing-date", lambda: check_pricing_date(_read_readme(repo_root), today)),
        ("release-due", lambda: check_release_due(run_git)),
    ]
    results = [_guard(check_id, thunk) for check_id, thunk in checks]
    return [finding for finding in results if finding is not None]


def render_report(findings: Sequence[Finding], today: date) -> str:
    """Return the tracking-issue body: one checkbox per finding."""
    items = "\n".join(f"- [ ] **{f.check}**: {f.message}" for f in findings)
    return (
        f"Automated monthly check, run {today.isoformat()}. "
        "Edit nothing here; the next run rewrites this body.\n"
        "\n"
        f"{items}\n"
        "\n"
        "Generated by `.github/workflows/maintenance-check.yml` (`scripts/check_pins.py`). "
        "Close this issue once every box is done; the next run reopens a new one if anything "
        "is still due.\n"
    )


# --------------------------------------------------------------------------- real seams


def fetch_json_url(url: str, *, token: str | None = None) -> object:
    """GET ``url`` as JSON; ``token`` is sent only to the GitHub API, never elsewhere."""
    headers = {"Accept": "application/json", "User-Agent": "starling-maintenance-check"}
    if token and url.startswith(_GITHUB_API_PREFIX):
        headers["Authorization"] = f"Bearer {token}"
    # S310: every URL passed here is a fixed https constant defined in this module.
    request = urllib.request.Request(url, headers=headers)  # noqa: S310
    with urllib.request.urlopen(request, timeout=_TIMEOUT_SECONDS) as response:  # noqa: S310
        return json.load(response)


def run_git_cli(args: Sequence[str], *, cwd: Path) -> str:
    """Run ``git <args>`` in ``cwd`` and return stdout; raises on a non-zero exit."""
    # S603/S607: args are fixed, repo-internal git subcommands, never user input; git is
    # resolved from PATH deliberately, matching capture.py's subprocess.Popen precedent.
    completed = subprocess.run(  # noqa: S603
        ["git", *args],  # noqa: S607
        check=True,
        capture_output=True,
        text=True,
        cwd=cwd,
    )
    return completed.stdout


def main(
    argv: Sequence[str] | None = None,
    *,
    fetch_json: FetchJson | None = None,
    run_git: RunGit | None = None,
    today: date | None = None,
) -> int:
    """Parse arguments, run the checks, write or delete the report, and return 0."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[1])
    parser.add_argument("--repo-root", type=Path, default=Path(), help="repository root")
    parser.add_argument(
        "--report", type=Path, required=True, help="markdown report to write when anything is due"
    )
    args = parser.parse_args(argv)
    repo_root: Path = args.repo_root
    report: Path = args.report

    if fetch_json is None:
        fetch_json = functools.partial(fetch_json_url, token=os.environ.get("GITHUB_TOKEN"))
    if run_git is None:
        run_git = functools.partial(run_git_cli, cwd=repo_root)
    if today is None:
        today = datetime.now(UTC).date()

    findings = run_checks(repo_root=repo_root, fetch_json=fetch_json, run_git=run_git, today=today)
    if findings:
        report.write_text(render_report(findings, today), encoding="utf-8")
        print(f"{len(findings)} finding(s); report at {report}")
    else:
        report.unlink(missing_ok=True)
        print("No findings.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
