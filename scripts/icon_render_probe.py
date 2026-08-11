"""Render every registry icon offscreen and verify transparent background + visible content."""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PySide6.QtGui import QGuiApplication

from AssetsManager.core import icons

SIZES = (16, 32, 48)
COLORS = ("#ffffff", "#1a1a1a")
VISIBLE_ALPHA = 100


def _check(image) -> tuple[bool, bool]:
    """Return (has_transparent_pixel, has_visible_pixel) for the rendered image."""
    has_transparent = False
    has_visible = False
    for y in range(image.height()):
        for x in range(image.width()):
            alpha = image.pixelColor(x, y).alpha()
            has_transparent = has_transparent or alpha == 0
            has_visible = has_visible or alpha > VISIBLE_ALPHA
            if has_transparent and has_visible:
                return True, True
    return has_transparent, has_visible


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Print every check result instead of only failures and the summary",
    )
    args = parser.parse_args()

    QGuiApplication.instance() or QGuiApplication([])

    lines: list[str] = []
    failed = 0
    for name in icons.names():
        for size in SIZES:
            for color in COLORS:
                pixmap = icons.icon(name, color=color, size=size).pixmap(size, size)
                has_transparent, has_visible = _check(pixmap.toImage())
                ok = has_transparent and has_visible
                if not ok:
                    failed += 1
                if args.verbose or not ok:
                    lines.append(
                        f"{name:<16} {size:>3}px {color:<7} "
                        f"transparent={str(has_transparent):<5} "
                        f"visible={str(has_visible):<5} "
                        f"{'OK' if ok else 'FAIL'}"
                    )

    if lines:
        print("\n".join(lines))
    total = len(icons.names()) * len(SIZES) * len(COLORS)
    print(f"icons={len(icons.names())} combos={total} failed={failed}")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
