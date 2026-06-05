"""One-shot generator for the Crow-Eye-styled SVG icon set.

Run once to produce the 30 .svg files in this directory. Idempotent — safe
to re-run if you tweak the shapes; it overwrites in place. Not imported by
the loader (which just reads the .svg files directly).

Style: 24x24 viewBox, 2px stroke, square caps, transparent background.
Cyan #00FFFF for neutral icons; status colors (green/amber/red/grey) for
the status-specific icons; amber for star + tip glyph; otherwise cyan.
"""

from __future__ import annotations

import os


def svg(body: str, viewbox: str = "0 0 24 24") -> str:
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="{viewbox}" '
        f'fill="none" stroke-linecap="square" stroke-linejoin="miter">\n'
        f'{body}\n'
        f'</svg>\n'
    )


# Crow-Eye palette tokens (mirrors styles.Colors).
CYAN = "#00FFFF"
GREEN = "#10B981"
AMBER = "#F59E0B"
RED = "#EF4444"
GREY = "#94A3B8"
DARK_FG = "#0F172A"  # dark stamp inside filled-status shapes


ICONS: dict[str, str] = {}


# Status icons (5) — filled shape in the status color with a contrast glyph.
ICONS["success"] = svg(
    f'  <circle cx="12" cy="12" r="10" fill="{GREEN}" stroke="{GREEN}" stroke-width="2"/>\n'
    f'  <path d="M7 12.5 L10.5 16 L17 8.5" stroke="{DARK_FG}" stroke-width="2.5" fill="none"/>'
)

ICONS["warning"] = svg(
    f'  <path d="M12 3 L22 20 L2 20 Z" fill="{AMBER}" stroke="{AMBER}" stroke-width="2" stroke-linejoin="round"/>\n'
    f'  <line x1="12" y1="10" x2="12" y2="14.5" stroke="{DARK_FG}" stroke-width="2.5"/>\n'
    f'  <circle cx="12" cy="17" r="1.2" fill="{DARK_FG}"/>'
)

ICONS["error"] = svg(
    f'  <circle cx="12" cy="12" r="10" fill="{RED}" stroke="{RED}" stroke-width="2"/>\n'
    f'  <line x1="8" y1="8" x2="16" y2="16" stroke="{DARK_FG}" stroke-width="2.5"/>\n'
    f'  <line x1="16" y1="8" x2="8" y2="16" stroke="{DARK_FG}" stroke-width="2.5"/>'
)

ICONS["info"] = svg(
    f'  <circle cx="12" cy="12" r="10" stroke="{GREY}" stroke-width="2" fill="none"/>\n'
    f'  <circle cx="12" cy="7.5" r="1.2" fill="{GREY}"/>\n'
    f'  <line x1="12" y1="11" x2="12" y2="17" stroke="{GREY}" stroke-width="2"/>'
)

ICONS["fail"] = svg(
    f'  <line x1="5" y1="5" x2="19" y2="19" stroke="{RED}" stroke-width="3"/>\n'
    f'  <line x1="19" y1="5" x2="5" y2="19" stroke="{RED}" stroke-width="3"/>'
)


# Action icons (8)
ICONS["add"] = svg(
    f'  <line x1="12" y1="4" x2="12" y2="20" stroke="{CYAN}" stroke-width="2"/>\n'
    f'  <line x1="4" y1="12" x2="20" y2="12" stroke="{CYAN}" stroke-width="2"/>'
)

ICONS["edit"] = svg(
    f'  <path d="M4 20 L4 16 L16 4 L20 8 L8 20 Z" stroke="{CYAN}" stroke-width="2" fill="none"/>\n'
    f'  <line x1="14" y1="6" x2="18" y2="10" stroke="{CYAN}" stroke-width="2"/>'
)

ICONS["delete"] = svg(
    f'  <line x1="4" y1="6" x2="20" y2="6" stroke="{CYAN}" stroke-width="2"/>\n'
    f'  <path d="M6 6 L7 21 L17 21 L18 6" stroke="{CYAN}" stroke-width="2" fill="none"/>\n'
    f'  <path d="M9 6 L9 3 L15 3 L15 6" stroke="{CYAN}" stroke-width="2" fill="none"/>\n'
    f'  <line x1="10" y1="10" x2="10" y2="17" stroke="{CYAN}" stroke-width="2"/>\n'
    f'  <line x1="14" y1="10" x2="14" y2="17" stroke="{CYAN}" stroke-width="2"/>'
)

