"""
Generate PLACEHOLDER traffic-light signal-head icons.

Three variants -- one lamp lit per phase state (red/yellow/green), matching
TrafficLightController's TL_STATE_COLORS so the icon and the plain-circle
fallback always agree on color. Source art faces UP (lens toward the top of
the image), so the renderer's generic "sprite" visual layer can rotate it to
face any approach, the same convention the vehicle sprite uses.

These are simple stand-ins, not final art. They live in the sibling
"2d Assets" folder (world-space, rotated sprite -- like the vehicle sprite,
not a fixed UI icon) under the filenames TrafficLightController expects
(trafficlight-<state>.png); dropping finished art at the same filenames
replaces them with no code change.

Run:  python tools/make_placeholder_traffic_light_icons.py
"""

import os
import sys

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
import pygame

# This script lives in Flowscape/tools/; intersection_control.py is a sibling
# of tools/, one level up -- add it to the path so this runs from anywhere.
_PKG_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _PKG_DIR)
from intersection_control import TL_GREEN, TL_YELLOW, TL_ALL_RED, TL_STATE_COLORS

# Source art drawn oversized for crisp downscaling at any in-sim zoom.
W, H = 60, 140
ASSETS_DIR = os.path.join(_PKG_DIR, "2d Assets")

OUTLINE = (25, 25, 25)      # signal-head housing border
HOUSING = (40, 43, 45)      # housing fill
DIM = (55, 45, 45)          # unlit lamp
BEZEL = (12, 12, 12)        # dark ring around each lamp

LAMP_RADIUS = 20
LAMP_GAP = 44                # vertical spacing between lamp centers
# top -> bottom, matching a real signal head's red/yellow/green order.
LAMP_LAYOUT = ((TL_ALL_RED, (W // 2, H // 2 - LAMP_GAP)),
              (TL_YELLOW, (W // 2, H // 2)),
              (TL_GREEN, (W // 2, H // 2 + LAMP_GAP)))


def _make(lit_state):
    surf = pygame.Surface((W, H), pygame.SRCALPHA)
    housing = pygame.Rect(4, 4, W - 8, H - 8)
    pygame.draw.rect(surf, OUTLINE, housing.inflate(6, 6), border_radius=10)
    pygame.draw.rect(surf, HOUSING, housing, border_radius=8)
    for state, (cx, cy) in LAMP_LAYOUT:
        lit = state == lit_state
        pygame.draw.circle(surf, BEZEL, (cx, cy), LAMP_RADIUS + 3)
        if lit:
            color = TL_STATE_COLORS[state]
            glow = pygame.Surface((W, H), pygame.SRCALPHA)
            pygame.draw.circle(glow, (*color, 90), (cx, cy), LAMP_RADIUS + 14)
            surf.blit(glow, (0, 0))
        else:
            color = DIM
        pygame.draw.circle(surf, color, (cx, cy), LAMP_RADIUS)
    return surf


def main():
    pygame.init()
    pygame.display.set_mode((1, 1))
    os.makedirs(ASSETS_DIR, exist_ok=True)
    for state, name in ((TL_GREEN, "trafficlight-green"),
                        (TL_YELLOW, "trafficlight-yellow"),
                        (TL_ALL_RED, "trafficlight-red")):
        surf = _make(state)
        path = os.path.join(ASSETS_DIR, name + ".png")
        pygame.image.save(surf, path)
        print(f"wrote {path}")
    pygame.quit()


if __name__ == "__main__":
    main()
