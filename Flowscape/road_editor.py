"""
Interactive Road Editor (Editor UI + Interaction System)

Architecture:
  - road_geometry.py : Road/Node/Zone data + pure geometry generation (UNCHANGED)
  - map_data.py      : JSON save/load (UNCHANGED format)
  - RoadNetwork (this file) : holds nodes/roads/zones, world-space data
  - Camera (this file)      : pan/zoom + world<->screen conversion
  - RoadRenderer (this file): draws everything through the camera transform
  - Toolbar (this file)     : sidebar tool buttons (UI shell)
  - InputController (this file): central input router -> active tool behavior
  - main loop : ties it together

Tool State System:
  InputController.current_tool is one of TOOL_SELECT, TOOL_ROAD, TOOL_ZONE
  (only one active at a time; TOOL_ZONE is a placeholder for Phase 3.1).
  All mouse/keyboard input is routed through InputController.handle_event(),
  which dispatches to tool-specific behavior:
    - TOOL_SELECT: select/drag nodes, select roads, edit control points
    - TOOL_ROAD:   click-to-place nodes and chain roads (Phase 1 workflow)

Camera System:
  All node/road/zone coordinates remain in WORLD space (feet), exactly as
  before -- geometry generation is untouched. Camera.world_to_screen() /
  screen_to_world() convert between world space and canvas pixels for
  rendering and for hit-testing mouse input. Mouse-wheel zooms around the
  cursor; right-click-drag pans.

Road Preview System (TOOL_ROAD):
  A `pending_start_node` holds the first clicked node (existing or newly
  created). While the mouse moves, a temporary Road with is_preview=True is
  built each frame from pending_start_node -> current mouse position (world
  space), using the SAME compute_road_geometry() function as committed
  roads. The second click commits a real Node + Road into the network.

Curve Offset Storage:
  Each Road has a 2D `curve_offset` (world-space vector from the start->end
  midpoint to the bezier control point). In TOOL_SELECT, dragging the red
  control-point handle sets this directly (free-form curve editing). Mouse
  wheel nudges it along the perpendicular to start->end when previewing or
  when a road is selected (and not zooming).

Controls:
  TOOL_SELECT (default):
    - Hover a node: highlight
    - Click a node: select it (green ring); drag to move (roads update live)
    - Click a road: select it (orange); drag the red control point to bend it
    - Click empty space: deselect
  TOOL_ROAD:
    - Click empty space: place start node, preview road to cursor
    - Click again (node or empty space): commit road
    - Esc: cancel placement
    - Scroll while previewing/road selected: nudge curvature
  Camera (any tool):
    - Mouse wheel (when not adjusting curvature): zoom around cursor
    - Right-click + drag: pan
  General:
    - 1 / 2: switch tool (Select / Road), or click sidebar buttons
    - D: toggle debug overlay
    - S: save map to JSON, L: load map from JSON
"""

import math
import os
import sys
import pygame

from road_geometry import (Node, Road, Zone, compute_road_geometry, _perpendicular,
                            compute_control_point, compute_road_edges, compute_road_polygon)
from map_data import save_map, load_map
from buildings import Building
from road_style import (get_road_style, marking_segments, decal_transform, MARKING_NONE,
                         get_road_profile, profile_markings, profile_shoulder_regions,
                         profile_median_region, offset_polyline, EDGE_LINE_PRESETS,
                         SHOULDER_NONE, SHOULDER_SIDEWALK, SHOULDER_COLORS)
from snap_mode import (SnapModeController, SnapModePanel, SNAP_AUTO, SNAP_STRAIGHT,
                        SNAP_CURVE, SNAP_MODE_LABELS)
from lane_graph import build_lane_graph, lane_graph_visual_layers
from traffic_sim import TrafficSimulation


NODE_RADIUS = 8
NODE_HIT_RADIUS = 12
CURVATURE_STEP = 8.0

MAP_SAVE_PATH = "map_save.json"

CANVAS_WIDTH = 1024
CANVAS_HEIGHT = 768
SIDEBAR_WIDTH = 280
MIN_WINDOW_WIDTH = SIDEBAR_WIDTH + 320
MIN_WINDOW_HEIGHT = 240

ZOOM_MIN = 0.2
ZOOM_MAX = 5.0
ZOOM_STEP = 1.1

# UI-only reference scale for the map scale bar: at camera.zoom == 1.0,
# one world foot is rendered as WORLD_SCALE screen pixels. (World/geometry
# data is unaffected -- this only feeds the scale-bar label/length.)
WORLD_SCALE = 3

SCALE_BAR_VALUES_FT = [10, 20, 50, 100, 200, 500]
SCALE_BAR_MAX_PX = 160
SCALE_BAR_MARGIN = 16
COLOR_SCALE_BAR = (230, 230, 230)
COLOR_SCALE_BAR_BG = (0, 0, 0)

TOOL_SELECT = "select_tool"
TOOL_NODE = "node_tool"
TOOL_ROAD = "new_road_tool"
TOOL_ZONE = "zone_tool"

ACTION_SAVE = "action_save"
ACTION_LOAD = "action_load"

TOOL_LABELS = {
    TOOL_SELECT: "Select Tool",
    TOOL_NODE: "Node Tool",
    TOOL_ROAD: "New Road Tool",
    TOOL_ZONE: "Zone Tool",
}

# UI-only tooltip content, keyed by toolbar item id (tool or action). The UI
# reads this table to render hover tooltips -- it contains no engine logic.
TOOLTIPS = {
    TOOL_SELECT: ("Select Tool", "Select and edit nodes/roads",
                   "Click to select, drag to move/bend"),
    TOOL_NODE: ("Node Tool", "Place standalone nodes",
                "Click anywhere to place a node"),
    TOOL_ROAD: ("New Road Tool", "Connect two existing nodes",
                "Click node A, then node B"),
    TOOL_ZONE: ("Zone Tool", "Draw zone polygons", "Coming soon"),
    ACTION_SAVE: ("Save Map", "Write the map to disk", f"Saves to {MAP_SAVE_PATH}"),
    ACTION_LOAD: ("Load Map", "Reload the map from disk", f"Loads from {MAP_SAVE_PATH}"),
}

BUTTON_PRESS_DURATION_MS = 120

COLOR_BG = (30, 32, 36)
COLOR_SIDEBAR_BG = (24, 25, 28)
COLOR_SIDEBAR_TEXT = (210, 210, 210)
COLOR_SIDEBAR_HEADER = (255, 210, 90)
COLOR_BUTTON = (50, 53, 60)
COLOR_BUTTON_ACTIVE = (80, 130, 200)
COLOR_BUTTON_HOVER = (68, 72, 82)
COLOR_BUTTON_PRESSED = (100, 150, 220)
COLOR_BUTTON_DISABLED = (40, 42, 46)
COLOR_TOOLTIP_BG = (45, 48, 54)
COLOR_TOOLTIP_BORDER = (90, 130, 180)
COLOR_BUTTON_TEXT = (230, 230, 230)
COLOR_BUTTON_TEXT_DISABLED = (110, 110, 110)
COLOR_NODE = (220, 220, 220)
COLOR_NODE_HOVER = (255, 255, 150)
COLOR_NODE_SELECTED = (60, 230, 140)
COLOR_NODE_PREVIEW = (255, 255, 255)
PREVIEW_NODE_ALPHA = 90  # ~0.35 of 255
PREVIEW_NODE_ALPHA_SNAPPED = 220  # ~0.85 of 255, locked to a node
SNAP_RADIUS = 20  # world units
NODE_DRAG_THRESHOLD = 4
COLOR_ROAD = (90, 200, 255)
COLOR_ROAD_SELECTED = (255, 140, 0)
COLOR_ROAD_PREVIEW = (255, 210, 90)
COLOR_DEBUG_TEXT = (255, 255, 255)
CONTROL_POINT_RADIUS = 7
CONTROL_POINT_HIT_RADIUS = 10
COLOR_CONTROL_POINT = (255, 100, 100)
COLOR_GUIDE_LINE = (255, 255, 255)
COLOR_SAMPLE_POINT = (120, 255, 120)
COLOR_ROAD_SURFACE = (70, 70, 80)
COLOR_ROAD_SURFACE_SELECTED = (110, 80, 50)
COLOR_CENTERLINE_DEBUG = (90, 200, 255)
COLOR_LEFT_EDGE = (255, 80, 80)
COLOR_RIGHT_EDGE = (80, 120, 255)
COLOR_CURB = (60, 60, 60)

ZONE_COLORS = {
    "Residential": (90, 200, 100),
    "Commercial": (90, 140, 220),
    "Industrial": (220, 180, 90),
}
ZONE_DEFAULT_COLOR = (160, 160, 160)
ZONE_ALPHA = 80


class RoadNetwork:
    """Owns committed nodes, roads and zones in WORLD space. No rendering, no input handling."""

    def __init__(self):
        self.nodes = {}
        self.roads = {}
        self.zones = {}
        self.buildings = {}
        self._next_node_id = 1
        self._next_road_id = 1
        self._next_zone_id = 1
        self._next_building_id = 1

    def add_building(self, x, y, connection_node_ids=None, type="building", data=None):
        building = Building(id=self._next_building_id, x=x, y=y, type=type,
                             connection_node_ids=list(connection_node_ids or []),
                             data=data or {})
        self.buildings[building.id] = building
        self._next_building_id += 1
        return building

    def connect_building_to_node(self, building_id, node_id):
        """Attach an existing road-graph node to a building as a connection
        point (entrance). Does not modify the node in any way."""
        building = self.buildings[building_id]
        if node_id not in building.connection_node_ids:
            building.connection_node_ids.append(node_id)

    def is_intersection(self, node_id):
        """Node classification (derived purely from road connectivity):
          0 roads -> isolated, 1 -> endpoint, 2 -> continuation (bend),
          3+ -> intersection. Only intersection nodes (>= 3) get junction
          rendering/markings/pavement; continuation nodes render as plain
          continuous road geometry, endpoints get dead-end caps."""
        return len(self.roads_for_node(node_id)) >= 3

    def outward_tangent_at_node(self, road, node_id):
        """Unit tangent of `road` at `node_id`, pointing away from the node
        back into the road. A quadratic Bezier's endpoint tangent runs
        toward its control point, so no sampling is needed; degenerates to
        the chord direction if the control point sits on the node."""
        start = self.nodes[road.start_node_id].pos
        end = self.nodes[road.end_node_id].pos
        control = compute_control_point(start, end, road.curve_offset)
        origin = start if road.start_node_id == node_id else end
        tangent = _normalize2(control[0] - origin[0], control[1] - origin[1])
        if tangent == (0.0, 0.0):
            other = end if origin is start else start
            tangent = _normalize2(other[0] - origin[0], other[1] - origin[1])
        return tangent

    # Width-transition (taper) tuning for 2-road continuation nodes joining
    # roads of different widths: the NARROWER road is trimmed back by a
    # taper length so the widening transition lives entirely on its side,
    # and the wider road gets only a token setback so it contributes its
    # full-width mouth to the transition surface (the wide road never
    # narrows before the node).
    TAPER_RATIO = 4.0       # taper length per foot of per-side width step
    TAPER_MIN = 12.0        # ft -- floor so even a small step eases visibly
    TAPER_WIDE_SETBACK = 0.5  # ft -- token trim on the wider road's side

    def road_trim_at_node(self, road, node_id):
        """Distance (feet) to trim `road` back from `node_id`, derived from
        the road's OWN carriageway width (not a shared/uniform radius), so
        the gap left for the junction surface follows each road's actual
        edge geometry. 0 if the node isn't an intersection -- except at a
        2-road continuation node joining different total widths, where the
        narrower road is trimmed by a taper length (and the wider by a
        token setback) so a width-transition surface can be drawn on the
        narrower road's side."""
        roads_here = self.roads_for_node(node_id)
        if (len(roads_here) == 2 and not road.is_preview
                and not any(r.is_preview for r in roads_here)
                and any(r.id == road.id for r in roads_here)):
            other = roads_here[0] if roads_here[1].id == road.id else roads_here[1]
            # Only taper across a genuine continuation (mouths roughly
            # opposing, bend <= ~90 deg). Sharper folds put both mouths on
            # the same side of the node, where any transition surface
            # degenerates into a bowtie -- render those like any other
            # sharp bend (no trim, no taper).
            out_self = self.outward_tangent_at_node(road, node_id)
            out_other = self.outward_tangent_at_node(other, node_id)
            if out_self[0] * out_other[0] + out_self[1] * out_other[1] > 0.0:
                return 0.0
            w_self = get_road_profile(road).total_width()
            w_other = get_road_profile(other).total_width()
            if w_self < w_other - 1e-6:
                taper = max(self.TAPER_MIN,
                            self.TAPER_RATIO * (w_other - w_self) / 2.0)
                # Don't let the taper swallow a short road outright: cap at
                # 40% of the node-to-node distance (a lower bound on the
                # road's true length).
                start = self.nodes[road.start_node_id].pos
                end = self.nodes[road.end_node_id].pos
                return min(taper, 0.4 * math.hypot(end[0] - start[0],
                                                    end[1] - start[1]))
            if w_self > w_other + 1e-6:
                return self.TAPER_WIDE_SETBACK
            return 0.0
        if not self.is_intersection(node_id):
            return 0.0
        # Trim back by half the carriageway (where the asphalt edge meets
        # the junction) PLUS half the full profile width (the curb-return
        # curve radius used for sidewalks/shoulders/edge lines) -- so the
        # straight boundary geometry (pavement edges, edge lines, shoulder
        # and sidewalk strips) ends exactly where the corner curve begins,
        # with no straight segment left protruding past it.
        profile = get_road_profile(road)
        trim = profile.carriageway_width() / 2.0 + profile.total_width() / 2.0

        # Acute wedges: with a width-only trim, two roads meeting at a sharp
        # angle still physically overlap past their mouths, so the junction
        # polygon built from those mouth chords self-intersects (bowtie ->
        # dark fill notch + stray edge-line sliver). Pull the mouth back to
        # where this road's near edge stops crossing each neighbour's near
        # edge: edges offset w_self/w_other from the centerlines of two
        # roads diverging at angle theta cross at distance
        # (w_self*cos(theta) + w_other) / sin(theta) along this road, the
        # single "V" point where both pavement edges meet. Obtuse pairs
        # yield a smaller (or negative) requirement and keep the base trim,
        # so non-degenerate corners keep their fillet behavior unchanged.
        w_self = profile.total_width() / 2.0
        outward = self.outward_tangent_at_node(road, node_id)
        for other in self.roads_for_node(node_id):
            if other.id == road.id:
                continue
            other_out = self.outward_tangent_at_node(other, node_id)
            cos_t = outward[0] * other_out[0] + outward[1] * other_out[1]
            sin_t = abs(outward[0] * other_out[1] - outward[1] * other_out[0])
            if sin_t < 1e-6:
                continue  # parallel/opposite: edges never cross
            w_other = get_road_profile(other).total_width() / 2.0
            needed = (w_self * cos_t + w_other) / sin_t
            if needed > trim:
                trim = needed
        return trim

    def add_zone(self, zone_type, boundary_points, data=None):
        zone = Zone(id=self._next_zone_id, type=zone_type,
                     boundary_points=boundary_points, data=data or {})
        self.zones[zone.id] = zone
        self._next_zone_id += 1
        return zone

    def add_node(self, x, y):
        node = Node(id=self._next_node_id, x=x, y=y)
        self.nodes[node.id] = node
        self._next_node_id += 1
        return node

    def add_road(self, start_node_id, end_node_id, curve_offset=(0.0, 0.0)):
        road = Road(
            id=self._next_road_id,
            start_node_id=start_node_id,
            end_node_id=end_node_id,
            curve_offset=curve_offset,
        )
        self.roads[road.id] = road
        self._next_road_id += 1
        return road

    def node_at(self, x, y, radius=NODE_HIT_RADIUS):
        for node in self.nodes.values():
            if (node.x - x) ** 2 + (node.y - y) ** 2 <= radius ** 2:
                return node
        return None

    def control_point_for_road(self, road):
        return self.geometry_for_road(road)["control_point"]

    def set_curve_offset_from_control_point(self, road, control_pos):
        """
        Given a desired control-point position (world space), compute the
        curve_offset (2D vector from the start->end midpoint) that places
        the control point there. Lets the control point move freely.
        """
        start = self.nodes[road.start_node_id].pos
        end = self.nodes[road.end_node_id].pos
        mx, my = (start[0] + end[0]) / 2.0, (start[1] + end[1]) / 2.0
        road.curve_offset = (control_pos[0] - mx, control_pos[1] - my)

    def roads_for_node(self, node_id):
        return [r for r in self.roads.values()
                if r.start_node_id == node_id or r.end_node_id == node_id]

    def road_at(self, x, y, threshold=6):
        best = None
        best_dist = threshold
        for road in self.roads.values():
            geometry = self.geometry_for_road(road)
            for px, py in geometry["sampled_points"]:
                d = ((px - x) ** 2 + (py - y) ** 2) ** 0.5
                if d < best_dist:
                    best_dist = d
                    best = road
        return best

    def geometry_for_road(self, road):
        start = self.nodes[road.start_node_id].pos
        end = self.nodes[road.end_node_id].pos
        geometry = compute_road_geometry(start, end, road.curve_offset, road.width)
        # Cache edge/polygon data on the road object (Phase 2 data fields).
        road.left_edge_points = geometry["left_edge_points"]
        road.right_edge_points = geometry["right_edge_points"]
        road.road_polygon = geometry["road_polygon"]
        return geometry