ICONS["copy"] = svg(
    f'  <rect x="8" y="3" width="13" height="13" rx="1" stroke="{CYAN}" stroke-width="2" fill="none"/>\n'
    f'  <path d="M16 16 L16 20 A1 1 0 0 1 15 21 L4 21 A1 1 0 0 1 3 20 L3 9 A1 1 0 0 1 4 8 L8 8" stroke="{CYAN}" stroke-width="2" fill="none"/>'
)

ICONS["star"] = svg(
    f'  <path d="M12 2 L15 9 L22.5 9.5 L17 14.5 L18.5 22 L12 18 L5.5 22 L7 14.5 L1.5 9.5 L9 9 Z" '
    f'fill="{AMBER}" stroke="{AMBER}" stroke-width="1.5" stroke-linejoin="round"/>'
)

ICONS["refresh"] = svg(
    f'  <path d="M3 12 A9 9 0 0 1 19 6 L21 4 M21 4 L21 9 M21 4 L16 4" stroke="{CYAN}" stroke-width="2" fill="none"/>\n'
    f'  <path d="M21 12 A9 9 0 0 1 5 18 L3 20 M3 20 L3 15 M3 20 L8 20" stroke="{CYAN}" stroke-width="2" fill="none"/>'
)

ICONS["download"] = svg(
    f'  <line x1="12" y1="3" x2="12" y2="16" stroke="{CYAN}" stroke-width="2"/>\n'
    f'  <path d="M6 11 L12 17 L18 11" stroke="{CYAN}" stroke-width="2" fill="none"/>\n'
    f'  <line x1="4" y1="20" x2="20" y2="20" stroke="{CYAN}" stroke-width="2"/>'
)

ICONS["save"] = svg(
    f'  <path d="M3 3 L17 3 L21 7 L21 21 L3 21 Z" stroke="{CYAN}" stroke-width="2" fill="none"/>\n'
    f'  <rect x="7" y="3" width="10" height="6" stroke="{CYAN}" stroke-width="2" fill="none"/>\n'
    f'  <rect x="6" y="14" width="12" height="7" stroke="{CYAN}" stroke-width="2" fill="none"/>'
)


# Navigation (6)
ICONS["prev"] = svg(
    f'  <line x1="19" y1="12" x2="5" y2="12" stroke="{CYAN}" stroke-width="2"/>\n'
    f'  <path d="M11 6 L5 12 L11 18" stroke="{CYAN}" stroke-width="2" fill="none"/>'
)

ICONS["next"] = svg(
    f'  <line x1="5" y1="12" x2="19" y2="12" stroke="{CYAN}" stroke-width="2"/>\n'
    f'  <path d="M13 6 L19 12 L13 18" stroke="{CYAN}" stroke-width="2" fill="none"/>'
)

ICONS["expand"] = svg(
    f'  <path d="M6 9 L12 15 L18 9" stroke="{CYAN}" stroke-width="2.5" fill="none"/>'
)

ICONS["collapse"] = svg(
    f'  <path d="M9 6 L15 12 L9 18" stroke="{CYAN}" stroke-width="2.5" fill="none"/>'
)

ICONS["up"] = svg(
    f'  <line x1="12" y1="19" x2="12" y2="5" stroke="{CYAN}" stroke-width="2"/>\n'
    f'  <path d="M6 11 L12 5 L18 11" stroke="{CYAN}" stroke-width="2" fill="none"/>'
)

ICONS["down"] = svg(
    f'  <line x1="12" y1="5" x2="12" y2="19" stroke="{CYAN}" stroke-width="2"/>\n'
    f'  <path d="M6 13 L12 19 L18 13" stroke="{CYAN}" stroke-width="2" fill="none"/>'
)


# Decoration (11)
ICONS["folder"] = svg(
    f'  <path d="M2 6 L2 19 A1 1 0 0 0 3 20 L21 20 A1 1 0 0 0 22 19 L22 8 A1 1 0 0 0 21 7 '
    f'L11 7 L9 5 L3 5 A1 1 0 0 0 2 6 Z" stroke="{CYAN}" stroke-width="2" fill="none" '
    f'stroke-linejoin="round"/>'
)

