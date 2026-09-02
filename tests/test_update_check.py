"""Tests for starling.update_check: version comparison, state caching, and the throttle."""

from __future__ import annotations

import io
import threading
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, Mock

import pytest
import requests

import starling.update_check as uc


def _response(status_code: int = 200, json_body: Any = None) -> Mock:
    """Build a fake requests.Response with the given status code and JSON payload."""
    response = Mock()
    response.status_code = status_code
    response.json.return_value = json_body
    return response

# ---------------------------------------------------------------------------
# normalize_version
# ---------------------------------------------------------------------------


class TestNormalizeVersion:
    @pytest.mark.parametrize(
        ("version", "expected"),
        [
            pytest.param("v0.2.0", (0, 2, 0), id="v_prefix"),
            pytest.param("0.2.0", (0, 2, 0), id="no_prefix"),
            pytest.param("v1.10.3", (1, 10, 3), id="multi_digit_component"),
        ],
    )
    def test_normalize_version_parses_tags(
        self, version: str, expected: tuple[int, ...],
    ) -> None:
        assert uc.normalize_version(version) == expected

    @pytest.mark.parametrize(
        "version",
        [
            pytest.param("", id="empty_string"),
            pytest.param(None, id="none"),
            pytest.param("dev", id="dev"),
            pytest.param("abc", id="no_digits"),
        ],
    )
    def test_normalize_version_empty_for_unparseable(self, version: str | None) -> None:
        assert uc.normalize_version(version) == ()


# ---------------------------------------------------------------------------
# is_update_available
# ---------------------------------------------------------------------------


class TestIsUpdateAvailable:
    def test_is_update_available_newer_release(self) -> None:
        assert uc.is_update_available("0.1.0", "v0.2.0") is True

    def test_is_update_available_equal_version(self) -> None:
        assert uc.is_update_available("0.1.0", "v0.1.0") is False

    def test_is_update_available_older_release(self) -> None:
        """Never prompts a downgrade."""
        assert uc.is_update_available("0.2.0", "v0.1.0") is False

    @pytest.mark.parametrize(
        "latest",
        [
            pytest.param(None, id="none"),
            pytest.param("", id="empty"),
            pytest.param("vNext", id="unparseable"),
        ],
    )
    def test_is_update_available_malformed_latest(self, latest: str | None) -> None:
        assert uc.is_update_available("0.1.0", latest) is False

    def test_is_update_available_dev_current(self) -> None:
        assert uc.is_update_available("dev", "v9.9.9") is False

    def test_is_update_available_shorter_current_tuple(self) -> None:
        """
        Documents a known limitation inherited from MeadowLark: (0,1) < (0,1,0).

        Harmless because Starling's own tags are always three-part; this test pins the
        behavior so a future change to normalize_version is deliberate, not accidental.
        """
        assert uc.is_update_available("0.1", "v0.1.0") is True


# ---------------------------------------------------------------------------
# state_dir
# ---------------------------------------------------------------------------


class TestStateDir:
    def test_state_dir_windows_uses_localappdata(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
    ) -> None:
        monkeypatch.setattr(uc.sys, "platform", "win32")
        monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))

        result = uc.state_dir()

        assert result.name == "starling"
        assert tmp_path in result.parents

    def test_state_dir_darwin_uses_application_support(
        self, monkeypatch: pytest.MonkeyPatch, fake_home: Path,
    ) -> None:
        monkeypatch.setattr(uc.sys, "platform", "darwin")

        result = uc.state_dir()

        assert result == fake_home / "Library" / "Application Support" / "starling"

    def test_state_dir_linux_prefers_xdg_state_home(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
    ) -> None:
        monkeypatch.setattr(uc.sys, "platform", "linux")
        monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path))

        result = uc.state_dir()

        assert result == tmp_path / "starling"

    def test_state_dir_linux_falls_back_to_local_state(
        self, monkeypatch: pytest.MonkeyPatch, fake_home: Path,
    ) -> None:
        monkeypatch.setattr(uc.sys, "platform", "linux")
        monkeypatch.delenv("XDG_STATE_HOME", raising=False)

        result = uc.state_dir()

        assert result == fake_home / ".local" / "state" / "starling"

    def test_state_dir_is_not_cwd_or_repo(self, fake_home: Path) -> None:
        result = uc.state_dir()

        assert Path.cwd() not in result.parents
        assert result != Path.cwd()


