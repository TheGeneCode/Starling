"""
Weekly, non-blocking check for a newer Starling release on GitHub.

Ported from MeadowLark's ``src/version_utils.py`` (``normalize_version``,
``get_latest_app_release``, ``is_app_update_available``) and its weekly throttle in
``meadowlark.pyw``. The differences are all consequences of being a CLI rather than a
desktop app: there is no dialog, nothing may block, and the check runs on every single
invocation, so the throttle has to be durable rather than in-memory.

Every failure mode here -- no network, a timeout, a rate limit, malformed JSON, an
unwritable or corrupt state file -- is a silent no-op. A user with no internet must see
byte-for-byte the same output as a user who never had this feature.
"""

from __future__ import annotations

import contextlib
import json
import os
import re
import sys
import threading
from datetime import UTC, date, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Final

from dotenv import load_dotenv

from starling import __version__

if TYPE_CHECKING:
    from typing import TextIO

# Patched by tests, the way MeadowLark's tests patch src.version_utils.APP_VERSION.
APP_VERSION: str = __version__

DEV_VERSION: Final = "dev"
UPDATE_CHECK_VAR: Final = "STARLING_UPDATE_CHECK"
RELEASES_API_URL: Final = "https://api.github.com/repos/TheGeneCode/Starling/releases"
RELEASES_HTML_URL: Final = "https://github.com/TheGeneCode/Starling/releases"
APP_DIR_NAME: Final = "starling"
STATE_FILENAME: Final = "update-check.json"

_TIMEOUT_SECONDS: Final = 5
_CHECK_INTERVAL_DAYS: Final = 7
_HTTP_OK: Final = 200

# Anything else -- including an unset or blank variable -- leaves the check enabled.
_DISABLED_VALUES: Final[frozenset[str]] = frozenset({"0", "false", "no", "off"})


# --------------------------------------------------------------------------- version


def normalize_version(version: str | None) -> tuple[int, ...]:
    """
    Normalize a version string like 'v0.2.0' or '0.2.0' to a tuple of ints.

    Ported unchanged from MeadowLark. Non-strings and strings with no digits
    (including "dev") return an empty tuple, which every caller treats as "unknown",
    never as "version zero".
    """
    if not isinstance(version, str):
        return ()
    parts = re.findall(r"\d+", version)
    return tuple(int(x) for x in parts)


def is_update_available(current: str | None, latest: str | None) -> bool:
    """
    Return True only when ``latest`` is strictly newer than ``current``.

    Strictly greater, so an equal version and an *older* published release both return
    False -- Starling must never nag a user to move backwards. An unparseable version on
    either side returns False rather than guessing.
    """
    current_parts = normalize_version(current)
    latest_parts = normalize_version(latest)
    if not (current_parts and latest_parts):
        return False
    return latest_parts > current_parts


def format_notice(latest_tag: str, current: str) -> str:
    """Return the notice printed when a newer release exists."""
    return (
        f"A new Starling release is available: {latest_tag} (you have {current})\n"
        f"{RELEASES_HTML_URL}"
    )


# ------------------------------------------------------------------------------ env


def update_check_enabled() -> bool:
    """
    Return whether the update check is switched on. Enabled unless explicitly disabled.

    ``load_dotenv()`` is called here for the same reason ``config.load_config`` calls it:
    the opt-out is documented in ``.env.example``, so it has to be readable from a ``.env``.
    It does not override anything already in ``os.environ``, and calling it twice in one
    process is harmless.
    """
    load_dotenv()
    raw = (os.getenv(UPDATE_CHECK_VAR) or "").strip().casefold()
    return raw not in _DISABLED_VALUES if raw else True


# ---------------------------------------------------------------------------- state


