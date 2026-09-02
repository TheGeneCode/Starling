"""
Render a captured terminal session into a terminal-styled PNG.

Used to regenerate docs/screenshot.png, the README's header image, from real
`starling read --dry-run` output. See docs/DEMO.md for the full procedure and
why the image is captured rather than invented.
"""

from __future__ import annotations

import argparse
import contextlib
import sys
from pathlib import Path
from typing import Final

from PIL import Image, ImageDraw, ImageFont

BASE_FONT_SIZE: Final = 15
LINE_HEIGHT_MULT: Final = 1.35
PADDING: Final = 20
CHROME_HEIGHT: Final = 28
DOT_RADIUS: Final = 6
DOT_GAP: Final = 8
CAPTION: Final = "starling"

BACKGROUND: Final = "#1E1E2E"
CHROME: Final = "#181825"
FOREGROUND: Final = "#CDD6F4"
ACCENT: Final = "#A6E3A1"
DIM: Final = "#6C7086"
DOT_COLORS: Final[tuple[str, str, str]] = ("#F38BA8", "#F9E2AF", "#A6E3A1")

# (regular filename, bold filename), tried in order; the first regular font that
# loads wins, and its matching bold variant is attempted alongside it.
_FONT_CANDIDATES: Final[tuple[tuple[str, str], ...]] = (
    ("consola.ttf", "consolab.ttf"),
    ("DejaVuSansMono.ttf", "DejaVuSansMono-Bold.ttf"),
)


def _load_fonts(size: int) -> tuple[ImageFont.FreeTypeFont, ImageFont.FreeTypeFont]:
    """Resolve (regular, bold) fonts at size, falling back through the documented chain."""
    for regular_name, bold_name in _FONT_CANDIDATES:
        try:
            regular = ImageFont.truetype(regular_name, size)
        except OSError:
            continue
        try:
            bold = ImageFont.truetype(bold_name, size)
        except OSError:
            bold = regular
        return regular, bold

    default = ImageFont.load_default(size=size)
    return default, default


def _line_font(
    line: str,
    regular: ImageFont.FreeTypeFont,
    bold: ImageFont.FreeTypeFont,
) -> ImageFont.FreeTypeFont:
    """Command lines (`$ ...`) render bold when the font provides a bold face."""
    return bold if line.startswith("$ ") else regular


def _draw_line(
    draw: ImageDraw.ImageDraw,
    position: tuple[int, int],
    line: str,
    *,
    regular: ImageFont.FreeTypeFont,
    bold: ImageFont.FreeTypeFont,
) -> None:
    """Draw one session line, splitting the `$` prompt into its own accent colour."""
    x, y = position
    if line.startswith("$ "):
        draw.text((x, y), "$", font=bold, fill=ACCENT)
        prompt_width = draw.textlength("$", font=bold)
        draw.text((x + prompt_width, y), line[1:], font=bold, fill=FOREGROUND)
    else:
        draw.text((x, y), line, font=regular, fill=FOREGROUND)


def _draw_chrome(draw: ImageDraw.ImageDraw, width: int, height: int, scale: int) -> None:
    """Draw the title-bar-style chrome: three dots and a dim caption."""
    draw.rectangle((0, 0, width, height), fill=CHROME)
    radius = DOT_RADIUS * scale
    gap = DOT_GAP * scale
    center_y = height // 2
    x = PADDING * scale
    for color in DOT_COLORS:
        draw.ellipse(
            (x, center_y - radius, x + 2 * radius, center_y + radius),
            fill=color,
        )
        x += 2 * radius + gap

    caption_font = ImageFont.load_default(size=BASE_FONT_SIZE * scale)
    with contextlib.suppress(OSError):
        caption_font = ImageFont.truetype("consola.ttf", BASE_FONT_SIZE * scale)
    draw.text((x + gap, center_y), CAPTION, font=caption_font, fill=DIM, anchor="lm")


def render_session(text: str, output_path: Path, *, scale: int = 2) -> Path:
    """Render a captured terminal session's text into a PNG at output_path."""
    lines = text.splitlines()

    # Measure with the exact fonts used for drawing -- a separately-loaded font at
    # 1x size does not scale perfectly linearly with hinting, which was clipping
    # the widest line by a few pixels once resized back down.
    big_regular, big_bold = _load_fonts(BASE_FONT_SIZE * scale)
    measure = ImageDraw.Draw(Image.new("RGB", (1, 1)))
    big_line_height = round(BASE_FONT_SIZE * scale * LINE_HEIGHT_MULT)
    max_line_width = max(
        (
            measure.textlength(line, font=_line_font(line, big_regular, big_bold))
            for line in lines
        ),
        default=0.0,
    )

    big_padding = PADDING * scale
    big_chrome = CHROME_HEIGHT * scale
    big_width = round(max_line_width) + 2 * big_padding
    big_height = big_chrome + 2 * big_padding + big_line_height * len(lines)

    image = Image.new("RGB", (big_width, big_height), BACKGROUND)
    draw = ImageDraw.Draw(image)
    _draw_chrome(draw, big_width, big_chrome, scale)

    y = big_chrome + big_padding
    x = big_padding
    for line in lines:
        _draw_line(draw, (x, y), line, regular=big_regular, bold=big_bold)
        y += big_line_height

    width, height = round(big_width / scale), round(big_height / scale)
    image = image.resize((width, height), Image.LANCZOS)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    image.save(output_path, format="PNG", optimize=True)
    return output_path


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--input",
        required=True,
        help="Path to the captured session text, or - for stdin",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("docs/screenshot.png"),
        help="Where to write the rendered PNG (default: docs/screenshot.png)",
    )
    args = parser.parse_args()

    text = (
        sys.stdin.read()
        if args.input == "-"
        else Path(args.input).read_text(encoding="utf-8")
    )

    output_path = render_session(text, args.output)
    print(f"{output_path} ({output_path.stat().st_size:,} bytes)")


if __name__ == "__main__":
    main()
