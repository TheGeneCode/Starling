"""
Guards the release pipeline's supply-chain properties.

``.github/workflows/release.yml`` builds and publishes the wheel users install. Each
property asserted here (SHA-pinned actions, a green-CI gate, no workflow expressions
inside ``run:`` scripts, no persisted checkout credentials, no uv cache in the publishing
job, a published checksum and provenance attestation) is easy to undo with an
innocent-looking edit, and nothing else would notice. The checks are text-based on
purpose: PyYAML is not in ``uv.lock``, and the properties are all visible as plain lines.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Final

import pytest

REPO_ROOT: Final = Path(__file__).resolve().parents[1]
_WORKFLOWS: Final = REPO_ROOT / ".github" / "workflows"
_CI: Final = _WORKFLOWS / "ci.yml"
_RELEASE: Final = _WORKFLOWS / "release.yml"
_MAINTENANCE: Final = _WORKFLOWS / "maintenance-check.yml"
_DEPENDABOT: Final = REPO_ROOT / ".github" / "dependabot.yml"

_USES: Final = re.compile(r"^\s*(?:-\s+)?uses:\s*([^\s#]+)", re.MULTILINE)
_SHA_PIN: Final = re.compile(r"@[0-9a-f]{40}$")
_RUN: Final = re.compile(r"^(\s*)(?:-\s+)?run:\s*(.*)$")
_CHECKOUT: Final = re.compile(r"uses:\s*actions/checkout@")


def _workflow_paths() -> list[Path]:
    paths = sorted(_WORKFLOWS.glob("*.yml"))
    assert paths, "no workflow files found"
    return paths


def _indent(line: str) -> int:
    return len(line) - len(line.lstrip(" "))


def _run_script_lines(text: str) -> list[str]:
    """Return every line belonging to a ``run:`` value (inline or block scalar)."""
    lines = text.splitlines()
    out: list[str] = []
    i = 0
    while i < len(lines):
        m = _RUN.match(lines[i])
        if m is None:
            i += 1
            continue
        key_indent, value = len(m.group(1)), m.group(2).strip()
        if value and value[0] not in "|>":
            out.append(value)
            i += 1
            continue
        i += 1
        while i < len(lines) and (not lines[i].strip() or _indent(lines[i]) > key_indent):
            out.append(lines[i])
            i += 1
    return out


def test_every_workflow_action_is_sha_pinned() -> None:
    """A mutable tag lets an upstream retag run new code with this repo's tokens."""
    offenders = [
        f"{path.name}: {ref}"
        for path in _workflow_paths()
        for ref in _USES.findall(path.read_text(encoding="utf-8"))
        if not ref.startswith("./") and not _SHA_PIN.search(ref)
    ]
    assert not offenders, f"actions not pinned to a 40-hex commit SHA: {offenders}"


@pytest.mark.parametrize(
    ("ref", "pinned"),
    [
        ("actions/checkout@" + "a" * 40, True),
        ("actions/checkout@v4", False),
        ("actions/checkout@main", False),
        ("actions/checkout@" + "a" * 39, False),
        ("actions/checkout@" + "a" * 41, False),
    ],
    ids=["full-sha", "tag", "branch", "short-sha", "overlong-sha"],
)
def test_sha_pin_pattern_accepts_only_full_lowercase_commit_sha(ref: str, pinned: bool) -> None:
    """Proves the pin guard's failing path fires (a loosened ``{40}`` would pass tags)."""
    (found,) = _USES.findall(f"      - uses: {ref} # comment\n")
    assert found == ref
    assert bool(_SHA_PIN.search(found)) is pinned


@pytest.mark.parametrize("workflow", _workflow_paths(), ids=lambda path: path.name)
def test_run_scripts_never_interpolate_expressions(workflow: Path) -> None:
    """
    ``${{ }}`` inside ``run:`` is textual substitution into a shell script (injection).

    Values reach scripts through ``$GITHUB_REF_NAME``-style environment variables.
    """
    lines = _run_script_lines(workflow.read_text(encoding="utf-8"))
    assert lines, f"no run: scripts extracted from {workflow.name}; the parser went stale"
    offenders = [line for line in lines if "${{" in line]
    assert not offenders, f"workflow expression inside a run: script: {offenders}"


