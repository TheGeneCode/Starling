"""Smoke tests for genekit.logging functionality."""

from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler
from typing import TYPE_CHECKING

import pytest
from genekit.logging import configure_logging, dedicated_file_logger, get_logger

from starling import reader

if TYPE_CHECKING:
    from pathlib import Path

    from starling.config import StarlingConfig


def test_dedicated_file_logger_writes_to_given_path(tmp_path: Path, isolated_logging: None) -> None:
    """Test that dedicated_file_logger writes messages to the specified file."""
    log_path = tmp_path / "tts_usage.log"
    logger = dedicated_file_logger(
        "starling_test_usage_write",
        log_path,
        fmt="%(asctime)s | %(message)s",
    )
    logger.info("sample.txt | characters: 1,234")

    assert log_path.exists()
    content = log_path.read_text(encoding="utf-8")
    assert "characters: 1,234" in content


def test_dedicated_file_logger_creates_parent_dirs(tmp_path: Path, isolated_logging: None) -> None:
    """Test that dedicated_file_logger creates parent directories."""
    nested_path = tmp_path / "nested" / "deeper" / "usage.log"
    logger = dedicated_file_logger(
        "starling_test_usage_nested",
        nested_path,
    )
    logger.info("test message")

    assert nested_path.exists()
    assert nested_path.parent.exists()
    content = nested_path.read_text(encoding="utf-8")
    assert "test message" in content


def test_dedicated_file_logger_does_not_propagate_to_root(
    tmp_path: Path, isolated_logging: None
) -> None:
    """Test that dedicated logger does not propagate to root logger."""
    configure_logging(
        "INFO",
        log_file=tmp_path / "root.log",
        console="none",
    )
    logger = dedicated_file_logger(
        "starling_test_usage_isolation",
        tmp_path / "usage.log",
    )
    logger.info("isolated message")

    usage_log = tmp_path / "usage.log"
    root_log = tmp_path / "root.log"

    assert usage_log.exists()
    assert "isolated message" in usage_log.read_text(encoding="utf-8")
    assert "isolated message" not in root_log.read_text(encoding="utf-8")


def test_dedicated_file_logger_reinit_replaces_handler(
    tmp_path: Path, isolated_logging: None
) -> None:
    """Test that reinitializing dedicated_file_logger replaces the handler."""
    path1 = tmp_path / "first.log"
    path2 = tmp_path / "second.log"

    logger = dedicated_file_logger("starling_test_usage_reinit", path1)
    logger = dedicated_file_logger("starling_test_usage_reinit", path2)
    logger.info("message")

    assert len(logger.handlers) == 1
    assert path2.exists()
    assert "message" in path2.read_text(encoding="utf-8")
    assert not path1.exists() or "message" not in path1.read_text(encoding="utf-8")


def test_configure_logging_writes_error_log(tmp_path: Path, isolated_logging: None) -> None:
    """Test that configure_logging writes ERROR level messages to log file."""
    configure_logging(
        "ERROR",
        log_file=tmp_path / "logfile.txt",
        console="none",
    )
    logger = get_logger("starling.test")
    logger.error("boom")

    log_file = tmp_path / "logfile.txt"
    assert log_file.exists()
    assert "boom" in log_file.read_text(encoding="utf-8")


def test_configure_logging_below_threshold_is_not_written(
    tmp_path: Path, isolated_logging: None
) -> None:
    """Test that messages below threshold are not written."""
    configure_logging(
        "ERROR",
        log_file=tmp_path / "logfile.txt",
        console="none",
    )
    logger = get_logger("starling.test")
    logger.info("quiet")

    log_file = tmp_path / "logfile.txt"
    content = log_file.read_text(encoding="utf-8")
    assert "quiet" not in content


def test_configure_logging_rejects_silent_config(isolated_logging: None) -> None:
    """Test that configure_logging raises ValueError for silent config."""
    with pytest.raises(ValueError, match="requires log_file"):
        configure_logging("ERROR", console="none", log_file=None)


class _StopRunError(Exception):
    """Raised by a spy to halt run_read right after configure_logging."""


def test_run_read_passes_rotation_constants_to_configure_logging(
    tmp_config: StarlingConfig, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Test that the read command wires the rotation constants into configure_logging."""
    (tmp_config.input_dir / "article.txt").write_text("Hello.", encoding="utf-8")
    captured: dict[str, object] = {}

    def spy(*_args: object, **kwargs: object) -> None:
        captured.update(kwargs)
        raise _StopRunError

    monkeypatch.setattr(reader, "require_credentials", lambda _config: None)
    monkeypatch.setattr(reader, "configure_logging", spy)

    with pytest.raises(_StopRunError):
        reader.run_read(config=tmp_config)

    assert captured["rotate_bytes"] == reader.ERROR_LOG_MAX_BYTES
    assert captured["backup_count"] == reader.ERROR_LOG_BACKUPS


def test_configure_logging_with_reader_constants_rolls_over_to_one_backup(
    tmp_path: Path, isolated_logging: None
) -> None:
    """Test that the root handler rotates at the cap and keeps exactly log + log.1."""
    log_path = tmp_path / "errors.log"
    configure_logging(
        "ERROR",
        log_file=log_path,
        console="none",
        rotate_bytes=reader.ERROR_LOG_MAX_BYTES,
        backup_count=reader.ERROR_LOG_BACKUPS,
    )
    handler = next(h for h in logging.getLogger().handlers if isinstance(h, RotatingFileHandler))
    assert handler.maxBytes == reader.ERROR_LOG_MAX_BYTES
    assert handler.backupCount == reader.ERROR_LOG_BACKUPS

    logger = get_logger("starling.test.rotation")
    chunk = "x" * (reader.ERROR_LOG_MAX_BYTES * 6 // 10)
    for marker in ("first", "second", "third"):
        logger.error("%s %s", marker, chunk)
    handler.flush()

    assert sorted(p.name for p in tmp_path.iterdir()) == ["errors.log", "errors.log.1"]
    assert log_path.stat().st_size <= reader.ERROR_LOG_MAX_BYTES
    assert "third" in log_path.read_text(encoding="utf-8")
