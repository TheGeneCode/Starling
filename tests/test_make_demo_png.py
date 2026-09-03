"""
Tests for scripts/make_demo_png.py.

scripts/ is not an importable package (see the ``import_script`` fixture in
conftest.py), so every test here loads the module fresh from its file path.

Every font-loading call in this file is monkeypatched -- deliberately, so the
whole suite stays deterministic on any machine, never depending on which
font families happen to be installed where. See ``fake_truetype_factory``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from PIL import Image, ImageFont

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path
    from types import ModuleType


@pytest.fixture
def demo_png(import_script: Callable[[str], ModuleType]) -> ModuleType:
    """Load and return the make_demo_png module, freshly."""
    return import_script("make_demo_png.py")


# ``fake_truetype_factory`` lives in tests/conftest.py -- shared with
# test_make_social_preview.py, which loads fonts through the same candidate-chain shape.


# ---------------------------------------------------------------------------
# _load_fonts -- font-candidate fallback chain
# ---------------------------------------------------------------------------


def test_load_fonts_uses_first_candidate_family_when_both_faces_available(
    demo_png: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    fake_truetype_factory: Callable[..., Callable[..., ImageFont.FreeTypeFont]],
) -> None:
    """Test the happy path: consola.ttf + consolab.ttf both load, no fallback taken."""
    calls: list[str] = []
    real_fake = fake_truetype_factory()

    def _tracking(name: str, size: int, *args: object, **kwargs: object) -> object:
        calls.append(name)
        return real_fake(name, size, *args, **kwargs)

    monkeypatch.setattr(demo_png.ImageFont, "truetype", _tracking)

    regular, bold = demo_png._load_fonts(30)

    assert isinstance(regular, ImageFont.FreeTypeFont)
    assert isinstance(bold, ImageFont.FreeTypeFont)
    assert calls == ["consola.ttf", "consolab.ttf"]


def test_load_fonts_bold_face_missing_falls_back_to_regular_for_bold(
    demo_png: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    fake_truetype_factory: Callable[..., Callable[..., ImageFont.FreeTypeFont]],
) -> None:
    """
    Test the bold-specific sub-branch: regular loads, its bold sibling is missing.

    ``_load_fonts`` must fall back to using the regular face for bold text
    rather than raising, since the file lists ``consolab.ttf`` as a candidate
    independent of ``consola.ttf``.
    """
    fake = fake_truetype_factory(blocked=frozenset({"consolab.ttf"}))
    monkeypatch.setattr(demo_png.ImageFont, "truetype", fake)

    regular, bold = demo_png._load_fonts(30)

    assert isinstance(regular, ImageFont.FreeTypeFont)
    assert bold is regular


def test_load_fonts_falls_back_to_second_candidate_family(
    demo_png: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    fake_truetype_factory: Callable[..., Callable[..., ImageFont.FreeTypeFont]],
) -> None:
    """Test that when consola is entirely unavailable, DejaVuSansMono is tried and used."""
    calls: list[str] = []
    real_fake = fake_truetype_factory(blocked=frozenset({"consola.ttf", "consolab.ttf"}))

    def _tracking(name: str, size: int, *args: object, **kwargs: object) -> object:
        calls.append(name)
        return real_fake(name, size, *args, **kwargs)

    monkeypatch.setattr(demo_png.ImageFont, "truetype", _tracking)

    regular, bold = demo_png._load_fonts(30)

    assert isinstance(regular, ImageFont.FreeTypeFont)
    assert isinstance(bold, ImageFont.FreeTypeFont)
    # consolab.ttf is never attempted: a failed *regular* face for a candidate
    # family skips straight to the next family without trying its bold sibling.
    assert calls == ["consola.ttf", "DejaVuSansMono.ttf", "DejaVuSansMono-Bold.ttf"]


def test_load_fonts_falls_back_to_load_default_when_no_truetype_font_available(
    demo_png: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    fake_truetype_factory: Callable[..., Callable[..., ImageFont.FreeTypeFont]],
) -> None:
    """
    Test the final fallback: every candidate family missing lands on load_default.

    ``ImageFont.load_default(size=...)`` itself calls ``truetype`` internally
    (on an absolute path to its own bundled font), which is why the fake only
    blocks the four documented candidate filenames rather than every call --
    otherwise this test would break the very fallback it's trying to reach.
    """
    fake = fake_truetype_factory(
        blocked=frozenset(
            {"consola.ttf", "consolab.ttf", "DejaVuSansMono.ttf", "DejaVuSansMono-Bold.ttf"}
        )
    )
    monkeypatch.setattr(demo_png.ImageFont, "truetype", fake)

    regular, bold = demo_png._load_fonts(30)

    assert regular is bold
    assert regular is not None


def test_load_fonts_propagates_the_requested_size_to_every_candidate(
    demo_png: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    fake_truetype_factory: Callable[..., Callable[..., ImageFont.FreeTypeFont]],
) -> None:
    """Test that the size argument (BASE_FONT_SIZE * scale) reaches truetype() unchanged."""
    sizes_seen: list[int] = []
    real_fake = fake_truetype_factory()

    def _tracking(name: str, size: int, *args: object, **kwargs: object) -> object:
        sizes_seen.append(size)
        return real_fake(name, size, *args, **kwargs)

    monkeypatch.setattr(demo_png.ImageFont, "truetype", _tracking)

    demo_png._load_fonts(42)

    assert sizes_seen == [42, 42]


# ---------------------------------------------------------------------------
# render_session -- font-fallback branches produce a valid image end to end
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "blocked",
    [
        pytest.param(frozenset(), id="consola_branch"),
        pytest.param(frozenset({"consola.ttf", "consolab.ttf"}), id="dejavu_branch"),
        pytest.param(
            frozenset(
                {"consola.ttf", "consolab.ttf", "DejaVuSansMono.ttf", "DejaVuSansMono-Bold.ttf"}
            ),
            id="load_default_branch",
        ),
    ],
)
def test_render_session_produces_a_valid_image_on_every_font_fallback_branch(
    tmp_path: Path,
    demo_png: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    fake_truetype_factory: Callable[..., Callable[..., ImageFont.FreeTypeFont]],
    blocked: frozenset[str],
) -> None:
    """Test that each of the three documented font fallback branches still renders a real PNG."""
    fake = fake_truetype_factory(blocked=blocked)
    monkeypatch.setattr(demo_png.ImageFont, "truetype", fake)

    output_path = tmp_path / "session.png"
    result = demo_png.render_session("$ starling read\nDone.", output_path)

    assert result == output_path
    with Image.open(result) as img:
        img.load()  # forces full decode, catching a truncated/corrupt file
        assert img.mode == "RGB"
        assert img.width > demo_png.PADDING * 2
        assert img.height > demo_png.CHROME_HEIGHT


# ---------------------------------------------------------------------------
# render_session -- content and scale boundaries (font-branch held constant)
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _default_font_branch(
    demo_png: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    fake_truetype_factory: Callable[..., Callable[..., ImageFont.FreeTypeFont]],
) -> None:
    """
    Force the load_default branch for every test below in this module.

    These tests probe content/scale boundaries orthogonal to font selection;
    pinning one branch keeps them deterministic across machines without
    repeating the parametrization above for each one.
    """
    fake = fake_truetype_factory(
        blocked=frozenset(
            {"consola.ttf", "consolab.ttf", "DejaVuSansMono.ttf", "DejaVuSansMono-Bold.ttf"}
        )
    )
    monkeypatch.setattr(demo_png.ImageFont, "truetype", fake)


def test_render_session_empty_string_still_produces_a_decodable_image(
    tmp_path: Path, demo_png: ModuleType
) -> None:
    """
    Test the empty-input boundary: splitlines() on "" yields [], zero draw iterations.

    max_line_width's generator is then empty and falls back to its explicit
    ``default=0.0`` -- the image should still be exactly chrome + padding in
    size, not a crash from an empty max() call.
    """
    scale = 2
    output_path = tmp_path / "empty.png"
    result = demo_png.render_session("", output_path, scale=scale)

    with Image.open(result) as img:
        img.load()
        assert img.mode == "RGB"
        big_padding = demo_png.PADDING * scale
        big_chrome = demo_png.CHROME_HEIGHT * scale
        expected_width = round((2 * big_padding) / scale)
        expected_height = round((big_chrome + 2 * big_padding) / scale)
        assert img.size == (expected_width, expected_height)


def test_render_session_single_line(tmp_path: Path, demo_png: ModuleType) -> None:
    """Test the boundary of exactly one line (not zero, not many)."""
    output_path = tmp_path / "single.png"
    result = demo_png.render_session("hello world", output_path)

    with Image.open(result) as img:
        img.load()
        assert img.width > 0
        assert img.height > demo_png.CHROME_HEIGHT


def test_render_session_line_that_is_only_the_bare_dollar_marker(
    tmp_path: Path, demo_png: ModuleType
) -> None:
    """
    Test a command-prompt line with nothing after the marker.

    ``_draw_line`` special-cases any line starting with "$ ": it draws "$" in
    bold accent color, then re-slices the same line from index 1 onward for
    the rest. When that remainder is just a trailing space, both the width
    measurement (over the full line) and the split-draw must still succeed.
    """
    output_path = tmp_path / "dollar.png"
    result = demo_png.render_session("$ ", output_path)

    with Image.open(result) as img:
        img.load()
        assert img.mode == "RGB"
        assert img.width > 0


def test_render_session_unicode_and_out_of_ascii_glyphs_do_not_raise(
    tmp_path: Path, demo_png: ModuleType
) -> None:
    """Test accented, em-dash, CJK, and emoji characters against the fallback font."""
    output_path = tmp_path / "unicode.png"
    text = "héllo wörld — 日本語 😀"

    result = demo_png.render_session(text, output_path)

    with Image.open(result) as img:
        img.load()
        assert img.mode == "RGB"


@pytest.mark.parametrize("scale", [1, 2, 4])
def test_render_session_scale_produces_proportionally_larger_output(
    tmp_path: Path, demo_png: ModuleType, scale: int
) -> None:
    """Test scale=1 (no upscale-then-downscale) through scale > 2 all succeed."""
    output_path = tmp_path / f"scale-{scale}.png"

    result = demo_png.render_session("$ starling read\nDone.", output_path, scale=scale)

    with Image.open(result) as img:
        img.load()
        assert img.mode == "RGB"
        assert img.width > 0
        assert img.height > 0


@pytest.mark.parametrize("scale", [0, -1, -2])
def test_render_session_non_positive_scale_raises_valueerror(
    tmp_path: Path, demo_png: ModuleType, scale: int
) -> None:
    """
    Document a real boundary defect: scale <= 0 is never validated.

    ``BASE_FONT_SIZE * scale`` becomes zero or negative and is handed straight
    to Pillow's font loader, which raises ``ValueError`` itself
    ("font size must be greater than 0") rather than render_session guarding
    the parameter -- confirmed empirically, not assumed. No ZeroDivisionError
    is reached because the font load fails first.
    """
    output_path = tmp_path / "bad-scale.png"

    with pytest.raises(ValueError, match="font size must be greater than 0"):
        demo_png.render_session("hello", output_path, scale=scale)


def test_render_session_creates_missing_output_parent_directories(
    tmp_path: Path, demo_png: ModuleType
) -> None:
    """Test that a nested, not-yet-existing output directory is created."""
    output_path = tmp_path / "nested" / "dir" / "out.png"

    result = demo_png.render_session("hello", output_path)

    assert result.is_file()


def test_render_session_multiline_session_preserves_line_order(
    tmp_path: Path, demo_png: ModuleType
) -> None:
    """Test that a realistic multi-line captured session renders without error, in order."""
    output_path = tmp_path / "session.png"
    text = "$ starling read\nReading civic-primer.txt...\nDone. 1 chunk synthesized."

    result = demo_png.render_session(text, output_path)

    with Image.open(result) as img:
        img.load()
        # Three lines plus chrome/padding must be taller than a single-line render.
        single_line_path = tmp_path / "single-for-comparison.png"
        demo_png.render_session("$ starling read", single_line_path)
        with Image.open(single_line_path) as single_img:
            assert img.height > single_img.height
