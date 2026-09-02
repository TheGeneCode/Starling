"""The packaged icon resource, and the guarantee that a missing one is harmless."""

from __future__ import annotations

from importlib.resources import as_file, files

import pytest

import starling.capture

tk = pytest.importorskip("tkinter")

REQUIRED_SIZES = {(16, 16), (32, 32), (48, 48), (256, 256)}


def test_icon_resource_is_packaged() -> None:
    """The .ico resolves through importlib.resources, not a repo-relative path."""
    resource = files("starling").joinpath("resources", "starling.ico")
    assert resource.is_file()


def test_icon_is_a_multi_size_ico() -> None:
    """A renamed PNG would not work with iconbitmap; assert the real ICO sizes."""
    from PIL import Image

    resource = files("starling").joinpath("resources", "starling.ico")
    with as_file(resource) as path, Image.open(path) as img:
        assert img.format == "ICO"
        assert set(img.info["sizes"]) >= REQUIRED_SIZES


def test_apply_window_icon_succeeds_on_a_real_root(tk_root) -> None:
    """The happy path must not raise. On Windows it also actually sets the icon."""
    starling.capture.apply_window_icon(tk_root)


def test_apply_window_icon_survives_a_missing_resource(
    monkeypatch: pytest.MonkeyPatch, tk_root
) -> None:
    """A wheel built without the icon must still open the window."""

    def _missing(*args: object, **kwargs: object) -> None:
        raise FileNotFoundError(2, "No such file", "starling.ico")

    monkeypatch.setattr(starling.capture, "as_file", _missing)
    starling.capture.apply_window_icon(tk_root)


def test_apply_window_icon_survives_permissionerror_from_as_file(
    monkeypatch: pytest.MonkeyPatch, tk_root
) -> None:
    """A different OSError subclass (unreadable resource) is caught the same way."""

    def _denied(*args: object, **kwargs: object) -> None:
        raise PermissionError(13, "Permission denied", "starling.ico")

    monkeypatch.setattr(starling.capture, "as_file", _denied)
    starling.capture.apply_window_icon(tk_root)


def test_apply_window_icon_survives_tclerror() -> None:
    """Iconbitmap raises TclError off Windows; that is a no-op, not a failure."""

    class FakeRoot:
        def iconbitmap(self, path: str) -> None:
            raise tk.TclError("wrong # args")

    starling.capture.apply_window_icon(FakeRoot())


def test_apply_window_icon_survives_oserror_raised_directly_by_iconbitmap() -> None:
    """A corrupted/unreadable .ico surfaces as OSError from iconbitmap itself, not as_file."""

    class FakeRoot:
        def iconbitmap(self, path: str) -> None:
            raise OSError("bad icon format")

    starling.capture.apply_window_icon(FakeRoot())


def test_apply_window_icon_does_not_swallow_other_exception_types() -> None:
    """
    Only OSError and TclError are meant to be swallowed.

    A FakeRoot that raises something else (e.g. a bug surfacing as ValueError) must
    propagate -- silently eating every exception here would hide real defects, not just
    a missing/unsupported icon.
    """

    class FakeRoot:
        def iconbitmap(self, path: str) -> None:
            raise ValueError("unexpected")

    with pytest.raises(ValueError, match="unexpected"):
        starling.capture.apply_window_icon(FakeRoot())


def test_apply_window_icon_is_idempotent_on_the_same_root(tk_root) -> None:
    """Calling it twice on one root (e.g. a second _build_ui) must not raise either time."""
    starling.capture.apply_window_icon(tk_root)
    starling.capture.apply_window_icon(tk_root)


def test_capture_window_builds_when_the_icon_is_missing(
    monkeypatch: pytest.MonkeyPatch, tk_root, tmp_config
) -> None:
    """The regression this whole guard exists to prevent."""

    def _missing(*args: object, **kwargs: object) -> None:
        raise FileNotFoundError(2, "No such file", "starling.ico")

    monkeypatch.setattr(starling.capture, "as_file", _missing)
    window = starling.capture.CaptureWindow(
        tmp_config, root=tk_root, clipboard_read=lambda: ""
    )
    assert window.root is tk_root
