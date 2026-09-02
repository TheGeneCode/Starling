"""Tests for starling.cli: argument parsing, dispatch, and the console entry point."""

from __future__ import annotations

import importlib.metadata
import os
import subprocess
import sys
import tomllib
from pathlib import Path
from typing import Any

import pytest

import starling
import starling.cli
import starling.update_check
from starling.cli import apply_default_command, build_parser, main
from starling.reader import ReadOptions

REPO_ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture(autouse=True)
def _no_update_check(monkeypatch: pytest.MonkeyPatch) -> None:
    """
    Stop every test in this file from touching the real update-check state or network.

    `main()` calls `maybe_notify_update()` unconditionally after `parse_args`, so without
    this every dispatch test below would write to the developer's real AppData state file
    and start a real background thread hitting GitHub. Tests that specifically exercise
    the update-check wiring re-patch this themselves, which simply overrides it further.
    """
    monkeypatch.setattr(
        starling.update_check, "maybe_notify_update", lambda *_args, **_kwargs: None,
    )


# ---------------------------------------------------------------------------
# apply_default_command
# ---------------------------------------------------------------------------


def test_apply_default_command_empty_argv() -> None:
    assert apply_default_command([]) == ["read"]


@pytest.mark.parametrize(
    "argv",
    [
        pytest.param(["--dry-run"], id="dry_run"),
        pytest.param(["-y"], id="short_yes"),
        pytest.param(["--input-dir", "x"], id="input_dir"),
    ],
)
def test_apply_default_command_prepends_read_for_bare_flags(argv: list[str]) -> None:
    assert apply_default_command(argv) == ["read", *argv]


@pytest.mark.parametrize(
    "argv",
    [
        pytest.param(["read"], id="read"),
        pytest.param(["capture"], id="capture"),
        pytest.param(["voices", "en-GB"], id="voices"),
        pytest.param(["usage"], id="usage"),
    ],
)
def test_apply_default_command_leaves_subcommands_alone(argv: list[str]) -> None:
    assert apply_default_command(argv) == argv


@pytest.mark.parametrize(
    "argv",
    [
        pytest.param(["--help"], id="help"),
        pytest.param(["-h"], id="short_help"),
        pytest.param(["--version"], id="version"),
    ],
)
def test_apply_default_command_leaves_top_level_flags_alone(argv: list[str]) -> None:
    assert apply_default_command(argv) == argv


def test_apply_default_command_is_case_sensitive_about_subcommand_names() -> None:
    """`READ` is not in SUBCOMMANDS, so it is treated as a bare value, not the subcommand."""
    assert apply_default_command(["READ"]) == ["read", "READ"]


def test_apply_default_command_accepts_a_tuple_not_just_a_list() -> None:
    """Argv is typed as Sequence[str]; a tuple must work the same as a list."""
    assert apply_default_command(("--dry-run",)) == ["read", "--dry-run"]


def test_apply_default_command_does_not_mutate_its_input() -> None:
    original = ["--dry-run"]
    apply_default_command(original)
    assert original == ["--dry-run"]


# ---------------------------------------------------------------------------
# build_parser
# ---------------------------------------------------------------------------


def test_parser_read_defaults() -> None:
    args = build_parser().parse_args(["read"])
    assert args.assume_yes is False
    assert args.dry_run is False
    assert args.input_dir is None


@pytest.mark.parametrize(
    "argv",
    [
        pytest.param(["read", "-y"], id="short"),
        pytest.param(["read", "--yes"], id="long"),
        pytest.param(["read", "--overwrite"], id="overwrite_alias"),
    ],
)
def test_parser_yes_aliases_all_set_assume_yes(argv: list[str]) -> None:
    args = build_parser().parse_args(argv)
    assert args.assume_yes is True


def test_parser_dry_run_flag() -> None:
    args = build_parser().parse_args(["read", "--dry-run"])
    assert args.dry_run is True


def test_parser_input_dir_is_a_path() -> None:
    args = build_parser().parse_args(["read", "--input-dir", "some/dir"])
    assert args.input_dir == Path("some/dir")


def test_parser_voices_language_code_is_optional() -> None:
    assert build_parser().parse_args(["voices"]).language_code is None
    assert build_parser().parse_args(["voices", "en-GB"]).language_code == "en-GB"


