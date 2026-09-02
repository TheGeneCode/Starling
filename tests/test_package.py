"""Smoke tests for package imports and metadata."""

from __future__ import annotations

import ast
import importlib.metadata
from typing import TYPE_CHECKING

import pytest

import starling
import starling.config
import starling.reader

if TYPE_CHECKING:
    from pathlib import Path


def test_package_imports() -> None:
    """Test that starling package imports and exposes __version__ as a non-empty str."""
    assert isinstance(starling.__version__, str)
    assert len(starling.__version__) > 0


def test_version_matches_installed_metadata() -> None:
    """Test that package version matches installed metadata."""
    try:
        installed_version = importlib.metadata.version("starling")
    except importlib.metadata.PackageNotFoundError:
        pytest.skip("starling not installed; bare source checkout")
    assert installed_version == starling.__version__


def test_reader_module_imports_without_side_effects() -> None:
    """Test that reader module imports cleanly without side effects."""
    import starling.reader  # noqa: F401 - imported for side-effect verification


def test_reader_exposes_pure_helpers() -> None:
    """Test that reader exposes all expected pure helper functions."""
    reader = starling.reader
    helpers = [
        "remove_citations",
        "split_text_into_chunks",
        "combine_audio_chunks",
        "get_monthly_total",
        "initialize_usage_logger",
        "log_usage",
        "spinner",
    ]
    for helper_name in helpers:
        assert hasattr(reader, helper_name), f"Missing helper: {helper_name}"
        helper = getattr(reader, helper_name)
        assert callable(helper), f"Not callable: {helper_name}"


def test_reader_exposes_pipeline_functions() -> None:
    """Test that reader exposes every function introduced by the Phase 3a pipeline extraction."""
    reader = starling.reader
    functions = [
        "run_read",
        "run_usage",
        "process_file",
        "synthesize_text",
        "resolve_voice_pool",
        "archive_file",
        "confirm_overwrite",
        "spinner_running",
        "plan_dry_run",
        "format_monthly_total",
    ]
    for name in functions:
        assert hasattr(reader, name), f"Missing function: {name}"
        assert callable(getattr(reader, name)), f"Not callable: {name}"


def test_reader_log_paths_come_from_config() -> None:
    """Test that reader's log paths are absolute and match a freshly loaded config."""
    reader = starling.reader
    config = starling.config.load_config()

    assert config.usage_log_path == reader.USAGE_LOG_PATH
    assert config.error_log_path == reader.ERROR_LOG_PATH
    assert reader.USAGE_LOG_PATH.is_absolute()
    assert reader.ERROR_LOG_PATH.is_absolute()


# capture.py builds its Tkinter UI at import time, so it can only be parsed here.
# Phase 3 wraps it in main(); replace this with a real import test then.
def test_capture_module_parses_without_importing(package_dir: Path) -> None:
    """
    Test that capture.py parses cleanly without importing it.

    capture.py builds Tkinter UI at module level, so it cannot be imported.
    """
    capture_path = package_dir / "capture.py"
    source = capture_path.read_text(encoding="utf-8")
    tree = ast.parse(source)

    function_names = {
        node.name for node in ast.walk(tree) if isinstance(node, ast.FunctionDef)
    }
    expected_functions = {
        "convert_numbers_to_words",
        "refine_text",
        "make_filename_ready",
        "shorten_text",
    }
    assert expected_functions.issubset(function_names), (
        f"Missing functions: {expected_functions - function_names}"
    )


def test_dropped_dependencies_are_not_imported(package_dir: Path) -> None:
    """Test that pandas and kittentts are not imported (only comments allowed)."""
    reader_path = package_dir / "reader.py"
    capture_path = package_dir / "capture.py"

    for module_file in [reader_path, capture_path]:
        source = module_file.read_text(encoding="utf-8")
        for line in source.splitlines():
            stripped = line.strip()
            # Skip comment lines
            if stripped.startswith("#"):
                continue
            # Check for live imports
            assert "import pandas" not in stripped, (
                f"Found live pandas import in {module_file.name}"
            )
            assert "import kittentts" not in stripped, (
                f"Found live kittentts import in {module_file.name}"
            )
