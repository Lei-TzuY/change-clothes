#!/usr/bin/env python3
"""
Generate favicon assets from a source image.

Usage:
  python scripts/generate_favicon.py path/to/source.png

Outputs into app/static/:
  - favicon.ico (16,32,48,64 embedded)
  - favicon.png (512x512)
  - favicon-32.png (32x32)
  - favicon-16.png (16x16)
  - apple-touch-icon.png (180x180)
"""
import sys
from pathlib import Path
from PIL import Image


def main():
    if len(sys.argv) < 2:
        print("Usage: python scripts/generate_favicon.py path/to/source.png")
        return 1

    src = Path(sys.argv[1])
    if not src.exists():
        print(f"Source not found: {src}")
        return 1

    out_dir = Path(__file__).resolve().parents[1] / 'app' / 'static'
    out_dir.mkdir(parents=True, exist_ok=True)

    im = Image.open(src).convert('RGBA')

    # Square crop-center if needed
    w, h = im.size
    if w != h:
        side = min(w, h)
        left = (w - side) // 2
        top = (h - side) // 2
        im = im.crop((left, top, left + side, top + side))

    # Save PNG variants
    (im.resize((512, 512), Image.LANCZOS)).save(out_dir / 'favicon.png')
    (im.resize((32, 32), Image.LANCZOS)).save(out_dir / 'favicon-32.png')
    (im.resize((16, 16), Image.LANCZOS)).save(out_dir / 'favicon-16.png')
    (im.resize((180, 180), Image.LANCZOS)).save(out_dir / 'apple-touch-icon.png')

    # Save ICO with multiple sizes
    ico_sizes = [(16, 16), (32, 32), (48, 48), (64, 64)]
    im.save(out_dir / 'favicon.ico', sizes=ico_sizes)

    print(f"Generated favicon assets in {out_dir}")


if __name__ == '__main__':
    raise SystemExit(main())

