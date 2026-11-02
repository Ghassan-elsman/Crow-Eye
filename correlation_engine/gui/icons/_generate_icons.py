"""One-shot generator for the Crow-Eye-styled SVG icon set.

Run once to produce the .svg files in this directory. Idempotent — safe
to re-run if you tweak the shapes; it overwrites in place. Not imported by
the loader (which just reads the .svg files directly).

Style: 24x24 viewBox, 2px stroke, square caps, transparent background.
Cyan #00FFFF for neutral icons; status colors (green/amber/red/grey) for
the status-specific icons; amber for star + tip glyph; otherwise cyan.
"""

from __future__ import annotations

import os


def svg(body: str, viewbox: str = "0 0 24 24", rounded: bool = False) -> str:
    cap, join = ("round", "round") if rounded else ("square", "miter")
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="{viewbox}" '
        f'fill="none" stroke-linecap="{cap}" stroke-linejoin="{join}">\n'
        f'{body}\n'
        f'</svg>\n'
    )


# Crow-Eye palette tokens (mirrors styles.Colors).
CYAN = "#00FFFF"
GREEN = "#10B981"
AMBER = "#F59E0B"
RED = "#EF4444"
GREY = "#94A3B8"
PURPLE = "#9C27B0"  # semantic-annotation accent (matches Semantic column text)
DARK_FG = "#0F172A"  # dark stamp inside filled-status shapes

