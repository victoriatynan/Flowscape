"""
Generate PLACEHOLDER undo/redo toolbar icons.

These are simple curved-arrow stand-ins, not final art. They live in the
sibling "2D Assets" folder under the same filenames the toolbar expects
(undo-button.png / redo-button.png), so dropping finished art at those paths
replaces them with no code change.

Run:  python tools/make_placeholder_icons.py
"""

import os
import math

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
import pygame

# Tile is 122x102 in-app; draw at 2x for crisp downscaling.
W, H = 244, 204
# Mirror road_editor's _ICON_DIR: the "2D Assets" folder sits one level ABOVE
# the Flowscape package (this script is in Flowscape/tools/, so go up twice).
_PKG_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ASSETS_DIR = os.path.join(_PKG_DIR, "..", "2D Assets")

OUTLINE = (31, 36, 10)     # dark border, matches the road-art outline tone
FILL = (239, 216, 161)     # cream, matches the lane-marking palette color


def _stroke_arc(surf, cx, cy, r, start_deg, end_deg, width, color):
    """Draw a thick circular-arc stroke as a run of filled dots (pygame's
    draw.arc is too thin/ragged). Angles are standard math degrees (0 = +x,
    counterclockwise), with screen-y flipped so the arc reads naturally."""
    steps = 120
    rad = width // 2
    for i in range(steps + 1):
        t = i / steps
        ang = math.radians(start_deg + (end_deg - start_deg) * t)
        x = cx + r * math.cos(ang)
        y = cy - r * math.sin(ang)
        pygame.draw.circle(surf, color, (int(round(x)), int(round(y))), rad)


def _arrow_head(surf, tip, direction, size, color):
    """Filled triangle arrowhead at `tip`, pointing along unit `direction`."""
    dx, dy = direction
    # Perpendicular for the two base corners.
    px, py = -dy, dx
    base = (tip[0] - dx * size, tip[1] - dy * size)
    p1 = (base[0] + px * size * 0.7, base[1] + py * size * 0.7)
    p2 = (base[0] - px * size * 0.7, base[1] - py * size * 0.7)
    pygame.draw.polygon(surf, color, [tip, p1, p2])


def _make(mirror):
    """Build one arrow icon Surface. mirror=False -> undo (head lower-left),
    mirror=True -> redo (head lower-right)."""
    surf = pygame.Surface((W, H), pygame.SRCALPHA)
    cx, cy, r = W / 2, H / 2 + 6, 66
    body_w = 30

    # Open-bottom horseshoe arc sweeping over the top, tip on the lower-left.
    start_deg, end_deg = -35, 215
    tip_ang = math.radians(end_deg)
    tip = (cx + r * math.cos(tip_ang), cy - r * math.sin(tip_ang))
    # Tangent (direction of travel along increasing angle), screen-space.
    tang = (-math.sin(tip_ang), -math.cos(tip_ang))

    def draw(target):
        # Outline pass (thicker/darker), then cream fill on top -> baked border.
        _stroke_arc(target, cx, cy, r, start_deg, end_deg, body_w + 10, OUTLINE)
        _arrow_head(target, tip, tang, 78, OUTLINE)
        _stroke_arc(target, cx, cy, r, start_deg, end_deg, body_w, FILL)
        _arrow_head(target, tip, tang, 64, FILL)

    draw(surf)
    if mirror:
        surf = pygame.transform.flip(surf, True, False)
    return surf


def main():
    pygame.init()
    pygame.display.set_mode((1, 1))
    os.makedirs(ASSETS_DIR, exist_ok=True)
    for name, mirror in (("undo-button", False), ("redo-button", True)):
        surf = _make(mirror)
        path = os.path.join(ASSETS_DIR, name + ".png")
        pygame.image.save(surf, path)
        print(f"wrote {path}")
    pygame.quit()


if __name__ == "__main__":
    main()