def test_run_script_parser_flags_inline_and_block_expressions() -> None:
    text = (
        "steps:\n"
        "  - run: echo ${{ github.ref_name }}\n"
        "  - run: |\n"
        "      echo start\n"
        "      echo ${{ x }}\n"
    )
    flagged = [line for line in _run_script_lines(text) if "${{" in line]
    assert len(flagged) == 2
    assert any("github.ref_name" in line for line in flagged)
    assert any("${{ x }}" in line for line in flagged)


def test_run_script_parser_ignores_env_and_with_mappings() -> None:
    text = (
        "env:\n"
        "  TAG: ${{ github.ref_name }}\n"
        "- run: echo hi\n"
        "- uses: a/b@c\n"
        "  with:\n"
        "    x: ${{ y }}\n"
    )
    assert _run_script_lines(text) == ["echo hi"]


def test_run_script_parser_stops_at_dedent() -> None:
    text = "- run: |\n    echo a\n- name: next\n  env:\n    X: ${{ z }}\n"
    assert [line.strip() for line in _run_script_lines(text)] == ["echo a"]


@pytest.mark.parametrize("workflow", _workflow_paths(), ids=lambda path: path.name)
def test_every_checkout_disables_persisted_credentials(workflow: Path) -> None:
    """A checkout token left in .git/config is readable by every later step."""
    text = workflow.read_text(encoding="utf-8")
    checkouts = len(_CHECKOUT.findall(text))
    if workflow in {_CI, _RELEASE}:
        assert checkouts >= 1, f"{workflow.name} has no checkout; the guard went stale"
    assert checkouts == text.count("persist-credentials: false"), (
        f"{workflow.name}: every actions/checkout needs `persist-credentials: false`"
    )


def test_release_is_gated_on_ci() -> None:
    release = _RELEASE.read_text(encoding="utf-8")
    ci = _CI.read_text(encoding="utf-8")
    assert "uses: ./.github/workflows/ci.yml" in release
    assert "needs: ci" in release
    assert "workflow_call:" in ci, "ci.yml is not callable, so release.yml's gate cannot run"


def test_release_job_disables_uv_cache() -> None:
    """A cache restored from another run is input the published artifact did not build from."""
    text = _RELEASE.read_text(encoding="utf-8")
    assert "enable-cache: false" in text
    assert "enable-cache: true" not in text


def test_release_write_scopes_are_job_local() -> None:
    """Write tokens belong to the one job that needs them, never to the whole workflow."""
    text = _RELEASE.read_text(encoding="utf-8")
    assert re.search(r"^permissions:\n  contents: read$", text, re.MULTILINE)
    assert text.count("contents: write") == 1
    assert text.count("id-token: write") == 1


def test_release_publishes_checksums_attestation_and_changelog_notes() -> None:
    text = _RELEASE.read_text(encoding="utf-8")
    assert "actions/attest-build-provenance@" in text
    assert "SHA256SUMS" in text
    assert "body_path: release_notes.md" in text
    assert "scripts/release_notes.py" in text
    assert "generate_release_notes" not in text


def test_maintenance_write_scope_is_issues_only() -> None:
    """The monthly check may edit one issue; it must never push code or open pull requests."""
    text = _MAINTENANCE.read_text(encoding="utf-8")
    assert re.search(r"^permissions:\n  contents: read$", text, re.MULTILINE)
    assert text.count("issues: write") == 1
    assert "contents: write" not in text
    assert "pull-requests: write" not in text


def test_maintenance_runs_check_pins_with_locked_sync() -> None:
    text = _MAINTENANCE.read_text(encoding="utf-8")
    assert "uv sync --locked" in text
    assert "uv run --no-sync python scripts/check_pins.py" in text
    assert "fetch-depth: 0" in text, "release-due needs tags and history"
    assert "workflow_dispatch:" in text


def test_dependabot_groups_actions_and_uv() -> None:
    text = _DEPENDABOT.read_text(encoding="utf-8")
    assert 'package-ecosystem: "github-actions"' in text
    assert 'package-ecosystem: "uv"' in text
    assert text.count("groups:") == 2