# Result-tree hierarchy palette — each level icon matches its row text color.
IDENTITY_BLUE = "#2196F3"
SUB_ORANGE = "#FF9800"
ANCHOR_AMBER = "#FFC107"
EVIDENCE_GREEN = "#4CAF50"
GUIDE_SLATE = "#475569"  # tree relation guide lines
SUBARROW_SLATE = "#64748B"  # subordinate-metric corner arrow (matches its label text)


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
# NOTE: add/link/stop were hand-tuned after the first generation (rounded
# caps, refined shapes). Their specs below match the on-disk SVGs exactly —
# keep them in sync so a regen never clobbers the tuned versions.
ICONS["add"] = svg(
    f'  <circle cx="12" cy="12" r="9" stroke="{CYAN}" stroke-width="2" fill="none"/>\n'
    f'  <line x1="12" y1="7.5" x2="12" y2="16.5" stroke="{CYAN}" stroke-width="2.5"/>\n'
    f'  <line x1="7.5" y1="12" x2="16.5" y2="12" stroke="{CYAN}" stroke-width="2.5"/>',
    rounded=True,
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

# Outlined star (line-icon house style, NOT a solid emoji-like fill) — "default"/
# "favorite" marker. Amber accent kept; hollow so it reads as an icon, not an emoji.
ICONS["star"] = svg(
    f'  <path d="M12 2.6 L14.7 8.6 L21.3 9.3 L16.4 13.9 L17.8 20.4 L12 17.1 '
    f'L6.2 20.4 L7.6 13.9 L2.7 9.3 L9.3 8.6 Z" '
    f'fill="none" stroke="{AMBER}" stroke-width="2"/>',
    rounded=True,
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


# Decoration (12)
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
    f'  <path d="M10.5 13.5 L13.5 10.5" stroke="{CYAN}" stroke-width="2"/>\n'
    f'  <path d="M9 15 L7 17 A3.5 3.5 0 0 1 2 12 L4 10 A3.5 3.5 0 0 1 9 10 L10 11" stroke="{CYAN}" stroke-width="2"/>\n'
    f'  <path d="M15 9 L17 7 A3.5 3.5 0 0 1 22 12 L20 14 A3.5 3.5 0 0 1 15 14 L14 13" stroke="{CYAN}" stroke-width="2"/>',
    rounded=True,
)

ICONS["play"] = svg(
    f'  <path d="M7 4 L7 20 L20 12 Z" fill="{CYAN}" stroke="{CYAN}" stroke-width="1.5" stroke-linejoin="round"/>'
)

ICONS["stop"] = svg(
    f'  <rect x="5" y="5" width="14" height="14" rx="2.5" fill="{CYAN}" stroke="{CYAN}" stroke-width="1.5"/>',
    rounded=True,
)

# Down-then-right corner arrow (the "↳" glyph) — marks a subordinate metric
# nested under the value above it. Slate to match its small gray label text.
ICONS["subarrow"] = svg(
    f'  <path d="M8 5 L8 13 L16 13" stroke="{SUBARROW_SLATE}" stroke-width="2" fill="none"/>\n'
    f'  <path d="M13 10 L16.5 13 L13 16" stroke="{SUBARROW_SLATE}" stroke-width="2" fill="none"/>',
    rounded=True,
)

# Lightning bolt — badges advanced wings ("Identity engine only").
# Amber to match the other attention-drawing icons (star/tip/warning).
# Outlined lightning bolt (line-icon house style, NOT a solid emoji-like fill) —
# "advanced wing" / Identity-engine badge. Amber accent kept; hollow outline.
ICONS["bolt"] = svg(
    f'  <path d="M13 2 L5 13 L11 13 L9 22 L19 9 L13 9 Z" fill="none" '
    f'stroke="{AMBER}" stroke-width="2"/>',
    rounded=True,
)

# Label tag with hole — marks rows carrying semantic annotations.
# Purple to match the Semantic column's text color (#9C27B0).
ICONS["tag"] = svg(
    f'  <path d="M3 3 L12 3 L21 12 L12 21 L3 12 Z" stroke="{PURPLE}" '
    f'stroke-width="2" fill="none" stroke-linejoin="round"/>\n'
    f'  <circle cx="8.5" cy="8.5" r="1.8" fill="{PURPLE}"/>'
)


# --------------------------------------------------------------------- #
# Result-tree hierarchy icons — one dedicated glyph per level, colored to
# match that level's row text. Identity = WHO/WHAT acted (fingerprint),
# Sub-identity = WHICH variant/version (branch to a child node), Anchor =
# WHEN evidence co-occurred (pin moored to a timeline node), Evidence =
# WHAT proves it (record under a magnifier).
# --------------------------------------------------------------------- #

ICONS["identity"] = svg(
    # Fingerprint whorl: three nested arcs with ridge tails + side ridges
    f'  <path d="M4.5 13 A7.5 7.5 0 0 1 19.5 13" stroke="{IDENTITY_BLUE}" stroke-width="1.8" fill="none"/>\n'
    f'  <path d="M7.5 13 A4.5 4.5 0 0 1 16.5 13 L16.5 18.5" stroke="{IDENTITY_BLUE}" stroke-width="1.8" fill="none"/>\n'
    f'  <path d="M10.5 13 A1.5 1.5 0 0 1 13.5 13 L13.5 20.5" stroke="{IDENTITY_BLUE}" stroke-width="1.8" fill="none"/>\n'
    f'  <line x1="10.5" y1="16" x2="10.5" y2="20.5" stroke="{IDENTITY_BLUE}" stroke-width="1.8"/>\n'
    f'  <line x1="7.5" y1="16.5" x2="7.5" y2="19" stroke="{IDENTITY_BLUE}" stroke-width="1.8"/>\n'
    f'  <line x1="19.5" y1="16" x2="19.5" y2="18" stroke="{IDENTITY_BLUE}" stroke-width="1.8"/>',
    rounded=True,
)

ICONS["sub_identity"] = svg(
    # Corner branch forking off the parent above into a small variant node
    # (circle with an inner arc echoing the fingerprint)
    f'  <path d="M6 3 L6 12 A2.5 2.5 0 0 0 8.5 14.5 L11 14.5" stroke="{SUB_ORANGE}" stroke-width="2" fill="none"/>\n'
    f'  <circle cx="16.5" cy="14.5" r="4.2" stroke="{SUB_ORANGE}" stroke-width="1.8" fill="none"/>\n'
    f'  <path d="M14.6 15.2 A2 2 0 0 1 18.4 15.2" stroke="{SUB_ORANGE}" stroke-width="1.5" fill="none"/>\n'
    f'  <circle cx="16.5" cy="17.2" r="0.9" fill="{SUB_ORANGE}"/>',
    rounded=True,
)

ICONS["anchor"] = svg(
    # Marker pin moored to a timeline — the fixed point in time a cluster of
    # evidence records is anchored to (WHEN evidence co-occurred).
    f'  <path d="M12 3.4 C8.4 3.4 5.5 6.3 5.5 9.9 C5.5 14.1 12 18.7 12 18.7 '
    f'C12 18.7 18.5 14.1 18.5 9.9 C18.5 6.3 15.6 3.4 12 3.4 Z" '
    f'stroke="{ANCHOR_AMBER}" stroke-width="2" fill="none"/>\n'
    f'  <circle cx="12" cy="9.8" r="2" fill="{ANCHOR_AMBER}" stroke="none"/>\n'
    f'  <line x1="4.5" y1="20.4" x2="19.5" y2="20.4" stroke="{ANCHOR_AMBER}" stroke-width="2"/>\n'
    f'  <circle cx="12" cy="20.4" r="1.5" fill="{ANCHOR_AMBER}" stroke="none"/>',
    rounded=True,
)

ICONS["evidence"] = svg(
    # Artifact record (document with folded corner + text lines) under a
    # magnifying glass — the raw evidence an examiner inspects
    f'  <path d="M14 3 L7 3 A1 1 0 0 0 6 4 L6 20 A1 1 0 0 0 7 21 L10.5 21" stroke="{EVIDENCE_GREEN}" stroke-width="1.8" fill="none"/>\n'
    f'  <path d="M14 3 L18 7 L18 10.5" stroke="{EVIDENCE_GREEN}" stroke-width="1.8" fill="none"/>\n'
    f'  <path d="M14 3 L14 7 L18 7" stroke="{EVIDENCE_GREEN}" stroke-width="1.4" fill="none"/>\n'
    f'  <line x1="9" y1="9" x2="13" y2="9" stroke="{EVIDENCE_GREEN}" stroke-width="1.4"/>\n'
    f'  <line x1="9" y1="12" x2="11.5" y2="12" stroke="{EVIDENCE_GREEN}" stroke-width="1.4"/>\n'
    f'  <circle cx="15.5" cy="15.5" r="3.9" stroke="{EVIDENCE_GREEN}" stroke-width="1.9" fill="none"/>\n'
    f'  <line x1="18.4" y1="18.4" x2="21.5" y2="21.5" stroke="{EVIDENCE_GREEN}" stroke-width="2.2"/>',
    rounded=True,
)


# --------------------------------------------------------------------- #
# Tree relation guides + expand state indicators (referenced by the result
# viewers' QTreeWidget::branch stylesheet rules, not via QIcon).
# Guides keep square caps so segments join seamlessly across cells.
# --------------------------------------------------------------------- #

ICONS["branch_vline"] = svg(
    f'  <line x1="12" y1="0" x2="12" y2="24" stroke="{GUIDE_SLATE}" stroke-width="1.4"/>'
)

ICONS["branch_more"] = svg(
    f'  <line x1="12" y1="0" x2="12" y2="24" stroke="{GUIDE_SLATE}" stroke-width="1.4"/>\n'
    f'  <line x1="12" y1="12" x2="24" y2="12" stroke="{GUIDE_SLATE}" stroke-width="1.4"/>'
)

ICONS["branch_end"] = svg(
    f'  <path d="M12 0 L12 12 L24 12" stroke="{GUIDE_SLATE}" stroke-width="1.4" fill="none"/>'
)

ICONS["branch_closed"] = svg(
    # Right chevron: this row HAS children, currently collapsed
    f'  <path d="M9.5 6.5 L15.5 12 L9.5 17.5" stroke="{CYAN}" stroke-width="2.2" fill="none"/>',
    rounded=True,
)

ICONS["branch_open"] = svg(
    # Down chevron: expanded — the rows below belong to this one
    f'  <path d="M6.5 9.5 L12 15 L17.5 9.5" stroke="{CYAN}" stroke-width="2.2" fill="none"/>',
    rounded=True,
)

# History / restore-previous: counterclockwise circular arrow around clock
# hands — "load the LAST results" (distinct from download = export to disk).
ICONS["history"] = svg(
    f'  <path d="M6.2 6.2 A8 8 0 1 0 12 4" stroke="{CYAN}" stroke-width="2" fill="none"/>\n'
    f'  <path d="M6.2 2.8 L6.2 6.4 L9.8 6.4" stroke="{CYAN}" stroke-width="2" fill="none"/>\n'
    f'  <line x1="12" y1="8" x2="12" y2="12.5" stroke="{CYAN}" stroke-width="2"/>\n'
    f'  <line x1="12" y1="12.5" x2="15.2" y2="14.3" stroke="{CYAN}" stroke-width="2"/>',
    rounded=True,
)


# --------------------------------------------------------------------- #
# Additional decoration icons (added 2026-07-18 for the emoji→icon sweep of
# the PyQt ui/ dialogs + Artifacts_Collectors GUIs + Eye Python UI).
# Neutral cyan stroke, same 24x24 / 2px house style.
# --------------------------------------------------------------------- #

# Export / send up-and-out (distinct from download = arrow into tray).
ICONS["upload"] = svg(
    f'  <path d="M4 15 v3 a1 1 0 0 0 1 1 h14 a1 1 0 0 0 1-1 v-3" stroke="{CYAN}" stroke-width="2" fill="none"/>\n'
    f'  <line x1="12" y1="4" x2="12" y2="15" stroke="{CYAN}" stroke-width="2"/>\n'
    f'  <path d="M8 8 L12 4 L16 8" stroke="{CYAN}" stroke-width="2" fill="none"/>',
    rounded=True,
)

# Hourglass — busy / in-progress.
ICONS["hourglass"] = svg(
    f'  <line x1="7" y1="3" x2="17" y2="3" stroke="{CYAN}" stroke-width="2"/>\n'
    f'  <line x1="7" y1="21" x2="17" y2="21" stroke="{CYAN}" stroke-width="2"/>\n'
    f'  <path d="M8 3 v3 l4 5 4-5 v-3" stroke="{CYAN}" stroke-width="2" fill="none"/>\n'
    f'  <path d="M8 21 v-3 l4-5 4 5 v3" stroke="{CYAN}" stroke-width="2" fill="none"/>',
    rounded=True,
)

# Lock — admin-required / secure.
ICONS["lock"] = svg(
    f'  <rect x="5" y="11" width="14" height="9" rx="2" stroke="{CYAN}" stroke-width="2" fill="none"/>\n'
    f'  <path d="M8 11 V8 a4 4 0 0 1 8 0 v3" stroke="{CYAN}" stroke-width="2" fill="none"/>\n'
    f'  <circle cx="12" cy="15.5" r="1.3" fill="{CYAN}"/>',
    rounded=True,
)

# Disk — a forensic image / optical disc.
ICONS["disk"] = svg(
    f'  <circle cx="12" cy="12" r="9" stroke="{CYAN}" stroke-width="2" fill="none"/>\n'
    f'  <circle cx="12" cy="12" r="2.4" stroke="{CYAN}" stroke-width="2" fill="none"/>',
)

# Calendar — created/opened dates.
ICONS["calendar"] = svg(
    f'  <rect x="4" y="5" width="16" height="15" rx="2" stroke="{CYAN}" stroke-width="2" fill="none"/>\n'
    f'  <line x1="4" y1="9.5" x2="20" y2="9.5" stroke="{CYAN}" stroke-width="2"/>\n'
    f'  <line x1="8" y1="3" x2="8" y2="7" stroke="{CYAN}" stroke-width="2"/>\n'
    f'  <line x1="16" y1="3" x2="16" y2="7" stroke="{CYAN}" stroke-width="2"/>',
    rounded=True,
)

# Text — font / character settings ("T").
ICONS["text"] = svg(
    f'  <line x1="5" y1="6" x2="19" y2="6" stroke="{CYAN}" stroke-width="2"/>\n'
    f'  <line x1="12" y1="6" x2="12" y2="18" stroke="{CYAN}" stroke-width="2"/>\n'
    f'  <line x1="9" y1="18" x2="15" y2="18" stroke="{CYAN}" stroke-width="2"/>',
    rounded=True,
)

# Crow — the Crow-Eye brand mark (a stylized eye).
ICONS["crow"] = svg(
    f'  <path d="M2 12 C5 6.5 9 4 12 4 C15 4 19 6.5 22 12 C19 17.5 15 20 12 20 C9 20 5 17.5 2 12 Z" '
    f'stroke="{CYAN}" stroke-width="2" fill="none"/>\n'
    f'  <circle cx="12" cy="12" r="3.2" stroke="{CYAN}" stroke-width="2" fill="none"/>',
    rounded=True,
)

# Clipboard — list/registry style records.
ICONS["clipboard"] = svg(
    f'  <rect x="6" y="4" width="12" height="17" rx="2" stroke="{CYAN}" stroke-width="2" fill="none"/>\n'
    f'  <rect x="9" y="2.5" width="6" height="3" rx="1" stroke="{CYAN}" stroke-width="2" fill="none"/>\n'
    f'  <line x1="9" y1="10" x2="15" y2="10" stroke="{CYAN}" stroke-width="2"/>\n'
    f'  <line x1="9" y1="13.5" x2="15" y2="13.5" stroke="{CYAN}" stroke-width="2"/>\n'
    f'  <line x1="9" y1="17" x2="13" y2="17" stroke="{CYAN}" stroke-width="2"/>',
    rounded=True,
)

# Package — collect / bundle artifacts.
ICONS["package"] = svg(
    f'  <path d="M12 3 L21 7.5 V16.5 L12 21 L3 16.5 V7.5 Z" stroke="{CYAN}" stroke-width="2" fill="none"/>\n'
    f'  <path d="M3 7.5 L12 12 L21 7.5" stroke="{CYAN}" stroke-width="2" fill="none"/>\n'
    f'  <line x1="12" y1="12" x2="12" y2="21" stroke="{CYAN}" stroke-width="2"/>',
    rounded=True,
)


# --------------------------------------------------------------------- #
# Behaviour Results view (correlation_engine/gui/behaviour_results_view.py,
# Phase 4 of the Behavioural Engine). Shapes from the chosen designs in the
# 2026-10 behaviour-icons sheet: the tab icon is "Activity pulse" (a head over
# a pulse line); the tree goes person -> Behaviour Wing -> hit. A hit's icon is
# the Wing's time range as a bracket over its steps: joined by an arrow when
# the steps happen in order, loose dots when any order counts. Person and Wing
# keep fixed colours, as the Identity view's levels do; the two hit icons are
# drawn in the UBA "routine" grey and tinted to the hit's severity at run time.
# --------------------------------------------------------------------- #
PULSE_SKY = "#38BDF8"     # the Behaviour Results tab and its Wing rows
PERSON_BLUE = "#60A5FA"   # a person (by SID)
HIT_DIM = "#8C95AB"       # UBA "routine"; re-tinted per severity in the view

ICONS["behaviour"] = svg(
    f'  <circle cx="12" cy="5" r="3" stroke="{PULSE_SKY}" stroke-width="2" fill="none"/>\n'
    f'  <polyline points="2 16 7 16 9.5 11 13 20 15.5 14 22 14" stroke="{PULSE_SKY}" '
    f'stroke-width="2" fill="none"/>',
    rounded=True,
)

ICONS["person"] = svg(
    f'  <circle cx="12" cy="8" r="4" stroke="{PERSON_BLUE}" stroke-width="2" fill="none"/>\n'
    f'  <path d="M4 21v-1a6 6 0 0 1 6-6h4a6 6 0 0 1 6 6v1" stroke="{PERSON_BLUE}" '
    f'stroke-width="2" fill="none"/>',
    rounded=True,
)

ICONS["behaviour_wing"] = svg(
    f'  <path d="M3 20C5 11 11 5 21 4c-1 4-3.5 6.5-7 7.5 2 .3 3 1.3 3 2.5-3 2.5-7.5 3.5-11 3" '
    f'stroke="{PULSE_SKY}" stroke-width="2" fill="none"/>\n'
    f'  <path d="M8 15l5-4" stroke="{PULSE_SKY}" stroke-width="2" fill="none"/>',
    rounded=True,
)

ICONS["hit_ordered"] = svg(
    f'  <path d="M3 7V5h18v2" stroke="{HIT_DIM}" stroke-width="2" fill="none"/>\n'
    f'  <circle cx="5" cy="13" r="2" stroke="{HIT_DIM}" stroke-width="2" fill="none"/>\n'
    f'  <circle cx="12" cy="13" r="2" stroke="{HIT_DIM}" stroke-width="2" fill="none"/>\n'
    f'  <circle cx="19" cy="13" r="2" stroke="{HIT_DIM}" stroke-width="2" fill="none"/>\n'
    f'  <path d="M7 13h3M14 13h3" stroke="{HIT_DIM}" stroke-width="2" fill="none"/>\n'
    f'  <path d="M15.5 11.4l1.6 1.6-1.6 1.6" stroke="{HIT_DIM}" stroke-width="2" fill="none"/>',
    rounded=True,
)

ICONS["hit_any"] = svg(
    f'  <path d="M3 7V5h18v2" stroke="{HIT_DIM}" stroke-width="2" fill="none"/>\n'
    f'  <circle cx="5" cy="13" r="2" stroke="{HIT_DIM}" stroke-width="2" fill="none"/>\n'
    f'  <circle cx="12" cy="17" r="2" stroke="{HIT_DIM}" stroke-width="2" fill="none"/>\n'
    f'  <circle cx="19" cy="12" r="2" stroke="{HIT_DIM}" stroke-width="2" fill="none"/>',
    rounded=True,
)


# --------------------------------------------------------------------- #
# The three correlation engines. Each draws how its engine groups evidence,
# in the style of the artifact icons on the parser buttons (one 1.8 stroke,
# round ends, no fill but the record dots). A Wing is shown as the brand's
# Wing art (wing.png, not generated here) beside its engine's icon
# (crow_eye_icons.wing_icon); the engine icon carries the engine's colour.
#   Time-Window: a clock between range brackets - one fixed window of time -
#                with the records from different feathers it caught.
#   Identity:    records of different kinds (one shape per feather) drawn into
#                one identity node; no time axis, time does not decide it.
#   Behavioural: one person, and under them the steps, in order.
# --------------------------------------------------------------------- #
TIME_GREEN = "#34D399"
IDENTITY_BLUE_ENGINE = IDENTITY_BLUE
BEHAVIOUR_VIOLET = "#A78BFA"


def _engine(colour: str, body: str) -> str:
    return svg(f'  <g stroke="{colour}" stroke-width="1.8" fill="none">\n{body}\n  </g>', rounded=True)


def _dot(x, y, r, colour):
    return f'    <circle cx="{x}" cy="{y}" r="{r}" fill="{colour}" stroke="none"/>'


ICONS["engine_time"] = _engine(TIME_GREEN, "\n".join([
    '    <path d="M6.5 4H5a1.5 1.5 0 0 0 -1.5 1.5V18.5A1.5 1.5 0 0 0 5 20H6.5'
    'M17.5 4H19a1.5 1.5 0 0 1 1.5 1.5V18.5A1.5 1.5 0 0 1 19 20H17.5"/>',
    '    <circle cx="12" cy="10.5" r="4.2"/>',
    '    <path d="M12 8.3V10.5L13.6 11.6"/>',
    _dot(8.6, 17.2, 1.2, TIME_GREEN), _dot(12, 17.2, 1.2, TIME_GREEN), _dot(15.4, 17.2, 1.2, TIME_GREEN),
]))

ICONS["engine_identity"] = _engine(IDENTITY_BLUE_ENGINE, "\n".join([
    '    <circle cx="16" cy="12" r="4.5"/>',
    _dot(16, 12, 1.6, IDENTITY_BLUE_ENGINE),
    '    <path d="M6.6 6.7L10.8 9.05M7 12H10M6.6 17.3L10.8 14.95"/>',
    _dot(4.4, 5.6, 1.6, IDENTITY_BLUE_ENGINE),
    f'    <rect x="3" y="10.6" width="2.8" height="2.8" rx=".6" fill="{IDENTITY_BLUE_ENGINE}" stroke="none"/>',
    f'    <path d="M4.4 16.6L5.9 18.4 4.4 20.2 2.9 18.4Z" fill="{IDENTITY_BLUE_ENGINE}" stroke="none"/>',
]))

ICONS["engine_behaviour"] = _engine(BEHAVIOUR_VIOLET, "\n".join([
    '    <circle cx="12" cy="6" r="2.5"/>',
    '    <path d="M7.5 13C7.5 10.5 9.5 9 12 9S16.5 10.5 16.5 13"/>',
    _dot(4.5, 18.5, 1.5, BEHAVIOUR_VIOLET), _dot(12, 18.5, 1.5, BEHAVIOUR_VIOLET), _dot(19.5, 18.5, 1.5, BEHAVIOUR_VIOLET),
    '    <path d="M6.8 18.5H9.4M8.2 17.2L9.5 18.5 8.2 19.8M14.3 18.5H16.9M15.7 17.2L17 18.5 15.7 19.8"/>',
]))



# --------------------------------------------------------------------- #
# The Wing and the Feather are not generated: since 2026-10-30 (Ghassan) they
# are the brand's art exactly as the User Guide draws them - the indigo
# layered wing and the cyan quill, wing.png / feather.png (128 px) and their
# @2x (256 px), the site's icon-wing / icon-feather files byte for byte, plus
# the rich-text sizes _scale_brand_art.py renders from the SVG masters in
# brand/ (<name>.svg, and <name>-small.svg for 256 px and below). Redrawn
# 2026-10-30; the masters stay out of this folder's top level, whose SVGs
# are the generated set ICON_NAMES is tested against.
# --------------------------------------------------------------------- #


def main() -> None:
    here = os.path.dirname(os.path.abspath(__file__))
    for name, body in ICONS.items():
        path = os.path.join(here, f"{name}.svg")
        with open(path, "w", encoding="utf-8", newline="\n") as f:
            f.write(body)
    print(f"Wrote {len(ICONS)} icons in {here}")


if __name__ == "__main__":
    main()