class Camera:
    """
    World <-> screen conversion for pan/zoom. All editor/geometry data stays
    in world space (feet); only rendering and mouse hit-testing go through
    this transform.
    """

    def __init__(self):
        self.offset_x = 0.0  # world-space coords shown at screen (0, 0)
        self.offset_y = 0.0
        self.zoom = 1.0
        # Smooth zoom: zoom eases toward zoom_target, anchored on the
        # screen position of the most recent scroll. Pure presentation --
        # world data / hit-testing always use the current `zoom`.
        self.zoom_target = 1.0
        self._zoom_anchor = (0.0, 0.0)
        # Viewport size in screen pixels, updated on resize/fullscreen.
        # Transforms don't depend on it, but it's the single source of
        # truth for anything (UI, future culling) that needs it.
        self.viewport_width = CANVAS_WIDTH
        self.viewport_height = CANVAS_HEIGHT

    def set_viewport(self, width, height):
        """Update viewport size on resize/fullscreen. Position and zoom
        are left untouched -- the world must not shift."""
        self.viewport_width = width
        self.viewport_height = height

    # Camera is the SINGLE conversion authority between world space (feet)
    # and screen space (pixels). Every other system -- rendering, the
    # scale bar, hit-testing, placement -- must go through these methods
    # (or feet_to_pixels/pixels_to_feet, which use the same factor) rather
    # than computing their own feet<->pixel scaling.
    def _scale(self):
        return WORLD_SCALE * self.zoom

    def world_to_screen(self, pos):
        x, y = pos
        s = self._scale()
        return ((x - self.offset_x) * s, (y - self.offset_y) * s)

    def world_to_screen_list(self, points):
        return [self.world_to_screen(p) for p in points]

    def screen_to_world(self, pos):
        x, y = pos
        s = self._scale()
        return (x / s + self.offset_x, y / s + self.offset_y)

    def feet_to_pixels(self, feet):
        """Convert a world-space (feet) distance to on-screen pixels at
        the current zoom, using the global WORLD_SCALE base scale."""
        return feet * self._scale()

    def pixels_to_feet(self, pixels):
        """Convert an on-screen pixel distance to world-space feet at the
        current zoom, using the global WORLD_SCALE base scale."""
        return pixels / self._scale()

    def pan(self, dx_screen, dy_screen):
        s = self._scale()
        self.offset_x -= dx_screen / s
        self.offset_y -= dy_screen / s

    def zoom_at(self, screen_pos, factor):
        self.zoom_target = max(ZOOM_MIN, min(ZOOM_MAX, self.zoom_target * factor))
        self._zoom_anchor = screen_pos

    def _set_zoom(self, screen_pos, new_zoom):
        new_zoom = max(ZOOM_MIN, min(ZOOM_MAX, new_zoom))
        world_before = self.screen_to_world(screen_pos)
        self.zoom = new_zoom
        world_after = self.screen_to_world(screen_pos)
        self.offset_x += world_before[0] - world_after[0]
        self.offset_y += world_before[1] - world_after[1]

    def update(self):
        """Ease the displayed zoom toward zoom_target, anchored on the
        cursor position at the time of the last scroll (smooth zoom)."""
        diff = self.zoom_target - self.zoom
        if abs(diff) < 1e-4:
            self.zoom = self.zoom_target
            return
        self._set_zoom(self._zoom_anchor, self.zoom + diff * 0.25)


INSTRUCTIONS = [
    ("Road Editor", COLOR_SIDEBAR_HEADER),
    ("", None),
    ("Camera (any tool):", COLOR_SIDEBAR_TEXT),
    ("  Scroll: zoom at cursor", COLOR_SIDEBAR_TEXT),
    ("  Right-drag: pan view", COLOR_SIDEBAR_TEXT),
    ("", None),
    ("--- Select tool ---", COLOR_SIDEBAR_HEADER),
    ("Hover a node: highlight", COLOR_SIDEBAR_TEXT),
    ("Click a node: select", COLOR_SIDEBAR_TEXT),
    ("(green ring); drag to", COLOR_SIDEBAR_TEXT),
    ("move it (roads update).", COLOR_SIDEBAR_TEXT),
    ("Click a road: select", COLOR_SIDEBAR_TEXT),
    ("(orange), shows control", COLOR_SIDEBAR_TEXT),
    ("point + guide lines.", COLOR_SIDEBAR_TEXT),
    ("Drag the red dot to bend", COLOR_SIDEBAR_TEXT),
    ("the curve, or scroll to", COLOR_SIDEBAR_TEXT),
    ("nudge curvature.", COLOR_SIDEBAR_TEXT),
    ("Click empty space to", COLOR_SIDEBAR_TEXT),
    ("deselect.", COLOR_SIDEBAR_TEXT),
    ("", None),
    ("--- Node tool ---", COLOR_SIDEBAR_HEADER),
    ("Click anywhere to create", COLOR_SIDEBAR_TEXT),
    ("a new node. No road is", COLOR_SIDEBAR_TEXT),
    ("created.", COLOR_SIDEBAR_TEXT),
    ("", None),
    ("--- New Road tool ---", COLOR_SIDEBAR_HEADER),
    ("Connects EXISTING nodes", COLOR_SIDEBAR_TEXT),
    ("only -- creates no nodes.", COLOR_SIDEBAR_TEXT),
    ("Click node A, then move", COLOR_SIDEBAR_TEXT),
    ("mouse for a live preview.", COLOR_SIDEBAR_TEXT),
    ("Scroll: adjust curvature.", COLOR_SIDEBAR_TEXT),
    ("Click node B to commit", COLOR_SIDEBAR_TEXT),
    ("the road A->B.", COLOR_SIDEBAR_TEXT),
    ("Click empty space or Esc", COLOR_SIDEBAR_TEXT),
    ("to cancel.", COLOR_SIDEBAR_TEXT),
    ("", None),
    ("--- Snap Mode (road) ---", COLOR_SIDEBAR_HEADER),
    ("Affects NEW roads only.", COLOR_SIDEBAR_TEXT),
    ("While Road tool active:", COLOR_SIDEBAR_TEXT),
    ("1 Auto  2 Straight", COLOR_SIDEBAR_TEXT),
    ("3 Curved", COLOR_SIDEBAR_TEXT),
    ("Hold Shift: force curve", COLOR_SIDEBAR_TEXT),
    ("Hold Ctrl: force straight", COLOR_SIDEBAR_TEXT),
    ("White line = straight,", COLOR_SIDEBAR_TEXT),
    ("cyan = curved preview.", COLOR_SIDEBAR_TEXT),
    ("", None),
    ("--- General ---", COLOR_SIDEBAR_HEADER),
    ("1/2/3  switch tool", COLOR_SIDEBAR_TEXT),
    ("G      lane graph viz", COLOR_SIDEBAR_TEXT),
    ("V      demo vehicle", COLOR_SIDEBAR_TEXT),
    ("D      toggle debug", COLOR_SIDEBAR_TEXT),
    ("S      save map JSON", COLOR_SIDEBAR_TEXT),
    ("L      load map JSON", COLOR_SIDEBAR_TEXT),
]