# ---------------------------------------------------------------------------
# read_state / write_state
# ---------------------------------------------------------------------------


class TestStateFile:
    def test_read_state_missing_file(self, state_file: Path) -> None:
        assert uc.read_state(state_file) == {}

    def test_read_state_corrupt_json(self, state_file: Path) -> None:
        state_file.parent.mkdir(parents=True, exist_ok=True)
        state_file.write_text("{not json", encoding="utf-8")

        assert uc.read_state(state_file) == {}

    def test_read_state_non_dict_json(self, state_file: Path) -> None:
        state_file.parent.mkdir(parents=True, exist_ok=True)
        state_file.write_text("[1, 2]", encoding="utf-8")

        assert uc.read_state(state_file) == {}

    def test_read_state_drops_non_string_values(self, state_file: Path) -> None:
        state_file.parent.mkdir(parents=True, exist_ok=True)
        state_file.write_text(
            '{"last_checked": "2026-01-01", "n": 3}', encoding="utf-8",
        )

        assert uc.read_state(state_file) == {"last_checked": "2026-01-01"}

    def test_write_state_creates_parent_dirs(self, state_file: Path) -> None:
        assert not state_file.parent.exists()

        uc.write_state(state_file, {"last_checked": "2026-01-01"})

        assert state_file.exists()
        assert uc.read_state(state_file) == {"last_checked": "2026-01-01"}

    def test_write_state_unwritable_is_silent(
        self, monkeypatch: pytest.MonkeyPatch, state_file: Path,
    ) -> None:
        def _raise(*_args: object, **_kwargs: object) -> None:
            raise PermissionError

        monkeypatch.setattr(Path, "write_text", _raise)

        assert uc.write_state(state_file, {"last_checked": "2026-01-01"}) is None

    def test_write_state_leaves_no_temp_file(self, state_file: Path) -> None:
        uc.write_state(state_file, {"last_checked": "2026-01-01"})

        assert [p.name for p in state_file.parent.iterdir()] == [state_file.name]


# ---------------------------------------------------------------------------
# is_stale
# ---------------------------------------------------------------------------


class TestIsStale:
    @pytest.mark.parametrize(
        "last_checked",
        [
            pytest.param(None, id="none"),
            pytest.param("", id="empty_string"),
        ],
    )
    def test_is_stale_missing_timestamp(self, last_checked: str | None) -> None:
        assert uc.is_stale(last_checked) is True

    def test_is_stale_fresh_cache(self) -> None:
        now = datetime.now(tz=UTC)
        last_checked = (now - timedelta(days=2)).date().isoformat()

        assert uc.is_stale(last_checked, now=now) is False

    def test_is_stale_six_days(self) -> None:
        now = datetime.now(tz=UTC)
        last_checked = (now - timedelta(days=6)).date().isoformat()

        assert uc.is_stale(last_checked, now=now) is False

    def test_is_stale_exactly_seven_days(self) -> None:
        now = datetime.now(tz=UTC)
        last_checked = (now - timedelta(days=7)).date().isoformat()

        assert uc.is_stale(last_checked, now=now) is True

    @pytest.mark.parametrize(
        "last_checked",
        [
            pytest.param("not-a-date", id="not_a_date"),
            pytest.param("2026-13-45", id="invalid_calendar_date"),
        ],
    )
    def test_is_stale_corrupt_timestamp(self, last_checked: str) -> None:
        assert uc.is_stale(last_checked) is True

    def test_is_stale_future_timestamp(self) -> None:
        """Clock skew must not wedge the throttle shut permanently."""
        now = datetime.now(tz=UTC)
        last_checked = (now + timedelta(days=3)).date().isoformat()

        assert uc.is_stale(last_checked, now=now) is True


# ---------------------------------------------------------------------------
# get_latest_release
# ---------------------------------------------------------------------------


