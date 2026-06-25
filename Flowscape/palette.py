"""
Flowscape color palette, "fantasy-24".

PROJECT RULE (from now on): every color drawn anywhere in Flowscape MUST be
one of the 24 entries in PALETTE below. Do NOT hard-code arbitrary RGB values
in new code; pick the nearest palette entry (see `nearest()`), or extend the
palette deliberately. New UI, new graphics, new overlays: palette only.

Source: fantasy-24 (1).hex (24 colors, in order).

NOTE: some pre-existing COLOR_* constants (e.g. in road_editor.py) predate this
rule and are not yet palette-exact; they should be migrated to PALETTE.
"""


def _hex(h):
    """'rrggbb' hex string -> (r, g, b) tuple."""
    return (int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16))


# fantasy-24, in source order (index 0 = palette color 1).
_HEXES = [
    "1f240a", "39571c", "a58c27", "efac28", "efd8a1", "ab5c1c",
    "183f39", "ef692f", "efb775", "a56243", "773421", "724113",
    "2a1d0d", "392a1c", "684c3c", "927e6a", "276468", "ef3a0c",
    "45230d", "3c9f9c", "9b1a0a", "36170c", "550f0a", "300f0a",
]

PALETTE = [_hex(h) for h in _HEXES]          # the core 24
BY_HEX = {h: _hex(h) for h in _HEXES}        # "rrggbb" -> (r, g, b)

# Deliberate additions beyond the core 24, kept in-family (warm, desaturated)
# so they still read as fantasy-24. Road-surface asphalt grays live here.
EXTRA_HEXES = ["655e56", "4e4843"]
EXTRAS = {h: _hex(h) for h in EXTRA_HEXES}

_ALL = {**BY_HEX, **EXTRAS}


def color(hex_str):
    """Palette color by hex string (core 24 or documented EXTRAS); raises if
    it's not in either, so a typo can't silently introduce an off-palette
    color."""
    key = hex_str.lower().lstrip("#")
    if key not in _ALL:
        raise ValueError(f"{hex_str!r} is not in the fantasy-24 palette (or EXTRAS)")
    return _ALL[key]


def nearest(rgb):
    """Closest palette color to an arbitrary RGB (squared distance); handy
    for migrating an existing ad-hoc color onto the palette."""
    r, g, b = rgb[:3]
    return min(PALETTE, key=lambda c: (c[0] - r) ** 2 + (c[1] - g) ** 2 + (c[2] - b) ** 2)
