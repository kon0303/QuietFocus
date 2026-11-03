"""Generate QuietFocus application and tray icons."""

from __future__ import annotations

import math
import os

from PIL import Image, ImageDraw

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ASSETS = os.path.join(ROOT, "assets")


def _rounded_mask(size: int, radius: int) -> Image.Image:
    mask = Image.new("L", (size * 4, size * 4), 0)
    draw = ImageDraw.Draw(mask)
    draw.rounded_rectangle(
        (0, 0, size * 4 - 1, size * 4 - 1), radius=radius * 4, fill=255
    )
    return mask.resize((size, size), Image.Resampling.LANCZOS)


def _gradient(size: int, top: tuple[int, int, int], bottom: tuple[int, int, int]) -> Image.Image:
    image = Image.new("RGB", (1, size))
    for y in range(size):
        t = y / max(1, size - 1)
        image.putpixel(
            (0, y),
            tuple(round(a + (b - a) * t) for a, b in zip(top, bottom)),
        )
    return image.resize((size, size))


def build_icon(size: int = 512) -> Image.Image:
    scale = size / 512.0
    base = _gradient(size, (24, 190, 168), (8, 111, 105)).convert("RGBA")
    base.putalpha(_rounded_mask(size, 112))

    # Soft highlight in the upper-left corner.
    glow = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    gd = ImageDraw.Draw(glow)
    gd.ellipse(
        (-size * 0.28, -size * 0.44, size * 0.74, size * 0.58),
        fill=(255, 255, 255, 30),
    )
    base = Image.alpha_composite(base, glow)

    draw = ImageDraw.Draw(base)
    white = (255, 255, 255, 255)
    soft = (255, 255, 255, 225)
    speaker = [
        (148 * scale, 212 * scale),
        (148 * scale, 300 * scale),
        (224 * scale, 354 * scale),
        (224 * scale, 158 * scale),
    ]
    draw.rounded_rectangle(
        (94 * scale, 212 * scale, 164 * scale, 300 * scale),
        radius=16 * scale,
        fill=white,
    )
    draw.polygon(speaker, fill=white)

    # Two clean sound waves.
    for radius, width, alpha in ((86, 26, 235), (136, 22, 150)):
        layer = Image.new("RGBA", (size, size), (0, 0, 0, 0))
        ld = ImageDraw.Draw(layer)
        cx, cy = 206 * scale, 256 * scale
        ld.arc(
            (cx - radius * scale, cy - radius * scale, cx + radius * scale, cy + radius * scale),
            start=-52,
            end=52,
            fill=(255, 255, 255, alpha),
            width=max(1, round(width * scale)),
        )
        base = Image.alpha_composite(base, layer)
        draw = ImageDraw.Draw(base)

    return base


def main() -> None:
    os.makedirs(ASSETS, exist_ok=True)
    icon = build_icon(512)
    icon.save(os.path.join(ASSETS, "icon.png"))
    icon.resize((128, 128), Image.Resampling.LANCZOS).save(
        os.path.join(ASSETS, "logo_128.png")
    )
    icon.resize((64, 64), Image.Resampling.LANCZOS).save(
        os.path.join(ASSETS, "logo_64.png")
    )
    icon.save(
        os.path.join(ASSETS, "icon.ico"),
        sizes=[(16, 16), (20, 20), (24, 24), (32, 32), (40, 40), (48, 48), (64, 64), (128, 128), (256, 256)],
    )
    print("icons written to", ASSETS)


if __name__ == "__main__":
    main()
