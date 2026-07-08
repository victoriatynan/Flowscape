"""Render a zoomed-in view of a scenario's junction node for visual
inspection of corner fillets and lane-line connectors."""

import math
import os
import sys

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")

import pygame

from road_editor import RoadRenderer, Camera, CANVAS_WIDTH, CANVAS_HEIGHT
from test_intersections_visual import SCENARIOS, _spoke_network
from check_fillet_direction import EXTRA

OUTPUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "test_output")
os.makedirs(OUTPUT_DIR, exist_ok=True)
ALL = dict(list(SCENARIOS) + list(EXTRA))


def render_zoom(name, zoom=6.0, cx=0.0, cy=0.0):
    net = ALL[name]()
    pygame.init()
    pygame.display.set_mode((CANVAS_WIDTH, CANVAS_HEIGHT))
    font = pygame.font.SysFont("monospace", 13)
    surface = pygame.Surface((CANVAS_WIDTH, CANVAS_HEIGHT))

    camera = Camera()
    camera.zoom = zoom
    s = camera._scale()
    camera.offset_x = cx - (CANVAS_WIDTH / 2.0) / s
    camera.offset_y = cy - (CANVAS_HEIGHT / 2.0) / s

    renderer = RoadRenderer(surface, font, camera)
    renderer.draw(net, None, None, None, False, None, None, None, None,
                   "select_tool", debug=False)
    path = os.path.join(OUTPUT_DIR, f"zoom_{name}.png")
    pygame.image.save(surface, path)
    pygame.quit()
    print(path)


if __name__ == "__main__":
    name = sys.argv[1]
    zoom = float(sys.argv[2]) if len(sys.argv) > 2 else 6.0
    cx = float(sys.argv[3]) if len(sys.argv) > 3 else 0.0
    cy = float(sys.argv[4]) if len(sys.argv) > 4 else 0.0
    render_zoom(name, zoom, cx, cy)
