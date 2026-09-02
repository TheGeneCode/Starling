"""Shared fixtures for the Starling test suite."""

from __future__ import annotations

import logging
import os
from pathlib import Path
from types import SimpleNamespace
from typing import TYPE_CHECKING
from unittest.mock import MagicMock

import pytest

import starling
from starling.config import StarlingConfig, VoiceMode, ensure_directories

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
def tk_root() -> Iterator[object]:
    """
    A real Tk root, or a skip on a machine with no display.

    tkinter raises TclError ("no display name and no $DISPLAY environment variable")
    on a headless runner. Skipping keeps the GUI smoke tests honest on Windows and
    silent everywhere else, rather than flaky in both places.
    """  # noqa: D401
    tk = pytest.importorskip("tkinter")

    try:
        root = tk.Tk()
    except tk.TclError as exc:  # pragma: no cover - depends on the runner
        pytest.skip(f"no display available for Tk: {exc}")
    root.withdraw()
    try:
        yield root
    finally:
        root.destroy()


@pytest.fixture
def tmp_config(tmp_path: Path) -> StarlingConfig:
    """A StarlingConfig whose every path lives under tmp_path, with dirs created."""  # noqa: D401
    config = StarlingConfig(
        home_dir=tmp_path,
        input_dir=tmp_path / "input",
        output_dir=tmp_path / "output",
        archive_dir=tmp_path / "archive",
        credentials_path=None,
        language_code="en-US",
        voice_mode=VoiceMode.FIXED,
        voice_name="en-US-Chirp3-HD-Aoede",
        voice_pool=("en-US-Chirp3-HD-Aoede",),
        usage_log_path=tmp_path / "logs" / "usage.log",
        error_log_path=tmp_path / "logs" / "errors.log",
    )
    ensure_directories(config)
    return config


@pytest.fixture
def clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """
    Remove every STARLING_* and Google credential variable for the duration of a test.

    The developer's own shell and .env both define some of these; without this fixture a
    default-resolution test would pass or fail depending on whose machine it ran on.
    """
    for key in list(os.environ):
        if key.startswith("STARLING_"):
            monkeypatch.delenv(key, raising=False)
    monkeypatch.delenv("GOOGLE_APPLICATION_CREDENTIALS", raising=False)


@pytest.fixture
def fake_home(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    """Point Path.home() at a temporary directory so default paths are assertable."""
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setattr(Path, "home", classmethod(lambda _cls: home))
    return home


@pytest.fixture
def fake_credentials(tmp_path: Path) -> Path:
    """Write a file that stands in for a service-account JSON key. Never a real key."""
    key = tmp_path / "service-account.json"
    key.write_text('{"type": "service_account"}', encoding="utf-8")
    return key


@pytest.fixture
def voice_catalog() -> list[SimpleNamespace]:
    """
    Stand-in for Google's ListVoices payload, shaped like the real proto messages.

    Deliberately mixes families and casings so family parsing and case-insensitive
    matching are exercised by the same fixture.
    """
    from google.cloud import texttospeech

    female = texttospeech.SsmlVoiceGender.FEMALE
    male = texttospeech.SsmlVoiceGender.MALE
    unspecified = texttospeech.SsmlVoiceGender.SSML_VOICE_GENDER_UNSPECIFIED
    return [
        SimpleNamespace(name="en-US-Chirp3-HD-Aoede", ssml_gender=female, language_codes=["en-US"]),
        SimpleNamespace(name="en-US-Chirp3-HD-Puck", ssml_gender=male, language_codes=["en-US"]),
        SimpleNamespace(name="en-US-Neural2-C", ssml_gender=female, language_codes=["en-US"]),
        SimpleNamespace(name="en-US-Standard-A", ssml_gender=unspecified, language_codes=["en-US"]),
    ]


@pytest.fixture
def fake_tts_client(voice_catalog: list[SimpleNamespace]) -> MagicMock:
    """Return a TextToSpeechClient mock whose list_voices returns the fixture catalog."""
    client = MagicMock()
    client.list_voices.return_value = SimpleNamespace(voices=voice_catalog)
    return client


@pytest.fixture
def state_file(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    """Redirect the update-check state file into tmp_path, never the real user data dir."""
    import starling.update_check as uc

    path = tmp_path / "state" / "update-check.json"
    monkeypatch.setattr(uc, "state_path", lambda: path)
    return path


@pytest.fixture
def no_network(monkeypatch: pytest.MonkeyPatch) -> None:
    """
    Make any unmocked HTTP call fail loudly instead of reaching the internet.

    Tests that need a response patch `requests.get` themselves, which overrides this.
    """
    import requests

    def _forbidden(*args: object, **kwargs: object) -> None:
        msg = "a test attempted a real network call"
        raise AssertionError(msg)

    monkeypatch.setattr(requests, "get", _forbidden)


@pytest.fixture
def captured_threads(monkeypatch: pytest.MonkeyPatch) -> list[MagicMock]:
    """
    Replace threading.Thread inside update_check with a recorder.

    Returns the list of constructed thread mocks so a test can assert on target/daemon and
    invoke the target synchronously. Keeps the suite deterministic and leak-free -- a real
    daemon thread outliving a test is exactly the flake this avoids.
    """
    import starling.update_check as uc

    created: list[MagicMock] = []

    def _factory(**kwargs: object) -> MagicMock:
        thread = MagicMock()
        thread.kwargs = kwargs
        created.append(thread)
        return thread

    monkeypatch.setattr(uc.threading, "Thread", _factory)
    return created
