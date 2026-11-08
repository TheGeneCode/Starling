"""
Write the GitHub Release notes for one version.

The notes are that version's section of CHANGELOG.md followed by a "Verify your
download" block (SHA256 checksums plus the commands that check them and the build
provenance attestation). ``.github/workflows/release.yml`` calls this script with the
system ``python3`` before publishing, so it uses only the standard library. A missing or
empty CHANGELOG section prints a ``::error::`` workflow command and exits 1, which fails
the release before anything is published.
"""

from __future__ import annotations

import argparse
import re
from pathlib import Path
from typing import TYPE_CHECKING, Final

if TYPE_CHECKING:
    from collections.abc import Sequence

# Any level-2 heading ends a section.
_HEADING: Final = re.compile(r"^## ", re.MULTILINE)
# So does the link-definition block that closes the file.
_LINK_DEF: Final = re.compile(r"^\[[^\]]+\]: ", re.MULTILINE)


def extract_section(changelog: str, version: str) -> str:
    r"""
    Return the body under ``## [version]`` (heading line excluded), stripped.

    The body ends at the next line starting with ``## `` or at the first link
    definition (``[x]: url``), whichever comes first. ``re.escape(version)`` plus the
    literal ``\]`` means ``0.2.1`` never matches ``## [0.2.10]``.

    >>> extract_section("## [1.0.0]\n- a\n\n## [0.9.0]\n- b\n", "1.0.0")
    '- a'

    Raises:
        ValueError: The section is absent, or its body is blank.

    """
    heading = re.search(rf"^## \[{re.escape(version)}\][^\n]*$", changelog, re.MULTILINE)
    if heading is None:
        msg = f"CHANGELOG.md has no '## [{version}]' section."
        raise ValueError(msg)
    start = heading.end()
    matches = (pattern.search(changelog, start) for pattern in (_HEADING, _LINK_DEF))
    end = min((m.start() for m in matches if m), default=len(changelog))
    body = changelog[start:end].strip()
    if not body:
        msg = f"CHANGELOG.md's '## [{version}]' section is empty."
        raise ValueError(msg)
    return body


def render_notes(section: str, *, version: str, repo: str, checksums: str) -> str:
    """Return the full release-notes text: the CHANGELOG section plus a verify block."""
    wheel = f"starling-{version}-py3-none-any.whl"
    return (
        f"{section}\n"
        "\n"
        "## Verify your download\n"
        "\n"
        "SHA256 checksums (also attached as `SHA256SUMS`):\n"
        "\n"
        "```\n"
        f"{checksums.strip()}\n"
        "```\n"
        "\n"
        "- Linux / macOS: `sha256sum -c SHA256SUMS --ignore-missing`\n"
        f"- PowerShell: `(Get-FileHash .\\{wheel}).Hash.ToLower()` and compare with the "
        "line above.\n"
        f"- Build provenance (GitHub CLI): `gh attestation verify {wheel} --repo {repo}`\n"
    )


def main(argv: Sequence[str] | None = None) -> int:
    """Parse arguments, write the notes file, and return the process exit code."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[1])
    parser.add_argument("--version", required=True, help="release version, without a leading v")
    parser.add_argument("--changelog", type=Path, default=Path("CHANGELOG.md"))
    parser.add_argument("--checksums", type=Path, required=True, help="path to SHA256SUMS")
    parser.add_argument("--repo", required=True, help="owner/name of the repository")
    parser.add_argument("--out", type=Path, required=True, help="notes file to write")
    args = parser.parse_args(argv)

    changelog = args.changelog.read_text(encoding="utf-8")
    checksums = args.checksums.read_text(encoding="utf-8")
    try:
        section = extract_section(changelog, args.version)
    except ValueError as exc:
        # GitHub parses workflow commands from stdout, not stderr.
        print(f"::error::{exc}")
        return 1
    notes = render_notes(section, version=args.version, repo=args.repo, checksums=checksums)
    args.out.write_text(notes, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