@pytest.mark.parametrize(
    "argv",
    [
        pytest.param(["read"], id="read"),
        pytest.param(["capture"], id="capture"),
        pytest.param(["voices"], id="voices"),
        pytest.param(["usage"], id="usage"),
    ],
)
def test_parser_every_subcommand_sets_a_handler(argv: list[str]) -> None:
    namespace = build_parser().parse_args(argv)
    assert hasattr(namespace, "handler")
    assert callable(namespace.handler)


def test_build_parser_returns_an_independent_parser_each_call() -> None:
    """Two build_parser() calls must not share subparser state across each other."""
    first_namespace = build_parser().parse_args(["read"])
    second_namespace = build_parser().parse_args(["voices"])

    assert not hasattr(first_namespace, "language_code")
    assert not hasattr(second_namespace, "assume_yes")


@pytest.mark.parametrize(
    "argv",
    [
        pytest.param(["voices", "-x"], id="option_like_positional_rejected"),
        pytest.param(["voices", "en-GB", "extra"], id="second_positional_rejected"),
    ],
)
def test_parser_voices_rejects_extra_or_option_like_arguments(
    argv: list[str],
) -> None:
    with pytest.raises(SystemExit) as exc_info:
        build_parser().parse_args(argv)
    assert exc_info.value.code == 2


def test_parser_read_has_no_positional_argument() -> None:
    """`read` only takes flags; a bare positional is an unrecognized argument, not a filename."""
    with pytest.raises(SystemExit) as exc_info:
        build_parser().parse_args(["read", "somefile.txt"])
    assert exc_info.value.code == 2


@pytest.mark.parametrize("subcommand", ["read", "capture", "voices", "usage"])
def test_parser_version_flag_is_root_only_not_inherited_by_subparsers(
    subcommand: str,
) -> None:
    """--version is a root-parser flag; placed after a subcommand it is unrecognized."""
    with pytest.raises(SystemExit) as exc_info:
        build_parser().parse_args([subcommand, "--version"])
    assert exc_info.value.code == 2


# ---------------------------------------------------------------------------
# main() dispatch
# ---------------------------------------------------------------------------


class _Recorder:
    """Records every call and returns a fixed value, standing in for a handler."""

    def __init__(self, return_value: int = 0) -> None:
        self.calls: list[tuple[tuple[Any, ...], dict[str, Any]]] = []
        self.return_value = return_value

    def __call__(self, *args: Any, **kwargs: Any) -> int:
        self.calls.append((args, kwargs))
        return self.return_value