def state_dir() -> Path:
    """
    Return the platform-appropriate directory for Starling's machine-local state.

    Deliberately not the repo, not the CWD, and not STARLING_HOME -- this is throttle
    bookkeeping, not user data, and STARLING_HOME may point into a synced folder.
    """
    if sys.platform == "win32":
        base = os.getenv("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
    elif sys.platform == "darwin":
        base = str(Path.home() / "Library" / "Application Support")
    else:
        base = os.getenv("XDG_STATE_HOME") or str(Path.home() / ".local" / "state")
    return Path(base) / APP_DIR_NAME


def state_path() -> Path:
    """Return the full path of the update-check state file."""
    return state_dir() / STATE_FILENAME


def read_state(path: Path) -> dict[str, str]:
    """
    Return the cached state, or an empty dict for a missing, unreadable, or corrupt file.

    A corrupt cache is indistinguishable from no cache: the next run rewrites it.
    """
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    if not isinstance(raw, dict):
        return {}
    return {str(k): v for k, v in raw.items() if isinstance(v, str)}


def write_state(path: Path, state: dict[str, str]) -> None:
    """
    Write the state file atomically. Any failure is swallowed.

    The temp file carries the PID because two Starling invocations can race here, and
    ``os.replace`` is atomic on both POSIX and Windows -- a reader therefore never sees a
    half-written file, which is what keeps ``read_state`` from having to distinguish
    "corrupt" from "being written".
    """
    tmp = path.with_name(f"{path.name}.{os.getpid()}.tmp")
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp.write_text(json.dumps(state), encoding="utf-8")
        os.replace(tmp, path)  # noqa: PTH105
    except OSError:
        with contextlib.suppress(OSError):
            tmp.unlink(missing_ok=True)


def is_stale(last_checked: str | None, *, now: datetime | None = None) -> bool:
    """
    Return whether a new check is due.

    True for a missing or unparseable timestamp (MeadowLark's ``except ValueError: pass``,
    made explicit), and true for a *future* timestamp -- a clock that jumped forward and
    back would otherwise wedge the throttle shut permanently.
    """
    if not last_checked:
        return True
    try:
        last = date.fromisoformat(last_checked)
    except (TypeError, ValueError):
        return True
    today = (now or datetime.now(tz=UTC)).date()
    days = (today - last).days
    return days >= _CHECK_INTERVAL_DAYS or days < 0


# ---------------------------------------------------------------------------- github


def get_latest_release() -> dict | None:
    """
    Fetch the most recent release from GitHub, including pre-releases.

    Returns None on any non-200 status (403 rate limits included), any transport error,
    malformed JSON, an empty releases array, or a payload that is not a list.
    ``requests`` is imported here rather than at module scope so the CLI's startup path
    never pays its import cost -- this function only ever runs on the refresh thread.
    """
    import requests  # noqa: PLC0415

    try:
        response = requests.get(
            RELEASES_API_URL,
            timeout=_TIMEOUT_SECONDS,
            headers={"Accept": "application/vnd.github+json"},
        )
        if response.status_code != _HTTP_OK:
            return None
        releases = response.json()
    except (requests.exceptions.RequestException, ValueError):
        return None
    if not isinstance(releases, list) or not releases:
        return None
    first = releases[0]
    return first if isinstance(first, dict) else None


def latest_release_tag() -> str | None:
    """Return the newest release's tag_name, or None if it is missing or not a string."""
    release = get_latest_release()
    if release is None:
        return None
    tag = release.get("tag_name")
    if not isinstance(tag, str) or not tag.strip():
        return None
    return tag.strip()


# --------------------------------------------------------------------------- refresh


def refresh_state(path: Path) -> None:
    """
    Body of the background thread: fetch the latest tag and cache it. Never raises.

    Re-reads the state file rather than closing over the caller's copy, so it cannot
    clobber the ``last_checked`` stamp the main thread wrote before starting this thread.
    """
    try:
        tag = latest_release_tag()
        if tag is None:
            return
        state = read_state(path)
        state["latest_version"] = tag
        write_state(path, state)
    except Exception:  # a background thread must never surface anything
        return


# ------------------------------------------------------------------------ entry point


def maybe_notify_update(stream: TextIO | None = None) -> None:
    """
    Print an update notice if one is cached, and schedule a refresh if the cache is stale.

    The only function the CLI calls. Wraps everything in a bare except: an update check
    must never be the reason Starling fails to do its actual job.
    """
    try:
        _maybe_notify_update(stream if stream is not None else sys.stderr)
    except Exception:  # see docstring
        return


def _maybe_notify_update(stream: TextIO) -> None:
    """Unguarded body of :func:`maybe_notify_update`."""
    # A source checkout has no release to compare against, and normalize_version("dev")
    # is empty anyway -- bail before touching the filesystem at all.
    if APP_VERSION == DEV_VERSION or not normalize_version(APP_VERSION):
        return
    if not update_check_enabled():
        return

    path = state_path()
    state = read_state(path)

    cached = state.get("latest_version")
    if is_update_available(APP_VERSION, cached):
        print(format_notice(str(cached), APP_VERSION), file=stream)

    if not is_stale(state.get("last_checked")):
        return

    # Stamp the throttle BEFORE spawning the thread. The thread is a daemon and is killed
    # outright when a short-lived command exits, so if the stamp waited for the thread's
    # result, a fast command like `starling usage` would re-hit GitHub on every single run
    # and burn the 60/hour unauthenticated rate limit.
    state["last_checked"] = datetime.now(tz=UTC).date().isoformat()
    write_state(path, state)

    threading.Thread(
        target=refresh_state,
        args=(path,),
        name="starling-update-check",
        daemon=True,
    ).start()