class Toolbar:
    """
    Basic UI shell: a row of tool buttons at the top of the sidebar.
    Only one tool can be active at a time (InputController.current_tool).
    """

    BUTTON_HEIGHT = 32
    BUTTON_GAP = 8
    TOP_MARGIN = 16
    SIDE_MARGIN = 16

    def __init__(self, font):
        self.font = font
        # Click-animation state: briefly highlight a button after it's
        # pressed, regardless of whether it's also active/hovered.
        self.pressed_id = None
        self.pressed_until = 0
        self.buttons = [
            (TOOL_SELECT, "Select", True),
            (TOOL_NODE, "Node Tool", True),
            (TOOL_ROAD, "New Road Tool", True),
            (TOOL_ZONE, "Zone Tool (soon)", False),
        ]
        self.action_buttons = [
            (ACTION_SAVE, "Save Map", True),
            (ACTION_LOAD, "Load Map", True),
        ]

    def layout(self, sidebar_rect):
        """Return list of (tool_id, label, enabled, rect) in screen space."""
        rects = []
        x = sidebar_rect.x + self.SIDE_MARGIN
        y = sidebar_rect.y + self.TOP_MARGIN
        width = sidebar_rect.width - 2 * self.SIDE_MARGIN
        for tool_id, label, enabled in self.buttons:
            rect = pygame.Rect(x, y, width, self.BUTTON_HEIGHT)
            rects.append((tool_id, label, enabled, rect))
            y += self.BUTTON_HEIGHT + self.BUTTON_GAP
        return rects

    def action_layout(self, sidebar_rect):
        """Return list of (action_id, label, enabled, rect) for the
        Save/Load action buttons, placed below the tool buttons."""
        rects = []
        x = sidebar_rect.x + self.SIDE_MARGIN
        y = self.bottom(sidebar_rect)
        width = sidebar_rect.width - 2 * self.SIDE_MARGIN
        for action_id, label, enabled in self.action_buttons:
            rect = pygame.Rect(x, y, width, self.BUTTON_HEIGHT)
            rects.append((action_id, label, enabled, rect))
            y += self.BUTTON_HEIGHT + self.BUTTON_GAP
        return rects

    def bottom(self, sidebar_rect):
        rects = self.layout(sidebar_rect)
        return rects[-1][3].bottom + self.BUTTON_GAP if rects else sidebar_rect.y

    def full_bottom(self, sidebar_rect):
        rects = self.action_layout(sidebar_rect)
        return rects[-1][3].bottom + self.BUTTON_GAP if rects else self.bottom(sidebar_rect)

    def _draw_buttons(self, surface, rects, active_id, hovered_id):
        now = pygame.time.get_ticks()
        pressed_active = self.pressed_id is not None and now < self.pressed_until
        for item_id, label, enabled, rect in rects:
            if not enabled:
                color = COLOR_BUTTON_DISABLED
                text_color = COLOR_BUTTON_TEXT_DISABLED
            elif item_id == active_id:
                # State priority: active > hover > click animation.
                color = COLOR_BUTTON_ACTIVE
                text_color = COLOR_BUTTON_TEXT
            elif pressed_active and item_id == self.pressed_id:
                color = COLOR_BUTTON_PRESSED
                text_color = COLOR_BUTTON_TEXT
            elif item_id == hovered_id:
                color = COLOR_BUTTON_HOVER
                text_color = COLOR_BUTTON_TEXT
            else:
                color = COLOR_BUTTON
                text_color = COLOR_BUTTON_TEXT
            pygame.draw.rect(surface, color, rect, border_radius=4)
            label_surf = self.font.render(label, True, text_color)
            label_rect = label_surf.get_rect(center=rect.center)
            surface.blit(label_surf, label_rect)

    def draw(self, surface, sidebar_rect, current_tool, hovered=None):
        hovered_id = hovered[1] if hovered is not None else None
        self._draw_buttons(surface, self.layout(sidebar_rect), current_tool, hovered_id)
        self._draw_buttons(surface, self.action_layout(sidebar_rect), None, hovered_id)

    def handle_hover(self, sidebar_rect, screen_pos):
        """Return (kind, id) for the button under screen_pos, else None.
        Used for hover highlighting and tooltips (any enabled button)."""
        for tool_id, label, enabled, rect in self.layout(sidebar_rect):
            if enabled and rect.collidepoint(screen_pos):
                return ("tool", tool_id)
        for action_id, label, enabled, rect in self.action_layout(sidebar_rect):
            if enabled and rect.collidepoint(screen_pos):
                return ("action", action_id)
        return None

    def handle_click(self, sidebar_rect, screen_pos):
        """Return (kind, id) if an enabled button was clicked, else None.
        kind is "tool" for tool-switch buttons or "action" for Save/Load.
        Also starts the brief press/click animation for that button."""
        clicked = self.handle_hover(sidebar_rect, screen_pos)
        if clicked is not None:
            self.pressed_id = clicked[1]
            self.pressed_until = pygame.time.get_ticks() + BUTTON_PRESS_DURATION_MS
        return clicked

    def tooltip_rect_for(self, sidebar_rect, item_id):
        for iid, label, enabled, rect in self.layout(sidebar_rect) + self.action_layout(sidebar_rect):
            if iid == item_id:
                return rect
        return None


class Sidebar:
    """Draws the toolbar + snap-mode panel + scrollable instructions panel."""

    def __init__(self, surface, font, header_font, toolbar):
        self.surface = surface
        self.font = font
        self.header_font = header_font
        self.toolbar = toolbar
        # Snap Mode overlay UI: lightweight radio panel below the
        # action buttons. Pure UI -- mode state lives in SnapModeController.
        self.snap_panel = SnapModePanel(font, header_font)

    def draw(self, rect, current_tool, status_message="", scroll=0, context_hint="",
             hovered=None, snap_mode=SNAP_AUTO):
        pygame.draw.rect(self.surface, COLOR_SIDEBAR_BG, rect)

        self.toolbar.draw(self.surface, rect, current_tool, hovered=hovered)

        x = rect.x + 16
        y = self.toolbar.full_bottom(rect) + 4
        y = self.snap_panel.draw(self.surface, rect, y, snap_mode) + 10

        active_label = TOOL_LABELS.get(current_tool, current_tool)
        active_surf = self.header_font.render(f"Active Tool: {active_label}", True, COLOR_SIDEBAR_HEADER)
        self.surface.blit(active_surf, (x, y))
        y += 22

        if context_hint:
            hint_surf = self.font.render(context_hint, True, COLOR_SIDEBAR_TEXT)
            self.surface.blit(hint_surf, (x, y))
            y += 22

        content_top = y + 8

        # Clip instructions to the area below the toolbar so scrolling
        # doesn't draw over the buttons.
        clip_rect = pygame.Rect(rect.x, content_top, rect.width, rect.bottom - content_top)
        prev_clip = self.surface.get_clip()
        self.surface.set_clip(clip_rect)

        y = content_top - scroll
        for text, color in INSTRUCTIONS:
            if text == "":
                y += 10
                continue
            f = self.header_font if color == COLOR_SIDEBAR_HEADER else self.font
            label = f.render(text, True, color)
            self.surface.blit(label, (x, y))
            y += 22

        if status_message:
            y += 10
            label = self.font.render(status_message, True, COLOR_SIDEBAR_HEADER)
            self.surface.blit(label, (x, y))

        self.surface.set_clip(prev_clip)

        # Hover tooltip, drawn last so it sits on top of everything else.
        if hovered is not None:
            self._draw_tooltip(rect, hovered)

    def _draw_tooltip(self, sidebar_rect, hovered):
        kind, item_id = hovered
        info = TOOLTIPS.get(item_id)
        button_rect = self.toolbar.tooltip_rect_for(sidebar_rect, item_id)
        if info is None or button_rect is None:
            return
        name, description, usage = info
        lines = [(name, COLOR_SIDEBAR_HEADER), (description, COLOR_SIDEBAR_TEXT),
                 (usage, COLOR_SIDEBAR_TEXT)]
        line_surfs = [(f.render(text, True, color))
                       for (text, color), f in zip(lines, [self.header_font, self.font, self.font])]
        width = max(s.get_width() for s in line_surfs) + 16
        height = sum(s.get_height() for s in line_surfs) + 12
        x = button_rect.left
        y = button_rect.bottom + 4
        panel = pygame.Rect(x, y, width, height)
        pygame.draw.rect(self.surface, COLOR_TOOLTIP_BG, panel, border_radius=4)
        pygame.draw.rect(self.surface, COLOR_TOOLTIP_BORDER, panel, 1, border_radius=4)
        ty = y + 6
        for s in line_surfs:
            self.surface.blit(s, (x + 8, ty))
            ty += s.get_height()


class ScaleBar:
    """
    Bottom-left, screen-fixed map scale bar (feet). Depends only on
    camera.zoom -- never on camera position, window size beyond drawing
    position, or world data. Picks the largest "clean" foot value from
    SCALE_BAR_VALUES_FT whose rendered width fits within SCALE_BAR_MAX_PX.
    """

    @staticmethod
    def compute(camera):
        chosen = SCALE_BAR_VALUES_FT[0]
        for ft in SCALE_BAR_VALUES_FT:
            width_px = camera.feet_to_pixels(ft)
            if width_px <= SCALE_BAR_MAX_PX:
                chosen = ft
            else:
                break
        return chosen, camera.feet_to_pixels(chosen)

    def draw(self, surface, font, camera, canvas_rect):
        feet, width_px = self.compute(camera)
        x0 = canvas_rect.x + SCALE_BAR_MARGIN
        y = canvas_rect.bottom - SCALE_BAR_MARGIN
        x1 = x0 + width_px

        pygame.draw.line(surface, COLOR_SCALE_BAR, (x0, y), (x1, y), 3)
        pygame.draw.line(surface, COLOR_SCALE_BAR, (x0, y - 5), (x0, y + 5), 2)
        pygame.draw.line(surface, COLOR_SCALE_BAR, (x1, y - 5), (x1, y + 5), 2)

        label = font.render(f"{feet} ft", True, COLOR_SCALE_BAR)
        surface.blit(label, (x0, y - label.get_height() - 4))


def _trim_polyline(points, start_trim, end_trim):
    """Shorten a polyline by `start_trim`/`end_trim` feet (arc length) from
    each end, inserting an interpolated point at the exact trim distance.
    Returns the original points unchanged if the line is too short to trim."""
    pts = list(points)
    if start_trim > 0:
        remaining = start_trim
        while len(pts) >= 2:
            seg = math.hypot(pts[1][0] - pts[0][0], pts[1][1] - pts[0][1])
            if seg > remaining:
                t = remaining / seg
                pts[0] = (pts[0][0] + (pts[1][0] - pts[0][0]) * t,
                          pts[0][1] + (pts[1][1] - pts[0][1]) * t)
                break
            remaining -= seg
            pts.pop(0)
    if end_trim > 0:
        remaining = end_trim
        while len(pts) >= 2:
            seg = math.hypot(pts[-1][0] - pts[-2][0], pts[-1][1] - pts[-2][1])
            if seg > remaining:
                t = remaining / seg
                pts[-1] = (pts[-1][0] + (pts[-2][0] - pts[-1][0]) * t,
                           pts[-1][1] + (pts[-2][1] - pts[-1][1]) * t)
                break
            remaining -= seg
            pts.pop()
    if len(pts) < 2:
        return points
    return pts


def _normalize2(dx, dy):
    length = math.hypot(dx, dy)
    if length == 0:
        return (0.0, 0.0)
    return (dx / length, dy / length)


def _fillet_points(point_a, tangent_a, point_b, tangent_b, node_pos, samples=5):
    """Cubic-Bezier fillet between two edge points, tangent-continuous with
    each road's edge direction at the junction. `tangent_a`/`tangent_b`
    point OUTWARD (back into each road, away from the node), so the curve
    leaves/arrives matching the real road edge directions instead of a
    straight chord. The curve's size scales with the wedge angle between
    the two roads: wide corners get a full sweeping curve, tight corners a
    proportionally smaller one, degrading continuously to the straight
    chord as the wedge closes. `node_pos` (the junction node) fixes which
    way the curve bows: both control points are forced onto the node's
    side of the chord, so the fillet always faces INTO the junction --
    a Bezier never leaves the convex hull of its endpoints and control
    points, so it can't bulge past the chord on the outward side. Returns
    interior points only (excludes the endpoints)."""
    chord = (point_b[0] - point_a[0], point_b[1] - point_a[1])
    half_chord = math.hypot(chord[0], chord[1]) * 0.5
    node_side = chord[0] * (node_pos[1] - point_a[1]) - chord[1] * (node_pos[0] - point_a[0])

    # Orient each tangent: both +tangent and -tangent are valid edge
    # directions, and the sign decides which side of the chord the control
    # point lands on -- i.e. which way the curve bows. Primary criterion:
    # the perpendicular component must point toward the NODE side of the
    # chord, so the fillet is concave into the junction (a dot-with-chord
    # heuristic alone gets this wrong when the edge is perpendicular to
    # the chord, e.g. asymmetric-width corners). Tie-break, when the
    # tangent is parallel to the chord (or the node sits on it): point
    # along the chord travel direction so the curve doesn't loop backward.
    def _oriented(t, fwd):
        side = chord[0] * t[1] - chord[1] * t[0]
        if abs(side) > 1e-9 and abs(node_side) > 1e-9:
            keep = (side > 0) == (node_side > 0)
        else:
            keep = (t[0] * fwd[0] + t[1] * fwd[1]) >= 0
        return t if keep else (-t[0], -t[1])

    ta = _oriented(tangent_a, chord)
    tb = _oriented(tangent_b, (-chord[0], -chord[1]))

    # Wedge angle between the two roads at this corner, from the oriented
    # tangents: pi (180 deg, curve runs straight through) down to 0 (fully
    # closed wedge). The control-point distance scales linearly with it,
    # so the tighter the corner, the smaller the curb-return curve. This
    # also keeps near-parallel converging edges (the old loop/gap hazard)
    # safe: their control points collapse onto the endpoints and the curve
    # hugs the straight chord instead of looping. The continuous scaling
    # replaces the old hard dot-product cutoff at 90 degrees, so corners of
    # a symmetric cross can no longer flip looks on float noise.
    dot = max(-1.0, min(1.0, ta[0] * tb[0] + ta[1] * tb[1]))
    wedge = math.acos(dot)
    scale = wedge / math.pi
    if scale < 1e-3:
        return []
    d = half_chord * scale

    c1 = (point_a[0] + ta[0] * d, point_a[1] + ta[1] * d)
    c2 = (point_b[0] + tb[0] * d, point_b[1] + tb[1] * d)

    # No-loop guarantee: the curve cannot self-intersect if it advances
    # monotonically along the chord, which holds when neither control
    # displacement has a backward chord component. Node-side orientation
    # can demand a backward-pointing tangent when facing-in and tangent-
    # continuity conflict (sharp/acute corners with skewed widths); strip
    # only the backward chord-parallel part and keep the inward
    # perpendicular part, so the curve still bows into the junction but
    # provably never doubles back into a loop. The correction is
    # continuous: it vanishes as the tangent rotates back to forward.
    if half_chord > 1e-9:
        ux, uy = chord[0] / (2 * half_chord), chord[1] / (2 * half_chord)
        back_a = ta[0] * ux + ta[1] * uy
        if back_a < 0:
            c1 = (c1[0] - ux * back_a * d, c1[1] - uy * back_a * d)
        back_b = -(tb[0] * ux + tb[1] * uy)  # tb should run AGAINST the chord
        if back_b < 0:
            c2 = (c2[0] + ux * back_b * d, c2[1] + uy * back_b * d)
    pts = []
    for i in range(1, samples):
        t = i / samples
        mt = 1 - t
        x = (mt ** 3) * point_a[0] + 3 * (mt ** 2) * t * c1[0] + 3 * mt * (t ** 2) * c2[0] + (t ** 3) * point_b[0]
        y = (mt ** 3) * point_a[1] + 3 * (mt ** 2) * t * c1[1] + 3 * mt * (t ** 2) * c2[1] + (t ** 3) * point_b[1]
        pts.append((x, y))
    return pts


