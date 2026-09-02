"""Shared fixtures for the Starling test suite."""

from __future__ import annotations

import ast
import logging
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

import starling

if TYPE_CHECKING:
    from collections.abc import Iterator


@pytest.fixture
def isolated_logging() -> Iterator[None]:
    """
    Restore root and named logger state after a test touches genekit.logging.

    ``configure_logging`` calls ``logging.basicConfig(force=True)`` and
    ``dedicated_file_logger`` mutates a process-global named logger, so a test that
    configures logging otherwise leaks handlers into every test that follows. This fixture
    snapshots the root handlers plus the set of existing logger names, then tears down
    anything new. Closing the handlers also releases the file locks Windows would
    otherwise hold on ``tmp_path``.
    """
    root = logging.getLogger()
    saved_handlers = root.handlers[:]
    saved_level = root.level
    saved_names = set(logging.root.manager.loggerDict)

    yield

    for handler in root.handlers[:]:
        if handler not in saved_handlers:
            root.removeHandler(handler)
            handler.close()
    root.handlers[:] = saved_handlers
    root.setLevel(saved_level)

    for name in set(logging.root.manager.loggerDict) - saved_names:
        logger = logging.getLogger(name)
        for handler in logger.handlers[:]:
            logger.removeHandler(handler)
            handler.close()


@pytest.fixture
def package_dir() -> Path:
    """Return the directory the installed ``starling`` package resolves to."""
    return Path(starling.__file__).parent


@pytest.fixture
def capture_helpers(package_dir: Path) -> dict[str, object]:
    """
    Exec capture.py's pure text-processing helpers in isolation, without importing it.

    capture.py builds a Tkinter GUI and calls ``root.mainloop()`` at module level, so
    it must never be imported directly (see ``test_capture_module_parses_without_importing``
    in ``test_package.py``). This fixture parses the source with ``ast``, keeps only the
    top-level import statements and the four pure helper function definitions
    (``make_filename_ready``, ``convert_numbers_to_words``, ``refine_text``,
    ``shorten_text``), and execs that reduced module into a fresh namespace. This gives
    real behavioral coverage of the text-processing logic without ever constructing a
    GUI window or touching the clipboard.
    """
    capture_path = package_dir / "capture.py"
    source = capture_path.read_text(encoding="utf-8")
    tree = ast.parse(source)

    wanted_functions = {
        "make_filename_ready",
        "convert_numbers_to_words",
        "refine_text",
        "shorten_text",
    }
    nodes = [
        node
        for node in tree.body
        if isinstance(node, (ast.Import, ast.ImportFrom))
        or (isinstance(node, ast.FunctionDef) and node.name in wanted_functions)
    ]
    reduced_module = ast.Module(body=nodes, type_ignores=[])
    ast.fix_missing_locations(reduced_module)

    namespace: dict[str, object] = {}
    exec(  # noqa: S102 - controlled exec of vetted, pre-parsed source; not user input
        compile(reduced_module, filename=str(capture_path), mode="exec"),
        namespace,
    )
    return namespace