class TestGetLatestRelease:
    def test_get_latest_release_returns_first_entry(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        body = [{"tag_name": "v0.2.0"}, {"tag_name": "v0.1.0"}]
        monkeypatch.setattr(requests, "get", Mock(return_value=_response(json_body=body)))

        assert uc.get_latest_release() == {"tag_name": "v0.2.0"}

    def test_get_latest_release_empty_array(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(requests, "get", Mock(return_value=_response(json_body=[])))

        assert uc.get_latest_release() is None

    def test_get_latest_release_rate_limited(self, monkeypatch: pytest.MonkeyPatch) -> None:
        response = _response(status_code=403)
        monkeypatch.setattr(requests, "get", Mock(return_value=response))

        assert uc.get_latest_release() is None
        response.json.assert_not_called()

    def test_get_latest_release_server_error(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(requests, "get", Mock(return_value=_response(status_code=500)))

        assert uc.get_latest_release() is None

    def test_get_latest_release_timeout(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(
            requests, "get", Mock(side_effect=requests.exceptions.Timeout),
        )

        assert uc.get_latest_release() is None

    def test_get_latest_release_connection_error(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr(
            requests, "get", Mock(side_effect=requests.exceptions.ConnectionError),
        )

        assert uc.get_latest_release() is None

    def test_get_latest_release_malformed_json(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        response = _response()
        response.json.side_effect = ValueError
        monkeypatch.setattr(requests, "get", Mock(return_value=response))

        assert uc.get_latest_release() is None

    def test_get_latest_release_non_list_payload(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        body = {"message": "Not Found"}
        monkeypatch.setattr(requests, "get", Mock(return_value=_response(json_body=body)))

        assert uc.get_latest_release() is None

    def test_get_latest_release_sends_timeout(self, monkeypatch: pytest.MonkeyPatch) -> None:
        body = [{"tag_name": "v0.2.0"}]
        get = Mock(return_value=_response(json_body=body))
        monkeypatch.setattr(requests, "get", get)

        uc.get_latest_release()

        assert get.call_args.kwargs["timeout"] == 5


# ---------------------------------------------------------------------------
# latest_release_tag
# ---------------------------------------------------------------------------


class TestLatestReleaseTag:
    def test_latest_release_tag_missing_tag_name(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        body = [{"name": "0.2.0"}]
        monkeypatch.setattr(requests, "get", Mock(return_value=_response(json_body=body)))

        assert uc.latest_release_tag() is None

    def test_latest_release_tag_non_string(self, monkeypatch: pytest.MonkeyPatch) -> None:
        body = [{"tag_name": 42}]
        monkeypatch.setattr(requests, "get", Mock(return_value=_response(json_body=body)))

        assert uc.latest_release_tag() is None

    def test_latest_release_tag_blank(self, monkeypatch: pytest.MonkeyPatch) -> None:
        body = [{"tag_name": "   "}]
        monkeypatch.setattr(requests, "get", Mock(return_value=_response(json_body=body)))

        assert uc.latest_release_tag() is None


# ---------------------------------------------------------------------------
# refresh_state
# ---------------------------------------------------------------------------


class TestRefreshState:
    def test_refresh_state_caches_tag(
        self, monkeypatch: pytest.MonkeyPatch, state_file: Path,
    ) -> None:
        uc.write_state(state_file, {"last_checked": "2000-01-01"})
        body = [{"tag_name": "v0.2.0"}]
        monkeypatch.setattr(requests, "get", Mock(return_value=_response(json_body=body)))

        uc.refresh_state(state_file)

        assert uc.read_state(state_file)["latest_version"] == "v0.2.0"

    def test_refresh_state_preserves_last_checked(
        self, monkeypatch: pytest.MonkeyPatch, state_file: Path,
    ) -> None:
        uc.write_state(state_file, {"last_checked": "2000-01-01"})
        body = [{"tag_name": "v0.2.0"}]
        monkeypatch.setattr(requests, "get", Mock(return_value=_response(json_body=body)))

        uc.refresh_state(state_file)

        state = uc.read_state(state_file)
        assert state["last_checked"] == "2000-01-01"
        assert state["latest_version"] == "v0.2.0"

    def test_refresh_state_silent_on_failure(
        self, monkeypatch: pytest.MonkeyPatch, state_file: Path,
    ) -> None:
        uc.write_state(state_file, {"last_checked": "2000-01-01"})
        before = state_file.read_bytes()
        monkeypatch.setattr(
            requests, "get", Mock(side_effect=requests.exceptions.ConnectionError),
        )

        uc.refresh_state(state_file)

        assert state_file.read_bytes() == before


# ---------------------------------------------------------------------------
# maybe_notify_update
# ---------------------------------------------------------------------------


class TestMaybeNotifyUpdate:
    def test_maybe_notify_dev_version_short_circuits(
        self,
        monkeypatch: pytest.MonkeyPatch,
        state_file: Path,
        captured_threads: list[MagicMock],
    ) -> None:
        monkeypatch.setattr(uc, "APP_VERSION", "dev")
        stream = io.StringIO()

        uc.maybe_notify_update(stream=stream)

        assert stream.getvalue() == ""
        assert captured_threads == []
        assert not state_file.exists()

    def test_maybe_notify_opt_out_false(
        self,
        monkeypatch: pytest.MonkeyPatch,
        clean_env: None,
        state_file: Path,
        captured_threads: list[MagicMock],
    ) -> None:
        monkeypatch.setattr(uc, "APP_VERSION", "0.1.0")
        monkeypatch.setenv("STARLING_UPDATE_CHECK", "false")
        stream = io.StringIO()

        uc.maybe_notify_update(stream=stream)

        assert stream.getvalue() == ""
        assert captured_threads == []

    @pytest.mark.parametrize(
        "value",
        [
            pytest.param("0", id="zero"),
            pytest.param("no", id="no"),
            pytest.param("off", id="off"),
            pytest.param("FALSE", id="uppercase_false"),
        ],
    )
    def test_maybe_notify_opt_out_variants(
        self,
        monkeypatch: pytest.MonkeyPatch,
        clean_env: None,
        state_file: Path,
        captured_threads: list[MagicMock],
        value: str,
    ) -> None:
        monkeypatch.setattr(uc, "APP_VERSION", "0.1.0")
        monkeypatch.setenv("STARLING_UPDATE_CHECK", value)

        uc.maybe_notify_update(stream=io.StringIO())

        assert captured_threads == []

    def test_maybe_notify_enabled_by_default(
        self,
        monkeypatch: pytest.MonkeyPatch,
        clean_env: None,
        state_file: Path,
        captured_threads: list[MagicMock],
    ) -> None:
        monkeypatch.setattr(uc, "APP_VERSION", "0.1.0")
        uc.write_state(state_file, {"last_checked": "2000-01-01"})

        uc.maybe_notify_update(stream=io.StringIO())

        assert len(captured_threads) == 1

    def test_maybe_notify_explicit_true_enables(
        self,
        monkeypatch: pytest.MonkeyPatch,
        clean_env: None,
        state_file: Path,
        captured_threads: list[MagicMock],
    ) -> None:
        monkeypatch.setattr(uc, "APP_VERSION", "0.1.0")
        monkeypatch.setenv("STARLING_UPDATE_CHECK", "true")
        uc.write_state(state_file, {"last_checked": "2000-01-01"})

        uc.maybe_notify_update(stream=io.StringIO())

        assert len(captured_threads) == 1

    def test_maybe_notify_prints_cached_newer_version(
        self,
        monkeypatch: pytest.MonkeyPatch,
        clean_env: None,
        state_file: Path,
        captured_threads: list[MagicMock],
    ) -> None:
        monkeypatch.setattr(uc, "APP_VERSION", "0.1.0")
        today = datetime.now(tz=UTC).date().isoformat()
        uc.write_state(
            state_file, {"latest_version": "v0.2.0", "last_checked": today},
        )
        stream = io.StringIO()

        uc.maybe_notify_update(stream=stream)

        output = stream.getvalue()
        assert "v0.2.0" in output
        assert "0.1.0" in output
        assert uc.RELEASES_HTML_URL in output

    def test_maybe_notify_silent_when_cache_equal(
        self,
        monkeypatch: pytest.MonkeyPatch,
        clean_env: None,
        state_file: Path,
        captured_threads: list[MagicMock],
    ) -> None:
        monkeypatch.setattr(uc, "APP_VERSION", "0.1.0")
        today = datetime.now(tz=UTC).date().isoformat()
        uc.write_state(
            state_file, {"latest_version": "v0.1.0", "last_checked": today},
        )
        stream = io.StringIO()

        uc.maybe_notify_update(stream=stream)

        assert stream.getvalue() == ""

    def test_maybe_notify_silent_when_cache_older(
        self,
        monkeypatch: pytest.MonkeyPatch,
        clean_env: None,
        state_file: Path,
        captured_threads: list[MagicMock],
    ) -> None:
        monkeypatch.setattr(uc, "APP_VERSION", "0.2.0")
        today = datetime.now(tz=UTC).date().isoformat()
        uc.write_state(
            state_file, {"latest_version": "v0.1.0", "last_checked": today},
        )
        stream = io.StringIO()

        uc.maybe_notify_update(stream=stream)

        assert stream.getvalue() == ""

    def test_maybe_notify_fresh_cache_skips_network(
        self,
        monkeypatch: pytest.MonkeyPatch,
        clean_env: None,
        state_file: Path,
        captured_threads: list[MagicMock],
        no_network: None,
    ) -> None:
        monkeypatch.setattr(uc, "APP_VERSION", "0.1.0")
        today = datetime.now(tz=UTC).date().isoformat()
        uc.write_state(state_file, {"last_checked": today})

        uc.maybe_notify_update(stream=io.StringIO())

        assert captured_threads == []

    def test_maybe_notify_stale_cache_starts_thread(
        self,
        monkeypatch: pytest.MonkeyPatch,
        clean_env: None,
        state_file: Path,
        captured_threads: list[MagicMock],
    ) -> None:
        monkeypatch.setattr(uc, "APP_VERSION", "0.1.0")
        stale = (datetime.now(tz=UTC) - timedelta(days=8)).date().isoformat()
        uc.write_state(state_file, {"last_checked": stale})

        uc.maybe_notify_update(stream=io.StringIO())

        assert len(captured_threads) == 1
        thread = captured_threads[0]
        assert thread.kwargs["daemon"] is True
        assert thread.kwargs["target"] is uc.refresh_state

    def test_maybe_notify_stamps_before_thread(
        self,
        monkeypatch: pytest.MonkeyPatch,
        clean_env: None,
        state_file: Path,
        captured_threads: list[MagicMock],
    ) -> None:
        monkeypatch.setattr(uc, "APP_VERSION", "0.1.0")
        stale = (datetime.now(tz=UTC) - timedelta(days=8)).date().isoformat()
        uc.write_state(state_file, {"last_checked": stale})

        uc.maybe_notify_update(stream=io.StringIO())

        today = datetime.now(tz=UTC).date().isoformat()
        # The stamp is on disk even though the thread body (which alone would set
        # latest_version) was never actually invoked -- captured_threads replaces
        # threading.Thread with a MagicMock, so .start() never runs the real target.
        # Proof the write happens before Thread.start(), not inside the thread body.
        state = uc.read_state(state_file)
        assert state["last_checked"] == today
        assert "latest_version" not in state

    def test_maybe_notify_no_state_file_starts_thread(
        self,
        monkeypatch: pytest.MonkeyPatch,
        clean_env: None,
        state_file: Path,
        captured_threads: list[MagicMock],
    ) -> None:
        monkeypatch.setattr(uc, "APP_VERSION", "0.1.0")
        assert not state_file.exists()

        uc.maybe_notify_update(stream=io.StringIO())

        assert len(captured_threads) == 1
        today = datetime.now(tz=UTC).date().isoformat()
        assert uc.read_state(state_file)["last_checked"] == today

    def test_maybe_notify_unwritable_state_never_raises(
        self,
        monkeypatch: pytest.MonkeyPatch,
        clean_env: None,
        state_file: Path,
    ) -> None:
        monkeypatch.setattr(uc, "APP_VERSION", "0.1.0")
        monkeypatch.setattr(
            uc, "write_state", Mock(side_effect=PermissionError),
        )

        assert uc.maybe_notify_update(stream=io.StringIO()) is None

    def test_maybe_notify_corrupt_state_recovers(
        self,
        monkeypatch: pytest.MonkeyPatch,
        clean_env: None,
        state_file: Path,
        captured_threads: list[MagicMock],
    ) -> None:
        monkeypatch.setattr(uc, "APP_VERSION", "0.1.0")
        state_file.parent.mkdir(parents=True, exist_ok=True)
        state_file.write_text("{{{", encoding="utf-8")
        stream = io.StringIO()

        uc.maybe_notify_update(stream=stream)

        assert stream.getvalue() == ""
        assert len(captured_threads) == 1
        # A corrupt cache is treated as empty (is_stale(None) is True), so the file gets
        # rewritten as valid JSON with today's stamp -- read_state would still return {}
        # if the corruption survived.
        today = datetime.now(tz=UTC).date().isoformat()
        assert uc.read_state(state_file) == {"last_checked": today}

    def test_maybe_notify_offline_is_indistinguishable(
        self,
        monkeypatch: pytest.MonkeyPatch,
        clean_env: None,
        state_file: Path,
        captured_threads: list[MagicMock],
    ) -> None:
        monkeypatch.setattr(uc, "APP_VERSION", "0.1.0")
        monkeypatch.setattr(
            requests, "get", Mock(side_effect=requests.exceptions.ConnectionError),
        )
        stream = io.StringIO()

        uc.maybe_notify_update(stream=stream)

        assert stream.getvalue() == ""
        thread = captured_threads[0]
        thread.kwargs["target"](*thread.kwargs["args"])  # run synchronously; must not raise

    def test_maybe_notify_swallows_unexpected_error(
        self,
        monkeypatch: pytest.MonkeyPatch,
        clean_env: None,
        state_file: Path,
    ) -> None:
        monkeypatch.setattr(uc, "APP_VERSION", "0.1.0")
        monkeypatch.setattr(uc, "read_state", Mock(side_effect=RuntimeError))

        assert uc.maybe_notify_update(stream=io.StringIO()) is None


# ---------------------------------------------------------------------------
# state_dir -- env-var-set-but-empty fallback (qa pass: 0 coverage before this)
# ---------------------------------------------------------------------------


class TestStateDirEnvFallback:
    def test_state_dir_windows_localappdata_unset_falls_back(
        self, monkeypatch: pytest.MonkeyPatch, fake_home: Path,
    ) -> None:
        """
        Exercise the Windows fallback the handoff says had zero coverage.

        The Windows branch's ``Path.home() / "AppData" / "Local"`` fallback had
        zero coverage per the handoff -- exercise it directly.
        """
        monkeypatch.setattr(uc.sys, "platform", "win32")
        monkeypatch.delenv("LOCALAPPDATA", raising=False)

        result = uc.state_dir()

        assert result == fake_home / "AppData" / "Local" / "starling"

    def test_state_dir_windows_localappdata_empty_falls_back(
        self, monkeypatch: pytest.MonkeyPatch, fake_home: Path,
    ) -> None:
        """
        A set-but-empty LOCALAPPDATA is falsy too, and must still fall back.

        Otherwise the ``or`` would resolve to a bare-empty base path instead.
        """
        monkeypatch.setattr(uc.sys, "platform", "win32")
        monkeypatch.setenv("LOCALAPPDATA", "")

        result = uc.state_dir()

        assert result == fake_home / "AppData" / "Local" / "starling"

    def test_state_dir_linux_xdg_state_home_empty_falls_back(
        self, monkeypatch: pytest.MonkeyPatch, fake_home: Path,
    ) -> None:
        monkeypatch.setattr(uc.sys, "platform", "linux")
        monkeypatch.setenv("XDG_STATE_HOME", "")

        result = uc.state_dir()

        assert result == fake_home / ".local" / "state" / "starling"


# ---------------------------------------------------------------------------
# read_state / write_state -- additional edge cases and concurrency
# ---------------------------------------------------------------------------


class TestStateFileAdditional:
    def test_read_state_permission_error(
        self, monkeypatch: pytest.MonkeyPatch, state_file: Path,
    ) -> None:
        """
        PermissionError gets the same silent-empty-dict contract as a missing file.

        It is an OSError subclass -- a distinct failure mode from FileNotFoundError,
        worth pinning on its own.
        """
        state_file.parent.mkdir(parents=True, exist_ok=True)
        state_file.write_text("{}", encoding="utf-8")

        def _raise(*_args: object, **_kwargs: object) -> str:
            raise PermissionError

        monkeypatch.setattr(Path, "read_text", _raise)

        assert uc.read_state(state_file) == {}

    def test_write_state_replace_failure_leaves_no_temp_file(
        self, monkeypatch: pytest.MonkeyPatch, state_file: Path,
    ) -> None:
        """
        The cleanup branch must fire when os.replace itself fails, not just write_text.

        Here the temp file is written successfully and only os.replace fails -- the
        cleanup branch must still remove the orphaned temp file rather than leaving
        it behind forever.
        """

        def _raise(*_args: object, **_kwargs: object) -> None:
            raise OSError

        monkeypatch.setattr(uc.os, "replace", _raise)

        uc.write_state(state_file, {"last_checked": "2026-01-01"})

        assert not state_file.exists()
        assert list(state_file.parent.iterdir()) == []

    def test_write_state_concurrent_writers_same_process_can_lose_writes(
        self, state_file: Path,
    ) -> None:
        """
        CONFIRMED bug: same-process concurrency can silently lose writes.

        Twenty threads race write_state on the shared, PID-only temp path
        (``os.getpid()`` carries no per-thread component). On Windows this makes
        concurrent ``os.replace`` calls collide with ``WinError 32``
        (ERROR_SHARING_VIOLATION) / ``WinError 5`` (ERROR_ACCESS_DENIED), which
        write_state's bare ``except OSError`` swallows silently. In isolation this
        reproducibly loses *every* write on this machine (read_state comes back
        ``{}``, no state file at all); inside the full suite's thread pressure a
        single writer has been observed to survive instead -- the exact extent of
        loss is timing-dependent, so this asserts the invariants that DO hold under
        either outcome: write_state never raises, and read_state never comes back
        torn or corrupted, only ever empty or one complete write. The deterministic
        test below pins the actual loss mechanism without relying on OS scheduling.
        Currently unreachable in production (today's only two write_state call sites
        -- the main-thread stamp and the later daemon-thread refresh -- are
        temporally separated, not concurrent), but a real latent gap if a future
        change adds a second concurrent write path; see the handoff's own note about
        a still-finishing daemon thread from a fast invocation racing the same
        process's next write.
        """
        errors: list[BaseException] = []

        def _writer(i: int) -> None:
            try:
                uc.write_state(state_file, {"i": str(i)})
            except BaseException as exc:
                errors.append(exc)

        threads = [
            threading.Thread(target=_writer, args=(i,), daemon=True) for i in range(20)
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=5)

        # write_state's "never raises" contract holds even under this contention.
        assert errors == []
        # But the result is never guaranteed to reflect any particular writer, and
        # heavy contention can and does drop writes entirely -- pin only that the
        # surviving state (if any) is one complete, uncorrupted write, not a torn one.
        state = uc.read_state(state_file)
        assert state in [{}, *({"i": str(i)} for i in range(20))]

    def test_write_state_same_process_concurrent_writers_can_silently_lose_a_write(
        self, monkeypatch: pytest.MonkeyPatch, state_file: Path,
    ) -> None:
        """
        Pins the gap the handoff flagged: same-process writers share a temp path.

        The temp file is suffixed with ``os.getpid()``, not a thread id, so two
        write_state calls racing in the SAME process share one temp path. Writer "a"
        is paused (via a monkeypatched os.replace) right after writing its own temp
        file but before renaming it; writer "b" then runs to completion, renaming the
        (now b-owned) shared temp path away. When "a" resumes, its own rename target
        no longer exists -- FileNotFoundError, silently swallowed by write_state's
        `except OSError` -- so "a"'s entire update vanishes without a trace and
        without raising.
        """
        a_wrote = threading.Event()
        b_done = threading.Event()
        original_replace = uc.os.replace

        def _paced_replace(src: object, dst: object) -> None:
            if threading.current_thread().name == "writer-a":
                a_wrote.set()
                assert b_done.wait(timeout=5)
            original_replace(src, dst)
            if threading.current_thread().name == "writer-b":
                b_done.set()

        monkeypatch.setattr(uc.os, "replace", _paced_replace)

        def _write_a() -> None:
            uc.write_state(state_file, {"who": "a"})

        def _write_b() -> None:
            assert a_wrote.wait(timeout=5)
            uc.write_state(state_file, {"who": "b"})

        thread_a = threading.Thread(target=_write_a, name="writer-a", daemon=True)
        thread_b = threading.Thread(target=_write_b, name="writer-b", daemon=True)
        thread_a.start()
        thread_b.start()
        thread_a.join(timeout=5)
        thread_b.join(timeout=5)

        assert uc.read_state(state_file)["who"] == "b"


# ---------------------------------------------------------------------------
# is_stale -- additional boundary
# ---------------------------------------------------------------------------


class TestIsStaleAdditional:
    def test_is_stale_datetime_with_time_component_is_treated_as_corrupt(self) -> None:
        """
        A full datetime string is treated as a corrupt timestamp, not truncated.

        date.fromisoformat rejects a full datetime string (with a time/offset
        component), so it takes the same "corrupt timestamp -> stale" branch as
        "not-a-date", not a silent truncation to the date part.
        """
        now = datetime.now(tz=UTC)
        full_datetime = now.isoformat()

        assert uc.is_stale(full_datetime, now=now) is True


# ---------------------------------------------------------------------------
# get_latest_release -- exception-narrowing boundary
# ---------------------------------------------------------------------------


class TestGetLatestReleaseExceptionNarrowing:
    def test_get_latest_release_unnarrowed_exception_propagates(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """
        Pins the boundary of the except clause named in the handoff's risk list.

        Only (RequestException, ValueError) are caught, so an unrelated exception
        from .json() is NOT swallowed inside get_latest_release itself -- the caller
        (refresh_state / maybe_notify_update's outer bare except) is the real backstop.
        """
        response = _response()
        response.json.side_effect = KeyError("boom")
        monkeypatch.setattr(requests, "get", Mock(return_value=response))

        with pytest.raises(KeyError):
            uc.get_latest_release()


# ---------------------------------------------------------------------------
# refresh_state -- additional resilience
# ---------------------------------------------------------------------------


class TestRefreshStateAdditional:
    def test_refresh_state_swallows_unexpected_exception_type(
        self, monkeypatch: pytest.MonkeyPatch, state_file: Path,
    ) -> None:
        """
        refresh_state's own bare except is the backstop for the gap pinned above.

        An exception type outside get_latest_release's narrow except clause still
        must not escape the background thread's body.
        """
        uc.write_state(state_file, {"last_checked": "2000-01-01"})
        before = state_file.read_bytes()
        monkeypatch.setattr(uc, "latest_release_tag", Mock(side_effect=KeyError("boom")))

        uc.refresh_state(state_file)

        assert state_file.read_bytes() == before


# ---------------------------------------------------------------------------
# update_check_enabled -- additional boundary
# ---------------------------------------------------------------------------


class TestUpdateCheckEnabledAdditional:
    def test_update_check_enabled_whitespace_padded_disable_value(
        self, monkeypatch: pytest.MonkeyPatch, clean_env: None,
    ) -> None:
        monkeypatch.setenv("STARLING_UPDATE_CHECK", "  FALSE  ")

        assert uc.update_check_enabled() is False


# ---------------------------------------------------------------------------
# maybe_notify_update -- additional combination/boundary coverage
# ---------------------------------------------------------------------------


class TestMaybeNotifyUpdateAdditional:
    def test_maybe_notify_prints_notice_and_starts_thread_together(
        self,
        monkeypatch: pytest.MonkeyPatch,
        clean_env: None,
        state_file: Path,
        captured_threads: list[MagicMock],
    ) -> None:
        """
        Combination boundary no existing test covers.

        A newer cached tag (fires the notice) AND a stale cache (fires the refresh
        thread) in the same call.
        """
        monkeypatch.setattr(uc, "APP_VERSION", "0.1.0")
        stale = (datetime.now(tz=UTC) - timedelta(days=8)).date().isoformat()
        uc.write_state(
            state_file, {"latest_version": "v0.2.0", "last_checked": stale},
        )
        stream = io.StringIO()

        uc.maybe_notify_update(stream=stream)

        assert "v0.2.0" in stream.getvalue()
        assert len(captured_threads) == 1

    def test_maybe_notify_unparseable_non_dev_version_short_circuits(
        self,
        monkeypatch: pytest.MonkeyPatch,
        state_file: Path,
        captured_threads: list[MagicMock],
    ) -> None:
        """
        A digit-less, non-"dev" APP_VERSION takes the same early-exit branch.

        normalize_version("unknown") == () takes the same early-exit branch as the
        literal "dev" sentinel -- any digit-less APP_VERSION must bail before ever
        touching the filesystem, not just the one hardcoded value.
        """
        monkeypatch.setattr(uc, "APP_VERSION", "unknown")
        stream = io.StringIO()

        uc.maybe_notify_update(stream=stream)

        assert stream.getvalue() == ""
        assert captured_threads == []
        assert not state_file.exists()