def _line_intersection(p1, d1, p2, d2):
    """Intersection of line (p1 + t*d1) and line (p2 + s*d2), or None if
    parallel/degenerate."""
    denom = d1[0] * d2[1] - d1[1] * d2[0]
    if abs(denom) < 1e-9:
        return None
    t = ((p2[0] - p1[0]) * d2[1] - (p2[1] - p1[1]) * d2[0]) / denom
    return (p1[0] + d1[0] * t, p1[1] + d1[1] * t)


def _segment_intersection(a1, a2, b1, b2):
    """Return the intersection point of segments a1->a2 and b1->b2, or None
    if they don't cross (parallel, or crossing point outside either
    segment)."""
    d1 = (a2[0] - a1[0], a2[1] - a1[1])
    d2 = (b2[0] - b1[0], b2[1] - b1[1])
    denom = d1[0] * d2[1] - d1[1] * d2[0]
    if abs(denom) < 1e-9:
        return None
    t = ((b1[0] - a1[0]) * d2[1] - (b1[1] - a1[1]) * d2[0]) / denom
    s = ((b1[0] - a1[0]) * d1[1] - (b1[1] - a1[1]) * d1[0]) / denom
    if -1e-6 <= t <= 1 + 1e-6 and -1e-6 <= s <= 1 + 1e-6:
        return (a1[0] + d1[0] * t, a1[1] + d1[1] * t)
    return None


# ----------------------------------------------------------------------
# Watchdog: read-only geometry diagnostics. Detects suspicious geometry
# (crossings without nodes, trims that overflow a road's length, degenerate
# profile widths) and reports it for visualization -- it does NOT modify or
# fix anything.
# ----------------------------------------------------------------------