ICONS["file"] = svg(
    f'  <path d="M5 3 L15 3 L19 7 L19 21 L5 21 Z" stroke="{CYAN}" stroke-width="2" fill="none"/>\n'
    f'  <polyline points="15,3 15,7 19,7" stroke="{CYAN}" stroke-width="2" fill="none"/>'
)

ICONS["chart"] = svg(
    f'  <line x1="3" y1="21" x2="21" y2="21" stroke="{CYAN}" stroke-width="2"/>\n'
    f'  <rect x="5" y="13" width="3" height="7" fill="{CYAN}"/>\n'
    f'  <rect x="10" y="8" width="3" height="12" fill="{CYAN}"/>\n'
    f'  <rect x="15" y="4" width="3" height="16" fill="{CYAN}"/>'
)

ICONS["search"] = svg(
    f'  <circle cx="10" cy="10" r="7" stroke="{CYAN}" stroke-width="2" fill="none"/>\n'
    f'  <line x1="15.5" y1="15.5" x2="21" y2="21" stroke="{CYAN}" stroke-width="2.5"/>'
)

ICONS["settings"] = svg(
    f'  <circle cx="12" cy="12" r="3" stroke="{CYAN}" stroke-width="2" fill="none"/>\n'
    f'  <path d="M12 2 L13.5 5 L16 4 L17 7 L20 8 L19 11 L22 12 L19 13 L20 16 L17 17 '
    f'L16 20 L13.5 19 L12 22 L10.5 19 L8 20 L7 17 L4 16 L5 13 L2 12 L5 11 L4 8 L7 7 '
    f'L8 4 L10.5 5 Z" stroke="{CYAN}" stroke-width="1.5" fill="none" stroke-linejoin="round"/>'
)

ICONS["tip"] = svg(
    f'  <path d="M9 18 L15 18 M10 21 L14 21 M12 3 A7 7 0 0 1 15 16 L15 18 L9 18 L9 16 '
    f'A7 7 0 0 1 12 3 Z" stroke="{AMBER}" stroke-width="2" fill="none" stroke-linejoin="round"/>'
)

ICONS["clock"] = svg(
    f'  <circle cx="12" cy="12" r="9" stroke="{CYAN}" stroke-width="2" fill="none"/>\n'
    f'  <line x1="12" y1="12" x2="12" y2="7" stroke="{CYAN}" stroke-width="2"/>\n'
    f'  <line x1="12" y1="12" x2="16" y2="14" stroke="{CYAN}" stroke-width="2"/>'
)

ICONS["target"] = svg(
    f'  <circle cx="12" cy="12" r="9" stroke="{CYAN}" stroke-width="2" fill="none"/>\n'
    f'  <circle cx="12" cy="12" r="5" stroke="{CYAN}" stroke-width="2" fill="none"/>\n'
    f'  <circle cx="12" cy="12" r="1.5" fill="{CYAN}"/>'
)

ICONS["link"] = svg(
    f'  <path d="M10 14 A4 4 0 0 1 10 8 L13 8 A4 4 0 0 1 13 16 L11.5 16" stroke="{CYAN}" stroke-width="2" fill="none"/>\n'
    f'  <path d="M14 10 A4 4 0 0 1 14 16 L11 16 A4 4 0 0 1 11 8 L12.5 8" stroke="{CYAN}" stroke-width="2" fill="none"/>'
)

ICONS["play"] = svg(
    f'  <path d="M7 4 L7 20 L20 12 Z" fill="{CYAN}" stroke="{CYAN}" stroke-width="1.5" stroke-linejoin="round"/>'
)

ICONS["stop"] = svg(
    f'  <rect x="5" y="5" width="14" height="14" fill="{CYAN}" stroke="{CYAN}" stroke-width="1.5"/>'
)


def main() -> None:
    here = os.path.dirname(os.path.abspath(__file__))
    for name, body in ICONS.items():
        path = os.path.join(here, f"{name}.svg")
        with open(path, "w", encoding="utf-8") as f:
            f.write(body)
    print(f"Wrote {len(ICONS)} icons in {here}")


if __name__ == "__main__":
    main()
