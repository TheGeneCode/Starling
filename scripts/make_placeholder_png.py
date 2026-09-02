"""
Generate the PROVISIONAL Starling source icon at resources/icons/starling.png.

This is a placeholder, not artwork. Delete this script once a real starling.png exists;
scripts/make_icon.py is the only generator that needs to survive.
"""

from pathlib import Path

from PIL import Image, ImageDraw

SIZE = 1024
BACKGROUND = (26, 42, 58, 255)    # slate, provisional
FOREGROUND = (242, 201, 76, 255)  # amber, provisional

root = Path(__file__).parent.parent
dst = root / "resources" / "icons" / "starling.png"
dst.parent.mkdir(parents=True, exist_ok=True)

img = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
draw = ImageDraw.Draw(img)
draw.ellipse((0, 0, SIZE - 1, SIZE - 1), fill=BACKGROUND)
# A bare geometric glyph. Anything more would imply this is a real design.
draw.ellipse((SIZE * 0.28, SIZE * 0.28, SIZE * 0.72, SIZE * 0.72), fill=FOREGROUND)
draw.ellipse((SIZE * 0.40, SIZE * 0.40, SIZE * 0.60, SIZE * 0.60), fill=BACKGROUND)

img.save(dst, format="PNG")
print(f"Saved PROVISIONAL {dst} ({dst.stat().st_size:,} bytes, {SIZE}x{SIZE})")