def detect_geometry_issues(network):
    """Return a list of {"type", "pos", "message"} issue dicts describing
    geometry the renderer can highlight, e.g.:
      - "crossing_no_node": two roads' centerlines cross at a point that
        isn't a shared graph node.
      - "trim_overflow": a road's intersection trims consume its entire
        length, collapsing its drawable geometry.
      - "degenerate_width": a road's profile produces a zero/negative
        left_width()/right_width() or lane_width.
    """
    issues = []
    roads = [r for r in network.roads.values() if not r.is_preview]

    # 1. Centerline crossings between roads that share no node.
    for i in range(len(roads)):
        for j in range(i + 1, len(roads)):
            r1, r2 = roads[i], roads[j]
            shared = {r1.start_node_id, r1.end_node_id} & {r2.start_node_id, r2.end_node_id}
            if shared:
                continue
            pts1 = network.geometry_for_road(r1)["sampled_points"]
            pts2 = network.geometry_for_road(r2)["sampled_points"]
            found = False
            for k in range(len(pts1) - 1):
                if found:
                    break
                for l in range(len(pts2) - 1):
                    pt = _segment_intersection(pts1[k], pts1[k + 1], pts2[l], pts2[l + 1])
                    if pt is not None:
                        issues.append({
                            "type": "crossing_no_node",
                            "pos": pt,
                            "message": f"Roads {r1.id} and {r2.id} cross without a shared node",
                        })
                        found = True
                        break

    # 2/3. Per-road trim and profile sanity.
    for road in roads:
        geometry = network.geometry_for_road(road)
        pts = geometry["sampled_points"]
        start_trim = network.road_trim_at_node(road, road.start_node_id)
        end_trim = network.road_trim_at_node(road, road.end_node_id)
        if start_trim > 0 or end_trim > 0:
            trimmed = _trim_polyline(pts, start_trim, end_trim)
            if len(trimmed) < 2:
                mid = pts[len(pts) // 2]
                issues.append({
                    "type": "trim_overflow",
                    "pos": mid,
                    "message": f"Road {road.id}: intersection trims ({start_trim:.1f}+{end_trim:.1f}ft) "
                               f"exceed road length -- geometry collapsed",
                })

        profile = get_road_profile(road)
        if profile.left_width() <= 0 or profile.right_width() <= 0 or profile.lane_width <= 0:
            mid = pts[len(pts) // 2]
            issues.append({
                "type": "degenerate_width",
                "pos": mid,
                "message": f"Road {road.id}: degenerate profile width "
                           f"(left={profile.left_width():.2f}, right={profile.right_width():.2f}, "
                           f"lane_width={profile.lane_width:.2f})",
            })

    return issues


def _build_junction_polygon(entries, node_pos):
    """Merge each connected road's near-end edge pair into one junction
    polygon, ordered by each road's outward tangent angle (NOT by raw point
    angle -- with >=4 roads a road's own left/right edge points can be on
    opposite sides of the node, so sorting points directly produces a
    self-intersecting polygon).

    Each entry is one road: {"left", "right", "outward", "color"}, where
    "left"/"right" are that road's near-end edge points using a consistent
    convention (perpendicular to the OUTWARD tangent, rotated +90 = left).

    Going counter-clockwise by outward-tangent angle, road i contributes its
    own chord [right_i, left_i], then fills the gap to the next road's
    right_(i+1) point with a tangent-continuous Bezier fillet whose size
    scales with the wedge angle between the two roads: wide corners curve
    gently, tight/acute corners get a proportionally smaller curve that
    degrades continuously into a straight join as the wedge closes (see
    _fillet_points).

    Returns (polygon_points, edge_lines) where edge_lines is
    [(curve_points, color), ...] for the connectors only."""
    ordered = sorted(entries, key=lambda e: math.atan2(e["outward"][1], e["outward"][0]))
    polygon = []
    edge_lines = []
    n = len(ordered)
    for i in range(n):
        a = ordered[i]
        b = ordered[(i + 1) % n]
        polygon.append(a["right"])
        polygon.append(a["left"])

        # The road geometry feeding these entries has already been trimmed
        # back (in road_trim_at_node) by an extra curb-return radius beyond
        # the bare carriageway/shoulder edge, so a["left"] and b["right"]
        # are themselves the curve's start/end points -- no further
        # pullback is needed. A tangent-continuous Bezier fillet bridges
        # them directly, replacing the straight segment entirely (the
        # straight boundary geometry simply doesn't extend past these
        # points anymore).
        fillet = _fillet_points(a["left"], a["outward"], b["right"], b["outward"], node_pos)
        polygon.extend(fillet)

        edge_lines.append(([a["left"]] + fillet + [b["right"]], a["color"]))
    return polygon, edge_lines


def _taper_curve(point_a, tangent_a, point_b, tangent_b, samples=8):
    """Cubic S-curve edge for a width transition: leaves `point_a` heading
    back toward the node (against `tangent_a`, which points outward into
    its road) and arrives at `point_b` moving outward along `tangent_b`,
    so each end is tangent-continuous with its road's straight edge.
    Unlike a junction corner fillet this curve is SUPPOSED to cross its
    chord (an S-shape has an inflection), so no faces-in constraint
    applies. The no-loop guarantee is the same as _fillet_points': any
    backward chord component is stripped from a control displacement, so
    the curve advances monotonically along its chord and can never double
    back into a loop, even across a sharply bent continuation node.
    Returns interior points only (excludes the endpoints)."""
    chord = (point_b[0] - point_a[0], point_b[1] - point_a[1])
    clen = math.hypot(chord[0], chord[1])
    if clen < 1e-9:
        return []
    ux, uy = chord[0] / clen, chord[1] / clen
    d = clen / 3.0

    disp_a = (-tangent_a[0] * d, -tangent_a[1] * d)   # depart toward the node
    disp_b = (-tangent_b[0] * d, -tangent_b[1] * d)   # arrive along +tangent_b
    back_a = disp_a[0] * ux + disp_a[1] * uy
    if back_a < 0:
        disp_a = (disp_a[0] - ux * back_a, disp_a[1] - uy * back_a)
    back_b = disp_b[0] * ux + disp_b[1] * uy
    if back_b > 0:
        disp_b = (disp_b[0] - ux * back_b, disp_b[1] - uy * back_b)

    c1 = (point_a[0] + disp_a[0], point_a[1] + disp_a[1])
    c2 = (point_b[0] + disp_b[0], point_b[1] + disp_b[1])
    pts = []
    for i in range(1, samples):
        t = i / samples
        mt = 1 - t
        x = (mt ** 3) * point_a[0] + 3 * (mt ** 2) * t * c1[0] + 3 * mt * (t ** 2) * c2[0] + (t ** 3) * point_b[0]
        y = (mt ** 3) * point_a[1] + 3 * (mt ** 2) * t * c1[1] + 3 * mt * (t ** 2) * c2[1] + (t ** 3) * point_b[1]
        pts.append((x, y))
    return pts


def _build_taper_polygon(entries):
    """Width-transition surface for a continuation node joining exactly two
    roads of different total widths. The wider road's mouth sits a token
    setback from the node at its full width; the narrower road's mouth sits
    a taper length down its own corridor -- so the whole transition lives
    on the narrower road's side and the wider road never necks down before
    the node. Each long edge is a tangent-continuous S-curve between the
    corresponding mouth corners (see _taper_curve).

    Same contract as _build_junction_polygon: entries are the two roads'
    {"left", "right", "outward", "color"} mouths; returns
    (polygon_points, edge_lines)."""
    a, b = entries
    polygon = []
    edge_lines = []
    for p, q in ((a, b), (b, a)):
        polygon.append(p["right"])
        polygon.append(p["left"])
        curve = _taper_curve(p["left"], p["outward"], q["right"], q["outward"])
        polygon.extend(curve)
        edge_lines.append(([p["left"]] + curve + [q["right"]], p["color"]))
    return polygon, edge_lines


class RoadRenderer:
    """Pure drawing. Reads network + preview state, draws to a surface through the camera."""

    def __init__(self, surface, font, camera):
        self.surface = surface
        self.font = font
        self.camera = camera
        self.scale_bar = ScaleBar()
        # Hit-rects for the lane-count context menu, refreshed each draw()
        # while a road is selected: [(rect, profile_key, delta), ...].
        self.lane_menu_buttons = []
        # Sprite caches for the generic "sprite" visual layer: base images
        # by path (None = failed load), plus the last rotated/scaled result
        # per path so straight-line motion at constant zoom costs nothing.
        self._sprite_images = {}
        self._sprite_rendered = {}

    def _sprite_base(self, path):
        if path not in self._sprite_images:
            try:
                self._sprite_images[path] = pygame.image.load(path).convert_alpha()
            except (pygame.error, FileNotFoundError, TypeError):
                self._sprite_images[path] = None
        return self._sprite_images[path]

    WATCHDOG_COLORS = {
        "crossing_no_node": (255, 60, 220),
        "trim_overflow": (255, 60, 60),
        "degenerate_width": (255, 170, 0),
    }

    def draw_watchdog_overlay(self, issues):
        """Draw markers for each detected geometry issue (debug-mode only).
        Read-only: highlights problems, fixes nothing."""
        cam = self.camera
        for i, issue in enumerate(issues):
            color = self.WATCHDOG_COLORS.get(issue["type"], (255, 0, 255))
            sx, sy = cam.world_to_screen(issue["pos"])
            r = 9
            pygame.draw.circle(self.surface, color, (int(sx), int(sy)), r, 2)
            pygame.draw.line(self.surface, color, (sx - r, sy - r), (sx + r, sy + r), 2)
            pygame.draw.line(self.surface, color, (sx - r, sy + r), (sx + r, sy - r), 2)

            label = self.font.render(issue["message"], True, color)
            self.surface.blit(label, (sx + r + 4, sy - r))

        if issues:
            summary = self.font.render(
                f"WATCHDOG: {len(issues)} geometry issue(s) detected", True, (255, 60, 60))
            self.surface.blit(summary, (10, self.surface.get_height() - 24))

    def draw_lane_menu(self, network, road):
        """Small floating panel anchored near the selected road's midpoint,
        showing forward/reverse lane counts with +/- controls. Returns
        nothing; populates self.lane_menu_buttons for hit-testing."""
        self.lane_menu_buttons = []
        profile = get_road_profile(road)
        geometry = network.geometry_for_road(road)
        pts = geometry["sampled_points"]
        mid = pts[len(pts) // 2]
        anchor_x, anchor_y = self.camera.world_to_screen(mid)

        # "Left"/"Right" matches the geometric sign convention used by
        # profile_markings/offset_polyline (sign=+1 -> left of travel
        # direction, sign=-1 -> right), so the label maps directly onto the
        # underlying lanes_forward()/lanes_reverse() data with no extra
        # heading computation.
        rows = [
            ("Left lanes", profile.lanes_forward(), "lane_count_forward", 1),
            ("Right lanes", profile.lanes_reverse(), "lane_count_reverse", -1),
        ]

        padding = 8
        row_h = 24
        width = 170
        height = padding * 2 + row_h * len(rows)
        panel_x = int(anchor_x + 12)
        panel_y = int(anchor_y - height - 12)

        panel_rect = pygame.Rect(panel_x, panel_y, width, height)

        # Live highlight: tint the half of the road surface (left or right
        # of the centerline) corresponding to the row currently under the
        # mouse cursor, so it's visually unambiguous which side a lane-count
        # change will affect.
        mouse_pos = pygame.mouse.get_pos()
        half = profile.carriageway_width() / 2.0
        for i, (label, value, key, side_sign) in enumerate(rows):
            row_rect = pygame.Rect(panel_rect.x, panel_rect.y + padding + i * row_h, width, row_h)
            if row_rect.collidepoint(mouse_pos):
                inner = offset_polyline(pts, 0.0)
                outer = offset_polyline(pts, side_sign * half)
                highlight_poly = inner + list(reversed(outer))
                screen_poly = self.camera.world_to_screen_list(highlight_poly)
                overlay = pygame.Surface(self.surface.get_size(), pygame.SRCALPHA)
                pygame.draw.polygon(overlay, (255, 230, 90, 90), screen_poly)
                self.surface.blit(overlay, (0, 0))

        pygame.draw.rect(self.surface, COLOR_TOOLTIP_BG, panel_rect)
        pygame.draw.rect(self.surface, COLOR_TOOLTIP_BORDER, panel_rect, 1)

        for i, (label, value, key, side_sign) in enumerate(rows):
            row_y = panel_rect.y + padding + i * row_h
            text = self.font.render(f"{label}: {value}", True, COLOR_BUTTON_TEXT)
            self.surface.blit(text, (panel_rect.x + padding, row_y + 3))

            minus_rect = pygame.Rect(panel_rect.right - padding - 44, row_y, 18, 18)
            plus_rect = pygame.Rect(panel_rect.right - padding - 20, row_y, 18, 18)
            for rect, sign in ((minus_rect, -1), (plus_rect, 1)):
                pygame.draw.rect(self.surface, COLOR_BUTTON, rect)
                pygame.draw.rect(self.surface, COLOR_TOOLTIP_BORDER, rect, 1)
                glyph = self.font.render("-" if sign < 0 else "+", True, COLOR_BUTTON_TEXT)
                glyph_rect = glyph.get_rect(center=rect.center)
                self.surface.blit(glyph, glyph_rect)
                self.lane_menu_buttons.append((rect, key, sign))

    def draw_road(self, network, road, geometry, line_color, surface_color, alpha,
                   debug, selected=False):
        cam = self.camera
        points = cam.world_to_screen_list(geometry["sampled_points"])

        # Full road surface width (lanes + median + shoulders) comes from
        # the RoadProfile, NOT from road.width -- the spline/edge/polygon
        # functions from road_geometry are unchanged, just fed a different
        # width for rendering. Preview roads have no profile; fall back to
        # their geometry's own (logical-width) polygon.
        if not road.is_preview:
            profile = get_road_profile(road)
            # Asymmetric per-side offsets from the (immutable) centerline --
            # changing lanes/shoulders on one side never shifts the other
            # side's edge or the centerline itself.
            left = offset_polyline(geometry["sampled_points"], profile.left_width() + profile.shoulder_width)
            right = offset_polyline(geometry["sampled_points"], -(profile.right_width() + profile.shoulder_width))
            polygon = cam.world_to_screen_list(compute_road_polygon(left, right))
        else:
            profile = None
            polygon = cam.world_to_screen_list(geometry["road_polygon"])

        # Road surface (filled polygon) replaces the simple centerline as
        # the primary visual.
        if alpha < 255:
            poly_surf = pygame.Surface(self.surface.get_size(), pygame.SRCALPHA)
            pygame.draw.polygon(poly_surf, (*surface_color, alpha), polygon)
            self.surface.blit(poly_surf, (0, 0))
        else:
            pygame.draw.polygon(self.surface, surface_color, polygon)

        # Visual style layer: shoulders, median, lane markings + decals --
        # purely cosmetic and independent of the geometry/polygon above
        # (skipped for the ghost preview road, which has no profile/style).
        if not road.is_preview:
            for region in profile_shoulder_regions(geometry["sampled_points"], profile):
                region_screen = cam.world_to_screen_list(region["polygon"])
                pygame.draw.polygon(self.surface, region["color"], region_screen)
                if profile.shoulder_type == SHOULDER_SIDEWALK:
                    # Sidewalk-specific outline (curb edge) so the strip
                    # reads as a distinct paved sidewalk rather than a
                    # plain color fill.
                    pygame.draw.polygon(self.surface, COLOR_CURB, region_screen, 1)
            median = profile_median_region(geometry["sampled_points"], profile)
            if median is not None:
                pygame.draw.polygon(self.surface, median["color"],
                                     cam.world_to_screen_list(median["polygon"]))

        # Selected road: highlight centerline, show guide lines + control point.
        if selected:
            pygame.draw.lines(self.surface, line_color, False, points, 3)
            cp = cam.world_to_screen(geometry["control_point"])
            pygame.draw.line(self.surface, COLOR_GUIDE_LINE, points[0], cp, 1)
            pygame.draw.line(self.surface, COLOR_GUIDE_LINE, cp, points[-1], 1)
            pygame.draw.circle(self.surface, COLOR_CONTROL_POINT, cp,
                                max(2, CONTROL_POINT_RADIUS * cam.zoom))

        # Centerline is a debug-only overlay now.
        if debug:
            pygame.draw.lines(self.surface, COLOR_CENTERLINE_DEBUG, False, points, 2)

            cp = cam.world_to_screen(geometry["control_point"])
            pygame.draw.circle(self.surface, COLOR_CONTROL_POINT, cp, max(2, 5 * cam.zoom))
            for p in points:
                pygame.draw.circle(self.surface, COLOR_SAMPLE_POINT, p, max(1, 2 * cam.zoom))
            for p in cam.world_to_screen_list(geometry["left_edge_points"]):
                pygame.draw.circle(self.surface, COLOR_LEFT_EDGE, p, max(1, 2 * cam.zoom))
            for p in cam.world_to_screen_list(geometry["right_edge_points"]):
                pygame.draw.circle(self.surface, COLOR_RIGHT_EDGE, p, max(1, 2 * cam.zoom))

            mid = points[len(points) // 2]
            label = self.font.render(f"R{road.id}", True, COLOR_DEBUG_TEXT)
            self.surface.blit(label, (mid[0] + 6, mid[1] + 6))

    def draw_road_markings(self, network, road, geometry):
        """Dedicated Road Marking Renderer pass: center, lane-separator and
        edge lines (plus decals), generated from the road's RoadProfile /
        RoadStyle. Runs entirely after road-surface rendering, so markings
        never affect or are affected by surface/intersection geometry.

        All markings -- including the center line -- are trimmed back at
        intersections so they terminate at the junction boundary instead of
        all roads' center lines crossing/meeting in the middle of the
        junction."""
        if road.is_preview:
            return
        profile = get_road_profile(road)

        trimmed = geometry["sampled_points"]
        start_trim = network.road_trim_at_node(road, road.start_node_id)
        end_trim = network.road_trim_at_node(road, road.end_node_id)
        if start_trim > 0 or end_trim > 0:
            trimmed = _trim_polyline(trimmed, start_trim, end_trim)

        self.draw_lane_markings(geometry, trimmed, profile)
        self.draw_decals(geometry, get_road_style(road))

    def draw_lane_markings(self, geometry, trimmed_points, profile):
        """Paint center + edge/separator lane markings from the road's
        RoadProfile. Purely cosmetic -- reads geometry, never recomputes
        the spline. All markings use `trimmed_points` so every line
        (including the center line) stops at the junction boundary instead
        of meeting/crossing other roads' lines in the intersection."""
        cam = self.camera
        for marking, offset in profile_markings(profile):
            base = trimmed_points
            if len(base) < 2:
                continue
            line_pts = offset_polyline(base, offset) if offset else base
            for segment in marking_segments(line_pts, marking):
                screen_pts = cam.world_to_screen_list(segment)
                if len(screen_pts) < 2:
                    continue
                width_px = max(1, int(round(marking.thickness * cam.zoom)))
                pygame.draw.lines(self.surface, marking.color, False, screen_pts, width_px)

    def draw_decals(self, geometry, style):
        """Paint configured decals (arrows/symbols/text) along the road."""
        cam = self.camera
        sampled = geometry["sampled_points"]
        for decal in style.decals:
            (wx, wy), angle = decal_transform(sampled, decal)
            p = cam.world_to_screen((wx, wy))
            scale = decal.scale * cam.zoom

            if decal.kind == "arrow":
                length = 10.0 * scale
                width = 4.0 * scale
                dx, dy = math.cos(angle), math.sin(angle)
                nx, ny = -dy, dx
                tip = (p[0] + dx * length, p[1] + dy * length)
                base_l = (p[0] - dx * length + nx * width, p[1] - dy * length + ny * width)
                base_r = (p[0] - dx * length - nx * width, p[1] - dy * length - ny * width)
                pygame.draw.polygon(self.surface, decal.color, [tip, base_l, base_r])

            elif decal.kind == "symbol":
                radius = max(2, 6 * scale)
                pygame.draw.circle(self.surface, decal.color, p, radius, max(1, int(scale)))

            elif decal.kind == "text" and decal.label:
                label_surf = self.font.render(decal.label, True, decal.color)
                rect = label_surf.get_rect(center=p)
                self.surface.blit(label_surf, rect)

    def draw_zone(self, zone, debug):
        if len(zone.boundary_points) < 3:
            return
        cam = self.camera
        screen_points = cam.world_to_screen_list(zone.boundary_points)
        color = ZONE_COLORS.get(zone.type, ZONE_DEFAULT_COLOR)
        zone_surf = pygame.Surface(self.surface.get_size(), pygame.SRCALPHA)
        pygame.draw.polygon(zone_surf, (*color, ZONE_ALPHA), screen_points)
        pygame.draw.polygon(zone_surf, (*color, 255), screen_points, 2)
        self.surface.blit(zone_surf, (0, 0))
        if debug:
            cx = sum(p[0] for p in screen_points) / len(screen_points)
            cy = sum(p[1] for p in screen_points) / len(screen_points)
            label = self.font.render(f"Z{zone.id}:{zone.type}", True, COLOR_DEBUG_TEXT)
            self.surface.blit(label, (cx, cy))

    def draw_node(self, node, color, debug, ring_color=None):
        cam = self.camera
        p = cam.world_to_screen(node.pos)
        # Nodes are UI-anchored markers: fixed screen-pixel size, not
        # scaled by camera zoom / WORLD_SCALE.
        radius = NODE_RADIUS
        pygame.draw.circle(self.surface, color, p, radius)
        if ring_color is not None:
            pygame.draw.circle(self.surface, ring_color, p, radius + 4, 2)
        if debug:
            label = self.font.render(f"N{node.id}", True, COLOR_DEBUG_TEXT)
            self.surface.blit(label, (p[0] + 10, p[1] - 10))

    def draw_preview_node(self, node, snapped=False):
        """
        Visual-only fake endpoint for the New Road tool: semi-transparent,
        not part of the graph, not saved, not hit-testable. Drawn last so
        it renders on top without occluding real nodes underneath.

        When `snapped` is True (the endpoint is locked to a nearby existing
        node), it's rendered with much higher opacity plus a highlight ring
        to clearly indicate the lock.
        """
        cam = self.camera
        p = cam.world_to_screen(node.pos)
        radius = NODE_RADIUS
        alpha = PREVIEW_NODE_ALPHA_SNAPPED if snapped else PREVIEW_NODE_ALPHA
        node_surf = pygame.Surface(self.surface.get_size(), pygame.SRCALPHA)
        pygame.draw.circle(node_surf, (*COLOR_NODE_PREVIEW, alpha), p, radius)
        if snapped:
            pygame.draw.circle(node_surf, (*COLOR_NODE_SELECTED, 255), p, radius + 4, 2)
        self.surface.blit(node_surf, (0, 0))

    def draw_visual_layers(self, layers):
        """
        Render generic, engine-provided visual instructions. The UI does
        not interpret what these mean (traffic, congestion, cars, zoning,
        debug, ...) -- it only knows how to draw a handful of primitive
        shapes in world space, supplied as plain dicts:

          {"shape": "circle",  "pos": (x, y), "radius": r,
           "color": (r,g,b), "alpha": 0-255}
          {"shape": "polygon", "points": [(x,y), ...],
           "color": (r,g,b), "alpha": 0-255, "outline": bool}
          {"shape": "line",    "points": [(x,y), ...],
           "color": (r,g,b), "width": px}
          {"shape": "sprite",  "pos": (x, y), "heading": (dx, dy),
           "length_ft": L, "image": path}
            -- an image whose source art points UP (head at the top),
               rotated to face `heading` and scaled so its length covers
               L world feet at the current zoom (aspect preserved).

        Unknown/malformed entries are ignored. Never reads/writes the
        graph, never persisted.
        """
        cam = self.camera
        for layer in layers:
            shape = layer.get("shape")
            color = layer.get("color", (255, 255, 255))
            alpha = layer.get("alpha", 255)
            if shape == "circle":
                p = cam.world_to_screen(layer["pos"])
                radius = max(1, layer.get("radius", 5) * cam.zoom)
                if alpha < 255:
                    surf = pygame.Surface(self.surface.get_size(), pygame.SRCALPHA)
                    pygame.draw.circle(surf, (*color, alpha), p, radius)
                    self.surface.blit(surf, (0, 0))
                else:
                    pygame.draw.circle(self.surface, color, p, radius)
            elif shape == "polygon":
                points = cam.world_to_screen_list(layer.get("points", []))
                if len(points) < 2:
                    continue
                if layer.get("outline"):
                    pygame.draw.polygon(self.surface, color, points, 2)
                elif alpha < 255:
                    surf = pygame.Surface(self.surface.get_size(), pygame.SRCALPHA)
                    pygame.draw.polygon(surf, (*color, alpha), points)
                    self.surface.blit(surf, (0, 0))
                else:
                    pygame.draw.polygon(self.surface, color, points)
            elif shape == "line":
                points = cam.world_to_screen_list(layer.get("points", []))
                if len(points) >= 2:
                    pygame.draw.lines(self.surface, color, False, points,
                                       layer.get("width", 2))
            elif shape == "sprite":
                base = self._sprite_base(layer.get("image"))
                if base is None:
                    continue
                p = cam.world_to_screen(layer["pos"])
                hx, hy = layer.get("heading", (0.0, -1.0))
                length_px = cam.feet_to_pixels(layer.get("length_ft", 14.0))
                scale = length_px / base.get_height()
                # Source art faces visually UP (= 90 deg in y-up screen
                # terms); rotozoom rotates counterclockwise, so rotate by
                # the heading's visual angle minus that baseline.
                angle = math.degrees(math.atan2(-hy, hx)) - 90.0
                key = layer.get("image")
                cached = self._sprite_rendered.get(key)
                if cached is None or abs(cached[0] - angle) > 0.25 \
                        or abs(cached[1] - scale) > 1e-3:
                    rendered = pygame.transform.rotozoom(base, angle, scale)
                    self._sprite_rendered[key] = (angle, scale, rendered)
                else:
                    rendered = cached[2]
                self.surface.blit(rendered, rendered.get_rect(center=p))

    def draw(self, network, preview_road, preview_geometry, preview_node, preview_snapped,
             pending_start_node, selected_road, hovered_node, selected_node,
             current_tool, debug, visual_layers=None, preview_snap_mode=None):
        self.surface.fill(COLOR_BG)

        for zone in network.zones.values():
            self.draw_zone(zone, debug)

        # Per-node collection of (left_edge_pt, right_edge_pt, surface_color)
        # contributed by each connected road's trimmed end -- the basis for
        # the lane-aware junction surface (replaces the old circular patch).
        junction_edge_points = {}
        junction_outer_points = {}

        for road in network.roads.values():
            geometry = network.geometry_for_road(road)
            surface_color = COLOR_ROAD_SURFACE_SELECTED if road is selected_road else COLOR_ROAD_SURFACE
            line_color = COLOR_ROAD_SELECTED if road is selected_road else COLOR_ROAD

            if not road.is_preview:
                start_trim = network.road_trim_at_node(road, road.start_node_id)
                end_trim = network.road_trim_at_node(road, road.end_node_id)
                if start_trim > 0 or end_trim > 0:
                    geometry = dict(geometry)
                    geometry["sampled_points"] = _trim_polyline(
                        geometry["sampled_points"], start_trim, end_trim)

                    profile = get_road_profile(road)
                    edge_color = EDGE_LINE_PRESETS.get(
                        profile.edge_line_style, EDGE_LINE_PRESETS["none"]).color
                    pts = geometry["sampled_points"]

                    has_outer = (profile.shoulder_type != SHOULDER_NONE and profile.shoulder_width > 0)

                    shoulder_width = profile.shoulder_width if has_outer else 0.0
                    outer_color = SHOULDER_COLORS.get(profile.shoulder_type, (120, 120, 120))

                    def _add_junction_entry(target, node_id, trim_point, outward, left_width, right_width, color, shoulder_width=0.0, outer_color=None):
                        # left/right via a consistent convention based on the
                        # OUTWARD tangent (away from the node, back into the
                        # road): rotate +90 deg for "left". left_width/
                        # right_width are each side's own offset from the
                        # (immutable) centerline -- never a shared half-width
                        # -- so an asymmetric profile produces an asymmetric
                        # junction edge.
                        perp = (-outward[1], outward[0])
                        left = (trim_point[0] + perp[0] * left_width, trim_point[1] + perp[1] * left_width)
                        right = (trim_point[0] - perp[0] * right_width, trim_point[1] - perp[1] * right_width)
                        target.setdefault(node_id, []).append(
                            {"left": left, "right": right, "outward": outward, "color": color,
                             "shoulder_width": shoulder_width, "outer_color": outer_color})

                    if start_trim > 0 and len(pts) >= 2:
                        outward = _normalize2(pts[1][0] - pts[0][0], pts[1][1] - pts[0][1])
                        _add_junction_entry(junction_edge_points, road.start_node_id,
                                             pts[0], outward, profile.left_width(), profile.right_width(), edge_color,
                                             shoulder_width, outer_color)
                    if end_trim > 0 and len(pts) >= 2:
                        # At the end node the "outward" tangent points back
                        # toward the start (opposite of the forward
                        # direction), which flips the perpendicular -- swap
                        # left_width/right_width so each entry point still
                        # gets its correct (asymmetric) physical-side width.
                        outward = _normalize2(pts[-2][0] - pts[-1][0], pts[-2][1] - pts[-1][1])
                        _add_junction_entry(junction_edge_points, road.end_node_id,
                                             pts[-1], outward, profile.right_width(), profile.left_width(), edge_color,
                                             shoulder_width, outer_color)

            self.draw_road(network, road, geometry, line_color, surface_color, 255, debug,
                            selected=(road is selected_road))

        # Sidewalk/shoulder junction surfaces: same fillet-merge as the
        # carriageway, but at full profile width and in the shoulder's
        # color. Drawn FIRST so the narrower asphalt polygon sits on top,
        # leaving a curved sidewalk/shoulder ring around the corners --
        # exactly mirroring how each road's own shoulder strip wraps its
        # asphalt edge.
        for node_id, entries in junction_edge_points.items():
            if len(entries) < 2:
                continue
            if not any(e.get("shoulder_width", 0.0) > 0 for e in entries):
                continue
            outer_entries = []
            for e in entries:
                sw = e.get("shoulder_width", 0.0)
                perp = (-e["outward"][1], e["outward"][0])
                outer_entries.append({
                    "left": (e["left"][0] + perp[0] * sw, e["left"][1] + perp[1] * sw),
                    "right": (e["right"][0] - perp[0] * sw, e["right"][1] - perp[1] * sw),
                    "outward": e["outward"],
                    "color": e["outer_color"] if sw > 0 else e["color"],
                })
            if len(entries) == 2:
                # 2-road continuation with differing widths: width-taper
                # surface (S-curve edges), not a corner-fillet junction.
                polygon, outer_edge_lines = _build_taper_polygon(outer_entries)
            else:
                polygon, outer_edge_lines = _build_junction_polygon(outer_entries, network.nodes[node_id].pos)
            color = next(e["outer_color"] for e in entries if e.get("shoulder_width", 0.0) > 0)
            pygame.draw.polygon(self.surface, color, self.camera.world_to_screen_list(polygon))

            # Curb-return curves: the outer (sidewalk/shoulder) boundary
            # also gets a smooth connecting curve between each pair of
            # trimmed edges, derived the same way as the asphalt edge
            # connectors -- giving the classic "curb wraps around the
            # corner" look instead of a sharp/abrupt sidewalk edge.
            for curve_points, _color in outer_edge_lines:
                screen_pts = self.camera.world_to_screen_list(curve_points)
                if len(screen_pts) >= 2:
                    pygame.draw.lines(self.surface, COLOR_CURB, False, screen_pts, 1)

        # Lane-aware junction surfaces: merge each intersection's incident
        # road edges into a single polygon (sorted by angle around the
        # node). Where two DIFFERENT roads' edges meet, the straight chord
        # between them is replaced with a tangent-continuous Bezier fillet,
        # so the junction boundary curves smoothly out of each road's edge
        # instead of a straight-line/circular patch.
        for node_id, entries in junction_edge_points.items():
            if len(entries) < 2:
                continue
            if len(entries) == 2:
                polygon, edge_lines = _build_taper_polygon(entries)
            else:
                polygon, edge_lines = _build_junction_polygon(entries, network.nodes[node_id].pos)

            screen_polygon = self.camera.world_to_screen_list(polygon)
            pygame.draw.polygon(self.surface, COLOR_ROAD_SURFACE, screen_polygon)

            # Outer edge-line connectors: continue each road's edge marking
            # through the junction along the same curved fillet.
            for curve_points, color in edge_lines:
                screen_pts = self.camera.world_to_screen_list(curve_points)
                if len(screen_pts) >= 2:
                    pygame.draw.lines(self.surface, color, False, screen_pts, 1)

        # Rounded dead-end caps: nodes with exactly one connected road get a
        # circular pavement cap (radius = full profile width / 2) so the
        # road end isn't a flat-cut polygon edge.
        for node in network.nodes.values():
            roads = [r for r in network.roads_for_node(node.id) if not r.is_preview]
            if len(roads) == 1:
                radius_ft = get_road_profile(roads[0]).total_width() / 2.0
                p = self.camera.world_to_screen(node.pos)
                radius_px = self.camera.feet_to_pixels(radius_ft)
                pygame.draw.circle(self.surface, COLOR_ROAD_SURFACE, p, radius_px)

        # Road Marking Renderer pass: runs after all surfaces/junction/cap
        # patches are painted, so markings sit cleanly on top and remain
        # fully independent of surface geometry. Uses the FULL (untrimmed)
        # centerline so markings run continuously into junctions/caps.
        for road in network.roads.values():
            self.draw_road_markings(network, road, network.geometry_for_road(road))

        # Generic engine-provided overlays (lane graph, future congestion/
        # traffic layers) render above the finished road surfaces and
        # markings but below nodes/previews/UI, so they're visible without
        # obscuring interactive elements.
        if visual_layers:
            self.draw_visual_layers(visual_layers)

        for node in network.nodes.values():
            color = COLOR_NODE_HOVER if node is hovered_node else COLOR_NODE
            ring_color = COLOR_NODE_SELECTED if node is selected_node else None
            self.draw_node(node, color, debug, ring_color=ring_color)

        if preview_road is not None and preview_geometry is not None:
            self.draw_road(network, preview_road, preview_geometry,
                            COLOR_ROAD_PREVIEW, COLOR_ROAD_PREVIEW, 140, debug)
            # Snap Mode overlay feedback: centerline drawn over the ghost
            # preview only -- white for a straight preview, cyan for a
            # curved one. Committed roads are rendered exactly as before.
            if preview_snap_mode is not None:
                line_pts = self.camera.world_to_screen_list(
                    preview_geometry["sampled_points"])
                if len(line_pts) >= 2:
                    pygame.draw.lines(
                        self.surface, SnapModeController.preview_color(preview_snap_mode),
                        False, line_pts, 2)

        if pending_start_node is not None:
            p = self.camera.world_to_screen(pending_start_node.pos)
            pygame.draw.circle(self.surface, COLOR_ROAD_PREVIEW, p,
                                NODE_RADIUS + 4, 2)

        # Drawn last so the semi-transparent preview endpoint sits on top
        # of everything without hiding real nodes underneath.
        if preview_node is not None:
            self.draw_preview_node(preview_node, snapped=preview_snapped)

        if debug:
            info = self.font.render(
                f"Tool: {current_tool} | Zoom: {self.camera.zoom:.2f}x | "
                "D: debug | Esc: cancel | Wheel: zoom/curvature | RMB-drag: pan | F11: fullscreen",
                True, COLOR_DEBUG_TEXT)
            self.surface.blit(info, (10, 10))

        self.scale_bar.draw(self.surface, self.font, self.camera,
                             self.surface.get_rect())

        # Watchdog overlay: read-only diagnostics, debug mode only. Marks
        # suspicious geometry (crossings without nodes, collapsed trims,
        # degenerate widths) WITHOUT changing any geometry.
        if debug:
            self.draw_watchdog_overlay(detect_geometry_issues(network))

        # Lane-count context menu for the selected road (TOOL_SELECT only).
        self.lane_menu_buttons = []
        if current_tool == TOOL_SELECT and selected_road is not None and not selected_road.is_preview:
            self.draw_lane_menu(network, selected_road)


class SnapSystem:
    """
    Centralized snapping: given a world position, returns the best valid
    snap position (a nearby existing node) for any placement preview.
    Visual-only -- never mutates the graph.
    """

    @staticmethod
    def find_snap_target(network, world_pos, camera, exclude_ids=None):
        exclude_ids = exclude_ids or set()
        snap_radius = SNAP_RADIUS / camera.zoom
        best = None
        best_dist = snap_radius
        for node in network.nodes.values():
            if node.id in exclude_ids:
                continue
            d = ((node.x - world_pos[0]) ** 2 + (node.y - world_pos[1]) ** 2) ** 0.5
            if d < best_dist:
                best_dist = d
                best = node
        return best


class PlacementManager:
    """
    Unified placement system. Owns:
      - placement-mode configuration per tool
      - step-based placement state (e.g. road = 2-step: pick A, pick B)
      - preview generation (delegates positions to SnapSystem)
      - final object creation (the only thing allowed to mutate the graph
        for a placement action)

    Tools only describe *what* is being placed via TOOL_CONFIGS; all
    interaction/state logic lives here.
    """

    TOOL_CONFIGS = {
        TOOL_NODE: {"object": "node", "steps": 1},
        TOOL_ROAD: {"object": "road", "steps": 2, "connect_existing": True},
    }

    def __init__(self, network, camera):
        self.network = network
        self.camera = camera
        self.active_tool = None

        # Step-based placement state (currently only used by the 2-step
        # "road" placement: pending_start_node is step 1's result).
        self.pending_start_node = None
        self.pending_start_was_new = False
        self.curve_offset = (0.0, 0.0)

        # Snap Mode overlay: only consulted when building the
        # road preview and committing a new road -- it never touches
        # existing roads or any other system. `last_preview_mode` mirrors
        # the most recent resolved preview mode (STRAIGHT/CURVE) purely so
        # the renderer can color the preview centerline; None when no road
        # preview is active.
        self.snap = SnapModeController()
        self.last_preview_mode = None

    def set_tool(self, tool_id):
        self.cancel()
        self.active_tool = tool_id if tool_id in self.TOOL_CONFIGS else None

    def cancel(self):
        if self.pending_start_node is not None and self.pending_start_was_new:
            del self.network.nodes[self.pending_start_node.id]
        self.pending_start_node = None
        self.pending_start_was_new = False
        self.curve_offset = (0.0, 0.0)
        self.last_preview_mode = None

    def _incoming_direction(self):
        """Continuation context for AUTO snap mode: when the pending start
        node has exactly one committed road attached, return the unit
        direction a smooth continuation of that road would travel (into the
        new road). Otherwise None. Read-only on the network."""
        if self.pending_start_node is None:
            return None
        roads = [r for r in self.network.roads_for_node(self.pending_start_node.id)
                 if not r.is_preview]
        if len(roads) != 1:
            return None
        out = self.network.outward_tangent_at_node(roads[0], self.pending_start_node.id)
        if out == (0.0, 0.0):
            return None
        return (-out[0], -out[1])

    def _resolve_snap_offset(self, end_pos):
        """Run the manual wheel offset through the Snap Mode overlay (with
        live Shift/Ctrl modifier overrides) for the current placement.
        Returns (curve_offset, resolved_mode)."""
        mods = pygame.key.get_mods()
        return self.snap.resolve_offset(
            self.pending_start_node.pos, end_pos, self.curve_offset,
            incoming_dir=self._incoming_direction(),
            shift_held=bool(mods & pygame.KMOD_SHIFT),
            ctrl_held=bool(mods & pygame.KMOD_CTRL))

    def _snap_exclude_ids(self):
        if self.pending_start_node is not None:
            return {self.pending_start_node.id}
        return set()

    def handle_click(self, world_pos):
        """Route a placement click to the active tool's object creation."""
        config = self.TOOL_CONFIGS.get(self.active_tool)
        if config is None:
            return

        if config["object"] == "node":
            self.network.add_node(*world_pos)

        elif config["object"] == "road":
            hit_radius = NODE_HIT_RADIUS / self.camera.zoom
            existing = self.network.node_at(*world_pos, radius=hit_radius)

            if self.pending_start_node is None:
                if existing is not None:
                    self.pending_start_node = existing
                    self.pending_start_was_new = False
                    self.curve_offset = (0.0, 0.0)
                # Empty space with nothing pending: no-op.
            else:
                if existing is None:
                    self.cancel()
                    return
                if existing.id == self.pending_start_node.id:
                    return
                # Snap Mode overlay: the committed road uses the SAME
                # resolved offset as the live preview, so what you see is
                # what you get. Only minimal metadata is stored; geometry
                # stays fully procedural from node positions + curve_offset.
                final_offset, resolved_mode = self._resolve_snap_offset(existing.pos)
                road = self.network.add_road(self.pending_start_node.id, existing.id,
                                              final_offset)
                road.data["snap"] = SnapModeController.metadata(
                    self.pending_start_node.pos, existing.pos, final_offset, resolved_mode)
                self.cancel()

    def handle_wheel(self, event, world_pos):
        """Curvature nudge for an in-progress road placement. Returns True
        if it consumed the wheel event (caller should not also zoom)."""
        if self.active_tool == TOOL_ROAD and self.pending_start_node is not None:
            # In (effective) STRAIGHT snap mode the wheel can't bend the
            # preview anyway -- let it fall through to camera zoom instead
            # of silently accumulating an invisible offset.
            mods = pygame.key.get_mods()
            effective = self.snap.effective_mode(
                bool(mods & pygame.KMOD_SHIFT), bool(mods & pygame.KMOD_CTRL))
            if effective == SNAP_STRAIGHT:
                return False
            ox, oy = self.curve_offset
            start = self.pending_start_node.pos
            px, py = _perpendicular(world_pos[0] - start[0], world_pos[1] - start[1])
            self.curve_offset = (ox + px * event.y * CURVATURE_STEP,
                                  oy + py * event.y * CURVATURE_STEP)
            return True
        return False

    def get_preview(self, world_pos):
        """
        Universal ghost-preview generation. Returns
        (preview_road, preview_geometry, preview_node, snapped).

        Snap System provides the candidate position for every preview;
        nothing here is added to the graph or saved.
        """
        config = self.TOOL_CONFIGS.get(self.active_tool)
        if config is None:
            self.last_preview_mode = None
            return None, None, None, False

        snap_target = SnapSystem.find_snap_target(
            self.network, world_pos, self.camera, self._snap_exclude_ids())
        pos = snap_target.pos if snap_target is not None else world_pos
        snapped = snap_target is not None

        if config["object"] == "road" and self.pending_start_node is not None:
            # Snap Mode overlay decides the offset the preview is built
            # with (straight line / bezier bulge / auto), wrapping -- not
            # replacing -- the manual wheel offset. Same geometry function
            # as committed roads, as before.
            final_offset, resolved_mode = self._resolve_snap_offset(pos)
            self.last_preview_mode = resolved_mode
            preview_node = Node(id=-1, x=pos[0], y=pos[1])
            preview_road = Road(
                id=-1,
                start_node_id=self.pending_start_node.id,
                end_node_id=-1,
                curve_offset=final_offset,
                is_preview=True,
            )
            geometry = compute_road_geometry(
                self.pending_start_node.pos, preview_node.pos, final_offset
            )
            return preview_road, geometry, preview_node, snapped

        self.last_preview_mode = None

        if config["object"] == "node":
            preview_node = Node(id=-1, x=pos[0], y=pos[1])
            return None, None, preview_node, snapped

        return None, None, None, False


class InputController:
    """
    Central input router. handle_event() dispatches every pygame event to
    either camera controls (pan/zoom, available in any tool) or the
    behavior for the currently active tool (TOOL_SELECT or TOOL_ROAD).

    Tool State System:
      current_tool in {TOOL_SELECT, TOOL_ROAD, TOOL_ZONE}. Only one is
      active at a time. set_tool() clears any in-progress
      interaction/selection state from the previous tool.

    State machine (TOOL_ROAD):
      idle -> (left click) -> placing (pending_start_node set)
      placing -> (mouse move) -> live preview road updates
      placing -> (scroll) -> preview curvature adjusts
      placing -> (left click) -> commit node + road, back to idle
      placing -> (Esc) -> cancel, back to idle (discard temp start node
                 if it was newly created for this placement)
    """

    def __init__(self, network, camera):
        self.network = network
        self.camera = camera
        self.current_tool = TOOL_SELECT

        self.placement = PlacementManager(network, camera)

        self.dragging_node = None
        self.dragging_control_point = False
        self.panning = False
        self.pan_last_screen_pos = None

        self.selected_road = None
        self.selected_node = None
        self.hovered_node = None

        # A node that was pressed but hasn't yet moved past the drag
        # threshold -- used to distinguish a click (select/chain) from a
        # drag (move node).
        self.mousedown_node = None
        self.mousedown_pos = None

        self.debug = False
        self.status_message = ""
        self.sidebar_scroll = 0
        # Lane-graph debug visualization (G key): read-only overlay built
        # from the committed network each frame while enabled.
        self.show_lane_graph = False
        # Traffic simulation (V key): single demo vehicle following a
        # precomputed Dijkstra lane path. Read-only on the network.
        self.traffic = TrafficSimulation(network)

    # ------------------------------------------------------------------
    # Tool state system
    # ------------------------------------------------------------------
    def set_tool(self, tool_id):
        if tool_id == self.current_tool:
            return
        if tool_id not in (TOOL_SELECT, TOOL_NODE, TOOL_ROAD, TOOL_ZONE):
            return
        if tool_id == TOOL_ZONE:
            self.status_message = "Zone tool is coming in Phase 3.1"
            return
        self.placement.set_tool(tool_id)
        self.dragging_node = None
        self.dragging_control_point = False
        self.mousedown_node = None
        self.mousedown_pos = None
        self.selected_road = None
        self.selected_node = None
        self.current_tool = tool_id
        self.status_message = f"Switched to {tool_id.replace('_', ' ')}"

    # ------------------------------------------------------------------
    # Central event routing
    # ------------------------------------------------------------------
    def handle_event(self, event, world_pos, screen_pos):
        if event.type == pygame.KEYDOWN:
            self._handle_key(event)
        elif event.type == pygame.MOUSEBUTTONDOWN:
            self._handle_mouse_down(event, world_pos, screen_pos)
        elif event.type == pygame.MOUSEBUTTONUP:
            self._handle_mouse_up(event, world_pos, screen_pos)
        elif event.type == pygame.MOUSEMOTION:
            self._handle_mouse_motion(world_pos, screen_pos)
        elif event.type == pygame.MOUSEWHEEL:
            self._handle_wheel(event, world_pos, screen_pos)

    def _handle_key(self, event):
        if event.key == pygame.K_d:
            self.debug = not self.debug
        elif event.key == pygame.K_g:
            self.show_lane_graph = not self.show_lane_graph
            self.status_message = ("Lane graph: on" if self.show_lane_graph
                                    else "Lane graph: off")
        elif event.key == pygame.K_v:
            self.status_message = self.traffic.toggle_demo_vehicle()
            print(self.status_message)
        elif event.key == pygame.K_ESCAPE:
            self.placement.cancel()
        elif event.key == pygame.K_s:
            self.save_to_file()
        elif event.key == pygame.K_l:
            self.load_from_file()
        elif event.key in (pygame.K_1, pygame.K_2, pygame.K_3):
            # Snap Mode overlay: while the New Road tool is active, 1/2/3
            # select the snap mode (Auto/Straight/Curved). In every other
            # tool they keep their original meaning (tool switching).
            if self.current_tool == TOOL_ROAD:
                mode = {pygame.K_1: SNAP_AUTO, pygame.K_2: SNAP_STRAIGHT,
                        pygame.K_3: SNAP_CURVE}[event.key]
                self.placement.snap.set_mode(mode)
                self.status_message = f"Snap mode: {SNAP_MODE_LABELS[mode]}"
            else:
                tool = {pygame.K_1: TOOL_SELECT, pygame.K_2: TOOL_NODE,
                        pygame.K_3: TOOL_ROAD}[event.key]
                self.set_tool(tool)

    # ------------------------------------------------------------------
    # Mouse buttons
    # ------------------------------------------------------------------
    def _handle_mouse_down(self, event, world_pos, screen_pos):
        if event.button == 1:
            if self.current_tool == TOOL_SELECT:
                self._select_tool_left_down(world_pos)
            elif self.current_tool in (TOOL_NODE, TOOL_ROAD):
                self.placement.handle_click(world_pos)
        elif event.button == 3:
            # Right-click + drag pans the camera, in any tool.
            self.panning = True
            self.pan_last_screen_pos = screen_pos

    def _handle_mouse_up(self, event, world_pos, screen_pos):
        if event.button == 1:
            if self.dragging_node is None and self.mousedown_node is not None:
                # Released without crossing the drag threshold -> a click.
                self._handle_node_click(self.mousedown_node)
            self.dragging_node = None
            self.dragging_control_point = False
            self.mousedown_node = None
            self.mousedown_pos = None
        elif event.button == 3:
            self.panning = False
            self.pan_last_screen_pos = None

    # ------------------------------------------------------------------
    # Mouse motion
    # ------------------------------------------------------------------
    def _handle_mouse_motion(self, world_pos, screen_pos):
        if self.panning and self.pan_last_screen_pos is not None:
            dx = screen_pos[0] - self.pan_last_screen_pos[0]
            dy = screen_pos[1] - self.pan_last_screen_pos[1]
            self.camera.pan(dx, dy)
            self.pan_last_screen_pos = screen_pos
            return

        if self.dragging_node is not None:
            self.dragging_node.x, self.dragging_node.y = world_pos
        elif self.dragging_control_point and self.selected_road is not None:
            self.network.set_curve_offset_from_control_point(self.selected_road, world_pos)
        elif self.mousedown_node is not None:
            dx = world_pos[0] - self.mousedown_pos[0]
            dy = world_pos[1] - self.mousedown_pos[1]
            threshold = NODE_DRAG_THRESHOLD / self.camera.zoom
            if (dx * dx + dy * dy) ** 0.5 > threshold:
                self.dragging_node = self.mousedown_node
                self.mousedown_node = None
                self.dragging_node.x, self.dragging_node.y = world_pos
        else:
            hit_radius = NODE_HIT_RADIUS / self.camera.zoom
            self.hovered_node = self.network.node_at(*world_pos, radius=hit_radius)

    # ------------------------------------------------------------------
    # Mouse wheel: curvature nudge takes priority over camera zoom when
    # actively previewing/editing a curve; otherwise zoom around cursor.
    # ------------------------------------------------------------------
    def _handle_wheel(self, event, world_pos, screen_pos):
        if self.placement.handle_wheel(event, world_pos):
            return

        if self.current_tool == TOOL_SELECT and self.selected_road is not None:
            road = self.selected_road
            start = self.network.nodes[road.start_node_id].pos
            end = self.network.nodes[road.end_node_id].pos
            px, py = _perpendicular(end[0] - start[0], end[1] - start[1])
            ox, oy = road.curve_offset
            road.curve_offset = (ox + px * event.y * CURVATURE_STEP,
                                  oy + py * event.y * CURVATURE_STEP)
            return

        # Otherwise: zoom the camera around the cursor.
        factor = ZOOM_STEP if event.y > 0 else (1.0 / ZOOM_STEP)
        self.camera.zoom_at(screen_pos, factor)

    # ------------------------------------------------------------------
    # TOOL_SELECT behavior
    # ------------------------------------------------------------------
    def _select_tool_left_down(self, world_pos):
        # Control-point grab takes priority when a road is selected.
        if self.selected_road is not None:
            cp = self.network.control_point_for_road(self.selected_road)
            hit_radius = CONTROL_POINT_HIT_RADIUS / self.camera.zoom
            dist = ((cp[0] - world_pos[0]) ** 2 + (cp[1] - world_pos[1]) ** 2) ** 0.5
            if dist <= hit_radius:
                self.dragging_control_point = True
                return

        hit_radius = NODE_HIT_RADIUS / self.camera.zoom
        existing = self.network.node_at(*world_pos, radius=hit_radius)
        if existing is not None:
            # Don't decide drag-vs-click yet -- motion/up resolves it.
            self.mousedown_node = existing
            self.mousedown_pos = world_pos
            self.selected_road = None
            return

        road_threshold = 6 / self.camera.zoom
        road = self.network.road_at(world_pos[0], world_pos[1], threshold=road_threshold)
        if road is not None:
            self.selected_road = road
            self.selected_node = None
            return

        # Empty space: deselect everything.
        self.selected_road = None
        self.selected_node = None

    def _handle_node_click(self, node):
        """A plain click (no drag) on an existing node, in TOOL_SELECT: select it."""
        if self.current_tool != TOOL_SELECT:
            return
        if self.selected_node is not None and self.selected_node.id == node.id:
            self.selected_node = None
        else:
            self.selected_node = node
            self.selected_road = None

    # ------------------------------------------------------------------
    # Save / load
    # ------------------------------------------------------------------
    def save_to_file(self, filepath=MAP_SAVE_PATH):
        """Save the single active RoadNetwork instance to JSON."""
        save_map(self.network, filepath)
        self.status_message = f"Saved to {filepath}"
        print(self.status_message)

    def load_from_file(self, filepath=MAP_SAVE_PATH):
        """
        Load JSON into the active RoadNetwork instance (mutated in place,
        so it remains the single source of truth -- no new RoadNetwork is
        created). Clears all transient editor/selection state since old
        node/road object references are no longer valid after the reload.
        """
        if not os.path.exists(filepath):
            self.status_message = f"No save file found at {filepath}"
            print(self.status_message)
            return

        load_map(self.network, filepath)

        # Old vehicle paths reference replaced road/node objects.
        self.traffic.reset()
        self.placement.cancel()
        self.dragging_node = None
        self.dragging_control_point = False
        self.mousedown_node = None
        self.mousedown_pos = None
        self.hovered_node = None
        self.selected_road = None

        self.status_message = f"Loaded from {filepath}"
        print(self.status_message)

    # ------------------------------------------------------------------
    # Placement (delegated to PlacementManager)
    # ------------------------------------------------------------------
    @property
    def pending_start_node(self):
        return self.placement.pending_start_node

    def get_preview(self, world_pos):
        return self.placement.get_preview(world_pos)

    def get_context_hint(self):
        """Read-only UI hint derived from current tool/placement state."""
        if self.current_tool == TOOL_NODE:
            return "Click to place node"
        if self.current_tool == TOOL_ROAD:
            if self.placement.pending_start_node is None:
                return "Click a node to start a road"
            return "Click second node to create road (Esc to cancel)"
        if self.current_tool == TOOL_SELECT:
            if self.selected_road is not None:
                return "Drag red dot to bend curve, scroll to nudge"
            if self.selected_node is not None:
                return "Drag node to move it"
            return "Click a node or road to select"
        if self.current_tool == TOOL_ZONE:
            return "Zone tool coming soon"
        return ""

    def get_visual_layers(self):
        """
        Extensibility hook for the Visual Data Layer: returns a list of
        generic shape dicts (see RoadRenderer.draw_visual_layers) for the
        renderer to draw, with no interpretation by the UI.

        Currently populated by the lane-graph debug overlay (G key) and
        the traffic simulation's vehicle/path overlay (V key), both
        rebuilt read-only from the committed network. Future engine
        systems (congestion, zoning) can append their own layers here.
        """
        layers = []
        if self.show_lane_graph:
            graph = build_lane_graph(self.network)
            layers += lane_graph_visual_layers(self.network, graph)
        layers += self.traffic.visual_layers()
        return layers


def _handle_lane_menu_click(renderer, selected_road, screen_pos):
    """Check the lane-count menu's +/- buttons for a hit; if hit, mutate the
    selected road's profile (lane_count_forward/reverse) and return True.
    Returns False if the click missed all buttons (caller falls through to
    normal selection handling)."""
    if selected_road is None:
        return False
    for rect, key, sign in renderer.lane_menu_buttons:
        if rect.collidepoint(screen_pos):
            profile = get_road_profile(selected_road)
            current = profile.lanes_forward() if key == "lane_count_forward" else profile.lanes_reverse()
            new_value = max(1, min(6, current + sign))
            profile_data = dict(selected_road.data.get("profile") or {})
            profile_data[key] = new_value
            selected_road.data["profile"] = profile_data
            # Geometry/markings/junctions are all recomputed live from
            # road.data each frame -- no caches to invalidate, and the
            # centerline (start/end nodes + curve_offset) is untouched, so
            # the road does not move.
            return True
    return False


def _compute_layout(window_size):
    """Pure layout helper: given the window size, return (canvas_rect,
    sidebar_rect). Sidebar keeps a fixed width; canvas fills the rest."""
    width, height = window_size
    canvas_width = max(1, width - SIDEBAR_WIDTH)
    canvas_rect = pygame.Rect(0, 0, canvas_width, height)
    sidebar_rect = pygame.Rect(canvas_width, 0, width - canvas_width, height)
    return canvas_rect, sidebar_rect


def main():
    pygame.init()
    window_size = (CANVAS_WIDTH + SIDEBAR_WIDTH, CANVAS_HEIGHT)
    screen = pygame.display.set_mode(window_size, pygame.RESIZABLE)
    pygame.display.set_caption("Road Editor - Phase 3")
    clock = pygame.time.Clock()
    font = pygame.font.SysFont("monospace", 14)
    header_font = pygame.font.SysFont("monospace", 16, bold=True)

    fullscreen = False
    windowed_size = window_size

    canvas_rect, sidebar_rect = _compute_layout(window_size)
    canvas = screen.subsurface(canvas_rect)

    network = RoadNetwork()
    camera = Camera()
    camera.set_viewport(canvas_rect.width, canvas_rect.height)
    controller = InputController(network, camera)
    renderer = RoadRenderer(canvas, font, camera)
    toolbar = Toolbar(font)
    sidebar = Sidebar(screen, font, header_font, toolbar)

    # Startup: load the previous session's map into the active network if
    # a save file exists, otherwise start with an empty map.
    if os.path.exists(MAP_SAVE_PATH):
        controller.load_from_file()
    else:
        controller.status_message = f"No save file found, starting empty ({MAP_SAVE_PATH})"

    running = True
    while running:
        raw_screen_pos = pygame.mouse.get_pos()
        screen_pos = (min(raw_screen_pos[0], canvas_rect.width - 1), raw_screen_pos[1])
        in_canvas = raw_screen_pos[0] < canvas_rect.width
        world_pos = camera.screen_to_world(screen_pos)

        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                running = False

            elif event.type == pygame.VIDEORESIZE and not fullscreen:
                window_size = (max(event.w, MIN_WINDOW_WIDTH), max(event.h, MIN_WINDOW_HEIGHT))
                windowed_size = window_size
                screen = pygame.display.set_mode(window_size, pygame.RESIZABLE)
                canvas_rect, sidebar_rect = _compute_layout(window_size)
                canvas = screen.subsurface(canvas_rect)
                renderer.surface = canvas
                camera.set_viewport(canvas_rect.width, canvas_rect.height)

            elif event.type == pygame.KEYDOWN and event.key == pygame.K_F11:
                # Fullscreen toggle: rendering/layout only -- camera
                # position and zoom are untouched.
                fullscreen = not fullscreen
                if fullscreen:
                    info = pygame.display.Info()
                    window_size = (info.current_w, info.current_h)
                    screen = pygame.display.set_mode(window_size, pygame.FULLSCREEN)
                else:
                    window_size = windowed_size
                    screen = pygame.display.set_mode(window_size, pygame.RESIZABLE)
                canvas_rect, sidebar_rect = _compute_layout(window_size)
                canvas = screen.subsurface(canvas_rect)
                renderer.surface = canvas
                sidebar.surface = screen
                camera.set_viewport(canvas_rect.width, canvas_rect.height)

            elif event.type in (pygame.MOUSEBUTTONDOWN, pygame.MOUSEBUTTONUP) and not in_canvas:
                # Sidebar UI: toolbar buttons.
                if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
                    # Snap Mode overlay panel first; falls through to the
                    # toolbar buttons if the click missed it.
                    snap_clicked = sidebar.snap_panel.handle_click(raw_screen_pos)
                    if snap_clicked is not None:
                        controller.placement.snap.set_mode(snap_clicked)
                        controller.status_message = (
                            f"Snap mode: {SNAP_MODE_LABELS[snap_clicked]}")
                    else:
                        clicked = toolbar.handle_click(sidebar_rect, raw_screen_pos)
                        if clicked is not None:
                            kind, item_id = clicked
                            if kind == "tool":
                                controller.set_tool(item_id)
                            elif item_id == ACTION_SAVE:
                                controller.save_to_file()
                            elif item_id == ACTION_LOAD:
                                controller.load_from_file()

            elif event.type == pygame.MOUSEWHEEL and not in_canvas:
                # Sidebar UI: scroll the instructions panel.
                controller.sidebar_scroll = max(0, controller.sidebar_scroll - event.y * 20)

            elif (event.type == pygame.MOUSEBUTTONDOWN and event.button == 1
                  and in_canvas and renderer.lane_menu_buttons
                  and _handle_lane_menu_click(renderer, controller.selected_road, raw_screen_pos)):
                pass

            else:
                controller.handle_event(event, world_pos, screen_pos)

        camera.update()
        # Advance the traffic simulation by real elapsed time (ms since the
        # previous frame's tick). No-op when no vehicle is spawned.
        controller.traffic.update(clock.get_time() / 1000.0)

        hovered = None if in_canvas else toolbar.handle_hover(sidebar_rect, raw_screen_pos)

        preview_road, preview_geometry, preview_node, preview_snapped = controller.get_preview(world_pos)

        renderer.draw(
            network,
            preview_road, preview_geometry, preview_node, preview_snapped,
            controller.pending_start_node,
            controller.selected_road,
            controller.hovered_node,
            controller.selected_node,
            controller.current_tool,
            controller.debug,
            visual_layers=controller.get_visual_layers(),
            preview_snap_mode=controller.placement.last_preview_mode,
        )

        sidebar.draw(sidebar_rect, controller.current_tool,
                      controller.status_message, controller.sidebar_scroll,
                      controller.get_context_hint(), hovered=hovered,
                      snap_mode=controller.placement.snap.mode)

        pygame.display.flip()
        clock.tick(60)

    pygame.quit()
    sys.exit()


if __name__ == "__main__":
    main()
