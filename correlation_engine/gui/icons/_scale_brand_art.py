"""Derive the small rich-text sizes of the Wing and Feather brand art.

wing.png / feather.png (128 px) and wing@2x.png / feather@2x.png (256 px) are
the brand's art exactly as the User Guide and crow-eye.com draw it, byte for
byte; this script never touches them. Their masters are the SVGs in brand/:
<name>.svg for large sizes and <name>-small.svg (heavier outline and rim, so
the layers survive a small size) for 256 px and below. The 128 / 256 px files
are that small master rendered at 1024 px, given its glow, and scaled down.

This script does the same for every px in RICH_TEXT_SIZES: it renders
brand/<name>-small.svg, adds the same glow, and writes <name>-<px>.png and
<name>-<px>@2x.png, each scaled straight down from the 1024 px render (never
from a 256 px file, so no second resample softens it).

Why: a QLabel's rich text draws an <img> scaled with no smoothing, so the
256 px art shrunk to 16 px comes out speckled. icon_label_html points at
<name>-<px>.png instead, an exact-size file that is never rescaled (and Qt
takes its @2x on a high-density screen). CrowEyeIcons.wing() / feather() add
every one of these files to the QIcon, so a button or a row picks the closest
size too. Re-run after the art changes:

    python correlation_engine/gui/icons/_scale_brand_art.py
"""

from __future__ import annotations

import os
import sys

from PIL import Image, ImageFilter

BRAND_ART = ("wing", "feather")
RICH_TEXT_SIZES = (14, 16, 24)

# The master is drawn on a 1024 px canvas; the glow is added in image space at
# that size (colour, inner radius, inner strength, outer radius, outer strength).
MASTER_PX = 1024
GLOW = {
    "wing": ((99, 102, 241), 18, 0.5, 5, 0.26),
    "feather": ((34, 211, 238), 18, 0.7, 5, 0.36),
}

_HERE = os.path.dirname(os.path.abspath(__file__))
_MASTERS: dict = {}


def master_path(name: str, small: bool = True) -> str:
    return os.path.join(_HERE, "brand", f"{name}{'-small' if small else ''}.svg")


def _render_svg(path: str, size: int) -> Image.Image:
    """``path`` drawn at ``size`` px by Qt's SVG renderer, as an RGBA image."""
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PyQt5.QtCore import QByteArray, QRectF
    from PyQt5.QtGui import QGuiApplication, QImage, QPainter
    from PyQt5.QtSvg import QSvgRenderer

    if QGuiApplication.instance() is None:
        # A QApplication, so a test process that builds widgets afterwards
        # still has the application type it needs.
        from PyQt5.QtWidgets import QApplication
        _MASTERS["_app"] = QApplication(sys.argv[:1])
    with open(path, "r", encoding="utf-8") as f:
        renderer = QSvgRenderer(QByteArray(f.read().encode()))
    image = QImage(size, size, QImage.Format_ARGB32_Premultiplied)
    image.fill(0)
    painter = QPainter(image)
    painter.setRenderHints(QPainter.Antialiasing | QPainter.SmoothPixmapTransform
                           | QPainter.HighQualityAntialiasing)
    renderer.render(painter, QRectF(0, 0, size, size))
    painter.end()
    image = image.convertToFormat(QImage.Format_RGBA8888)
    ptr = image.bits()
    ptr.setsize(image.byteCount())
    return Image.frombuffer("RGBA", (size, size), bytes(ptr), "raw", "RGBA", 0, 1).copy()


def _add_glow(im: Image.Image, colour, r1, s1, r2, s2) -> Image.Image:
    alpha = im.getchannel("A")
    out = Image.new("RGBA", im.size, (0, 0, 0, 0))
    for radius, strength in ((r1, s1), (r2, s2)):
        if not radius or strength <= 0:
            continue
        glow = alpha.filter(ImageFilter.GaussianBlur(radius))
        glow = glow.point(lambda v, st=strength: int(min(255, v * st)))
        layer = Image.new("RGBA", im.size, colour + (0,))
        layer.putalpha(glow)
        out.alpha_composite(layer)
    out.alpha_composite(im)
    return out


def master(name: str) -> Image.Image:
    """The small master of ``name`` at 1024 px with its glow (cached)."""
    cached = _MASTERS.get(name)
    if cached is None:
        cached = _add_glow(_render_svg(master_path(name), MASTER_PX), *GLOW[name])
        _MASTERS[name] = cached
    return cached


def scaled(name: str, px: int) -> Image.Image:
    return master(name).resize((px, px), Image.LANCZOS)


def main() -> None:
    written = 0
    for name in BRAND_ART:
        for px in RICH_TEXT_SIZES:
            for suffix, side in (("", px), ("@2x", px * 2)):
                scaled(name, side).save(os.path.join(_HERE, f"{name}-{px}{suffix}.png"), optimize=True)
                written += 1
    print(f"Wrote {written} brand-art sizes in {_HERE}")


if __name__ == "__main__":
    main()
