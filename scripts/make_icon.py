"""Regenerate src/starling/resources/starling.ico from resources/icons/starling.png."""

from pathlib import Path

from PIL import Image

SIZES = [16, 24, 32, 48, 64, 128, 256]

root = Path(__file__).parent.parent
src = root / "resources" / "icons" / "starling.png"
# The .ico ships inside the package so importlib.resources finds it in an editable
# install and in a built wheel alike. The .png source stays out of the distribution.
dst = root / "src" / "starling" / "resources" / "starling.ico"
dst.parent.mkdir(parents=True, exist_ok=True)

img = Image.open(src).convert("RGBA")
frames = [img.resize((s, s), Image.LANCZOS) for s in SIZES]
img.save(dst, format="ICO", sizes=[(s, s) for s in SIZES], append_images=frames)
print(f"Saved {dst} ({dst.stat().st_size:,} bytes, {len(SIZES)} sizes: {SIZES})")