def test_main_bare_invocation_dispatches_to_read(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    recorder = _Recorder(return_value=42)
    monkeypatch.setattr(starling.cli, "run_read", recorder)

    result = main([])

    assert len(recorder.calls) == 1
    assert recorder.calls[0][1] == {"options": ReadOptions()}
    assert result == 42


def test_main_read_passes_options_through(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    recorder = _Recorder()
    monkeypatch.setattr(starling.cli, "run_read", recorder)

    main(["read", "--yes", "--dry-run", "--input-dir", str(tmp_path)])

    assert recorder.calls[0][1] == {
        "options": ReadOptions(assume_yes=True, dry_run=True, input_dir=tmp_path),
    }


def test_main_capture_dispatches(monkeypatch: pytest.MonkeyPatch) -> None:
    recorder = _Recorder(return_value=7)
    monkeypatch.setattr("starling.capture.run_capture", recorder)

    assert main(["capture"]) == 7
    assert len(recorder.calls) == 1


def test_main_voices_dispatches_with_language_code(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    recorder = _Recorder()
    monkeypatch.setattr("starling.voices.run_voices", recorder)

    main(["voices", "en-GB"])

    assert recorder.calls == [(("en-GB",), {})]


def test_main_usage_dispatches(monkeypatch: pytest.MonkeyPatch) -> None:
    recorder = _Recorder(return_value=3)
    monkeypatch.setattr(starling.cli, "run_usage", recorder)

    assert main(["usage"]) == 3
    assert len(recorder.calls) == 1


def test_main_propagates_nonzero_exit_code(monkeypatch: pytest.MonkeyPatch) -> None:
    recorder = _Recorder(return_value=1)
    monkeypatch.setattr(starling.cli, "run_read", recorder)

    assert main([]) == 1


def test_main_keyboard_interrupt_returns_130(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    def _raise(**_kwargs: Any) -> int:
        raise KeyboardInterrupt

    monkeypatch.setattr(starling.cli, "run_read", _raise)

    result = main([])

    assert result == 130
    assert "Interrupted." in capsys.readouterr().out


def test_main_unknown_subcommand_exits_two() -> None:
    with pytest.raises(SystemExit) as exc_info:
        main(["frobnicate"])
    assert exc_info.value.code == 2


def test_main_none_argv_reads_sys_argv(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`main()` with no argv falls back to sys.argv[1:], not an empty list."""
    recorder = _Recorder()
    monkeypatch.setattr(starling.cli, "run_read", recorder)
    monkeypatch.setattr(sys, "argv", ["starling", "--dry-run"])

    main()

    assert recorder.calls[0][1] == {"options": ReadOptions(dry_run=True)}


def test_main_keyboard_interrupt_during_parsing_is_not_caught(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """
    Document the documented boundary: only args.handler(args) is wrapped in try/except.

    A KeyboardInterrupt raised by parser.parse_args() itself (e.g. Ctrl+C while argparse
    is still working) must propagate uncaught, unlike one raised from inside a handler.
    """

    def _raise(_self: object, _argv: object = None) -> None:
        raise KeyboardInterrupt

    monkeypatch.setattr(
        starling.cli.argparse.ArgumentParser,
        "parse_args",
        _raise,
    )

    with pytest.raises(KeyboardInterrupt):
        main(["read"])


def test_main_unknown_flag_exits_two() -> None:
    with pytest.raises(SystemExit) as exc_info:
        main(["--nope"])
    assert exc_info.value.code == 2


def test_main_version_prints_package_version(
    capsys: pytest.CaptureFixture[str],
) -> None:
    with pytest.raises(SystemExit) as exc_info:
        main(["--version"])
    assert exc_info.value.code == 0
    assert capsys.readouterr().out.strip() == f"starling {starling.__version__}"


def test_main_help_exits_zero_and_lists_all_subcommands(
    capsys: pytest.CaptureFixture[str],
) -> None:
    with pytest.raises(SystemExit) as exc_info:
        main(["--help"])
    assert exc_info.value.code == 0
    out = capsys.readouterr().out
    for subcommand in ("read", "capture", "voices", "usage"):
        assert subcommand in out


# ---------------------------------------------------------------------------
# Process-boundary behavior
# ---------------------------------------------------------------------------


def test_read_does_not_import_tkinter() -> None:
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "import starling.cli, sys; sys.exit('tkinter' in sys.modules)",
        ],
        check=False,
        timeout=30,
    )
    assert result.returncode == 0


def test_console_script_is_declared_in_pyproject() -> None:
    data = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    assert data["project"]["scripts"]["starling"] == "starling.cli:main"


def test_console_script_entry_point_is_installed() -> None:
    entry_points = importlib.metadata.entry_points(group="console_scripts")
    matches = [ep for ep in entry_points if ep.name == "starling"]
    if not matches:
        pytest.skip("starling not installed; bare source checkout")
    assert matches[0].value == "starling.cli:main"


def test_python_dash_m_starling_help_works() -> None:
    result = subprocess.run(
        [sys.executable, "-m", "starling", "--help"],
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0
    assert "usage: starling" in result.stdout


def test_python_dash_m_starling_read_on_empty_dir(tmp_path: Path) -> None:
    env = {
        **{k: v for k, v in os.environ.items() if not k.startswith("STARLING_")},
        "STARLING_HOME": str(tmp_path),
        "STARLING_INPUT_DIR": str(tmp_path),
        # This is a real subprocess, so the in-process _no_update_check autouse fixture
        # can't reach it -- opt out for real, or this test hits GitHub and writes to the
        # developer's real AppData state file on every run.
        "STARLING_UPDATE_CHECK": "false",
    }
    result = subprocess.run(
        [sys.executable, "-m", "starling", "read"],
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
        env=env,
    )
    assert result.returncode == 0
    assert result.stdout.strip() == "No text files found."


# ---------------------------------------------------------------------------
# Update-check wiring
# ---------------------------------------------------------------------------


def test_main_checks_for_updates_before_dispatch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    recorder = _Recorder()
    monkeypatch.setattr(starling.update_check, "maybe_notify_update", recorder)
    monkeypatch.setattr(starling.cli, "run_read", lambda **_kwargs: 0)

    main(["read", "--dry-run"])

    assert len(recorder.calls) == 1


def test_version_flag_does_not_check_for_updates(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    recorder = _Recorder()
    monkeypatch.setattr(starling.update_check, "maybe_notify_update", recorder)

    with pytest.raises(SystemExit):
        main(["--version"])

    assert recorder.calls == []


def test_pyproject_declares_requests() -> None:
    data = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    dependencies = data["project"]["dependencies"]
    assert any(dep.startswith("requests") for dep in dependencies)
