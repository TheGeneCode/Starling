"""Starling's command-line interface."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import TYPE_CHECKING, Final

from starling import __version__
from starling.reader import ReadOptions, run_read, run_usage

if TYPE_CHECKING:
    from collections.abc import Sequence

SUBCOMMANDS: Final[tuple[str, ...]] = ("read", "capture", "voices", "usage")

# Flags argparse handles at the top level. Everything else that is not a subcommand
# belongs to the implicit `read`, so `starling --dry-run` == `starling read --dry-run`.
TOP_LEVEL_FLAGS: Final[frozenset[str]] = frozenset({"-h", "--help", "--version"})

EPILOG: Final = """\
examples:
  starling                      synthesize every .txt in the input directory
  starling read --dry-run       report what would be billed, without calling Google
  starling read --yes           overwrite existing .wav files without prompting
  starling capture              open the clipboard-capture window
  starling voices en-GB         list the voices Google offers for a language
  starling usage                this month's character total
"""


def _handle_read(args: argparse.Namespace) -> int:
    return run_read(
        options=ReadOptions(
            assume_yes=args.assume_yes,
            dry_run=args.dry_run,
            input_dir=args.input_dir,
        ),
    )


def _handle_capture(args: argparse.Namespace) -> int:
    # Imported here so `starling read` never loads tkinter.
    from starling.capture import run_capture  # noqa: PLC0415

    return run_capture()


def _handle_voices(args: argparse.Namespace) -> int:
    from starling.voices import run_voices  # noqa: PLC0415

    return run_voices(args.language_code)


def _handle_usage(args: argparse.Namespace) -> int:
    return run_usage()


def build_parser() -> argparse.ArgumentParser:
    """Build the `starling` parser. Every subparser sets a `handler` default."""
    parser = argparse.ArgumentParser(
        prog="starling",
        description=(
            "Read saved articles aloud — turn article text into narrated audio "
            "with Google Cloud Text-to-Speech."
        ),
        epilog=EPILOG,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"starling {__version__}",
    )
    subparsers = parser.add_subparsers(
        dest="command",
        metavar="{read,capture,voices,usage}",
    )

    read_parser = subparsers.add_parser(
        "read",
        help="Synthesize every .txt in the input directory (the default command).",
    )
    read_parser.add_argument(
        "--input-dir",
        type=Path,
        default=None,
        metavar="PATH",
        help="Directory to read .txt files from. Defaults to STARLING_INPUT_DIR.",
    )
    read_parser.add_argument(
        "-y",
        "--yes",
        "--overwrite",
        dest="assume_yes",
        action="store_true",
        help="Overwrite an existing .wav without asking. Makes the tool scriptable.",
    )
    read_parser.add_argument(
        "--dry-run",
        action="store_true",
        help=(
            "Report what would be synthesized and how many characters it would bill. "
            "Makes no API calls and needs no Google credentials."
        ),
    )
    read_parser.set_defaults(handler=_handle_read)

    capture_parser = subparsers.add_parser(
        "capture",
        help="Open the clipboard-capture window to save articles into the input directory.",
    )
    capture_parser.set_defaults(handler=_handle_capture)

    voices_parser = subparsers.add_parser(
        "voices",
        help="List the Google voices available for a language code.",
    )
    voices_parser.add_argument(
        "language_code",
        nargs="?",
        default=None,
        metavar="LANGUAGE_CODE",
        help="A BCP-47 code such as en-US. Defaults to STARLING_LANGUAGE_CODE.",
    )
    voices_parser.set_defaults(handler=_handle_voices)

    usage_parser = subparsers.add_parser(
        "usage",
        help="Print this month's character total from the usage log.",
    )
    usage_parser.set_defaults(handler=_handle_usage)

    return parser


def apply_default_command(argv: Sequence[str]) -> list[str]:
    """
    Insert the implicit `read` subcommand.

    `starling` and `starling --dry-run` both mean `starling read [...]`. A leading
    top-level flag (-h/--help/--version) is left alone so it reaches the root parser.
    """
    args = list(argv)
    if not args:
        return ["read"]
    if args[0] in SUBCOMMANDS or args[0] in TOP_LEVEL_FLAGS:
        return args
    return ["read", *args]


def main(argv: Sequence[str] | None = None) -> int:
    """Entry point for the `starling` console script. Returns a process exit code."""
    raw = sys.argv[1:] if argv is None else list(argv)
    parser = build_parser()
    args = parser.parse_args(apply_default_command(raw))
    try:
        return args.handler(args)
    except KeyboardInterrupt:
        print()
        print("Interrupted.")
        return 130


if __name__ == "__main__":
    sys.exit(main())
