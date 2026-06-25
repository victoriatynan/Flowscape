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
  before; geometry generation is untouched. Camera.world_to_screen() /
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
import random
import sys
import pygame

import palette
import road_style
from road_geometry import (Node, Road, Zone, compute_road_geometry, _perpendicular,
                            compute_control_point, compute_road_edges, compute_road_polygon,
                            sample_cubic_bezier)
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
from destinations import (RESIDENTIAL, OFFICE, RETAIL, SCHOOL, RECREATION,
                          SMALL, MEDIUM, LARGE, BUILDING_TYPES, generate_trips)
from sim_clock import TripScheduler
from test_city import create_test_city


NODE_RADIUS = 8
NODE_HIT_RADIUS = 12
CURVATURE_STEP = 8.0

MAP_SAVE_PATH = "map_save.json"

# Building footprint rendering (UI only: reads BuildingType data, draws it).
BUILDING_CATEGORY_COLORS = {
    RESIDENTIAL: (95, 175, 95),
    OFFICE: (90, 135, 215),
    RETAIL: (225, 165, 75),
    SCHOOL: (210, 95, 95),
    RECREATION: (120, 200, 135),
}
BUILDING_DEFAULT_COLOR = (180, 180, 180)
BUILDING_SIZE_FT = {SMALL: 30.0, MEDIUM: 55.0, LARGE: 80.0}
BUILDING_FILL_ALPHA = 150
# Building tool: ordered archetypes for the picker, placement offset/feel.
BUILDING_TYPE_ORDER = ["House", "Apartment", "Small Office", "Large Office",
                       "Store", "School", "Park"]
BUILDING_PLACE_OFFSET = 45.0    # ft: footprint sits this far off its node
BUILDING_PREVIEW_ALPHA = 90     # ghost footprint while the tool is active

# Trip demo (T key / Trips button): a watchable subset of the day's trips,
# played back over an accelerated clock. The full realistic count would be
# too many cars.
DEMO_TRIP_LIMIT = 300       # per DAY
DEMO_START_HOUR = 6.5
DEMO_HOURS_PER_SEC = 0.4
DEMO_SEED = 0               # base seed; each day uses DEMO_SEED + day_index
# "Trips at once": live cap on concurrent cars (slider). When at the cap, a
# due departure waits until a car finishes its trip.
TRIPS_AT_ONCE_MIN = 5
TRIPS_AT_ONCE_MAX = 120
TRIPS_AT_ONCE_DEFAULT = 40

CANVAS_WIDTH = 1024
# Tall enough that the full sidebar stack (big icon tiles + all panels +
# the Settings sliders) fits on screen at startup; window stays resizable.
CANVAS_HEIGHT = 920
SIDEBAR_WIDTH = 280
MIN_WINDOW_WIDTH = SIDEBAR_WIDTH + 320
MIN_WINDOW_HEIGHT = 240

ZOOM_MIN = 0.2
ZOOM_MAX = 5.0
ZOOM_STEP = 1.1

# UI-only reference scale for the map scale bar: at camera.zoom == 1.0,
# one world foot is rendered as WORLD_SCALE screen pixels. (World/geometry
# data is unaffected; this only feeds the scale-bar label/length.)
WORLD_SCALE = 3

SCALE_BAR_VALUES_FT = [10, 20, 50, 100, 200, 500]
SCALE_BAR_MAX_PX = 160
SCALE_BAR_MARGIN = 16
COLOR_SCALE_BAR = (230, 230, 230)
COLOR_SCALE_BAR_BG = (0, 0, 0)

TOOL_SELECT = "select_tool"
TOOL_NODE = "node_tool"
TOOL_ROAD = "new_road_tool"
TOOL_BUILDING = "building_tool"
TOOL_ZONE = "zone_tool"

ACTION_SAVE = "action_save"
ACTION_LOAD = "action_load"

TOOL_LABELS = {
    TOOL_SELECT: "Select Tool",
    TOOL_NODE: "Node Tool",
    TOOL_ROAD: "New Road Tool",
    TOOL_BUILDING: "Building Tool",
    TOOL_ZONE: "Zone Tool",
}

# UI-only tooltip content, keyed by toolbar item id (tool or action). The UI
# reads this table to render hover tooltips; it contains no engine logic.
TOOLTIPS = {
    TOOL_SELECT: ("Select Tool", "Select and edit nodes/roads",
                   "Click to select, drag to move/bend"),
    TOOL_NODE: ("Node Tool", "Place standalone nodes",
                "Click anywhere to place a node"),
    TOOL_ROAD: ("New Road Tool", "Connect two existing nodes",
                "Click node A, then node B"),
    TOOL_BUILDING: ("Building Tool", "Place a building on a road node",
                    "Pick a type, click a road node"),
    TOOL_ZONE: ("Zone Tool", "Draw zone polygons", "Coming soon"),
    ACTION_SAVE: ("Save Map", "Write the map to disk", f"Saves to {MAP_SAVE_PATH}"),
    ACTION_LOAD: ("Load Map", "Reload the map from disk", f"Loads from {MAP_SAVE_PATH}"),
}

# UI icons live in the sibling "2D Assets" folder (one level up from this
# package). Buttons with a mapped icon show the icon instead of a text label;
# everything else stays text. Missing/unloadable icons fall back to text.
_ICON_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "2D Assets")
_ICON_CACHE = {}

# Tool/button id -> icon filename (without .png).
TOOL_ICONS = {
    TOOL_SELECT: "MouseSelection-button",
    TOOL_NODE: "node-button",
    TOOL_ROAD: "roadpath-button",
}

# Icon-button tile size (matches the icons' ~1.2:1 shape), shared by the
# toolbar tools and the Sim-panel play/pause button so all icon buttons match.
# The icon IS the button: no background fill and no padding, so the tile equals
# the icon's bounds (incl. the dark outline baked into the art). 2x the old size.
ICON_TILE_W = 122
ICON_TILE_H = 102
ICON_TILE_PAD = 0
ICON_TILE_GAP = 4          # horizontal gap between icon tiles (fits 2 per row)
# The ACTIVE tool's icon is tinted pink (a multiplicative color "filter" that
# keeps the art's shading + transparency); inactive icons render normally.
COLOR_ICON_ACTIVE = (255, 110, 190)


def get_icon(name, target_h):
    """Load+cache a UI icon scaled to `target_h` px (aspect preserved).
    Returns a Surface, or None when the file is missing/unloadable so callers
    fall back to a text label. Requires the display to be initialized."""
    key = (name, int(target_h))
    if key in _ICON_CACHE:
        return _ICON_CACHE[key]
    surf = None
    try:
        img = pygame.image.load(os.path.join(_ICON_DIR, name + ".png")).convert_alpha()
        scale = target_h / img.get_height()
        surf = pygame.transform.smoothscale(
            img, (max(1, round(img.get_width() * scale)), int(target_h)))
    except (pygame.error, FileNotFoundError):
        surf = None
    _ICON_CACHE[key] = surf
    return surf

BUTTON_PRESS_DURATION_MS = 120

# COLOR RULE: from now on, every color used in Flowscape must come from the
# "fantasy-24" palette in palette.py (use palette.color("rrggbb") or
# palette.nearest(rgb)). The COLOR_* constants below predate that rule and are
# NOT yet palette-exact; migrate them to palette entries over time.
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
# Placement grid (snap nodes/road endpoints to a regular spacing). Logic lives
# in PlacementManager; the overlay below is a PLACEHOLDER visual only.
GRID_SIZES_FT = [10.0, 25.0, 50.0, 100.0, 200.0]
GRID_SIZE_DEFAULT = 50.0
# PLACEHOLDER ground-grid line color (faint). Replace the grid overlay with
# real tiled ground graphics later; this is the visual stand-in.
COLOR_GRID = (48, 52, 60)
# Procedural-graphics outline, mirroring the PNG icons' baked border: same
# dark color, and a width that's ~3.8% of the element's size (the icon's
# border / icon shorter-side ratio), floored so thin elements stay visible.
COLOR_OUTLINE = (37, 37, 37)
OUTLINE_RATIO = 0.038
OUTLINE_MIN_PX = 2
COLOR_ROAD = (90, 200, 255)
COLOR_ROAD_SELECTED = (255, 140, 0)
COLOR_ROAD_PREVIEW = (255, 210, 90)
COLOR_DEBUG_TEXT = (255, 255, 255)
CONTROL_POINT_RADIUS = 7
CONTROL_POINT_HIT_RADIUS = 10
COLOR_CONTROL_POINT = (255, 100, 100)
COLOR_GUIDE_LINE = (255, 255, 255)
COLOR_SAMPLE_POINT = (120, 255, 120)
# Road graphics in the icon style, all from the fantasy-24 palette (see
# palette.py). Layered look: dark outline -> asphalt -> thin lighter rim, with
# a lighter "frame" tone for shoulders. All road lines are drawn THICK
# (proportional to road width) to match the icons' heavy strokes.
# Tones are mid/light so the road reads against the dark background (the
# palette has no dark-gray asphalt that would contrast with near-black).
COLOR_ROAD_SURFACE = palette.color("684c3c")           # asphalt (inner panel)
COLOR_ROAD_SURFACE_SELECTED = palette.color("ab5c1c")  # selected asphalt
# Each road/junction picks one of these surface tones (stable per id), so the
# network has varied asphalt instead of one flat color.
ROAD_SURFACE_OPTIONS = [palette.color("684c3c"), palette.color("927e6a"),
                        palette.color("655e56"), palette.color("4e4843")]


def road_surface_color(obj_id):
    """Stable per-id asphalt tone (so a road keeps its color frame to frame)."""
    return ROAD_SURFACE_OPTIONS[obj_id % len(ROAD_SURFACE_OPTIONS)]


def set_road_knob(which, value):
    """Live-set one of the two road tuning knobs and return a status string.
    'line' -> ROAD_LINE_WEIGHT (this module); 'width' -> road_style's shared
    ROAD_WIDTH_SCALE (so cars/junctions/drawing scale together)."""
    global ROAD_LINE_WEIGHT
    if which == "line":
        ROAD_LINE_WEIGHT = value
        return f"Line weight: x{value:.1f}"
    road_style.ROAD_WIDTH_SCALE = value
    return f"Road width: x{value:.1f}"
COLOR_ROAD_FRAME = palette.color("927e6a")             # shoulder / outer frame
COLOR_ROAD_RIM = palette.color("927e6a")               # thin inner rim highlight
COLOR_ROAD_OUTLINE = palette.color("1f240a")           # heavy dark border
COLOR_ROAD_MARK_CENTER = palette.color("efac28")       # center line (amber)
COLOR_ROAD_MARK_EDGE = palette.color("efd8a1")         # edge/lane lines (cream)
ROAD_OUTLINE_RATIO = 0.12      # road border width as a fraction of road width
ROAD_MARK_RATIO = 0.10         # lane/edge line width as a fraction of carriageway
ROAD_LINE_MIN_PX = 2           # floor so lines stay visible when zoomed out
# KNOB 1: LINE WEIGHT. One multiplier on the thickness of ALL road lines
# (borders + lane/edge lines). 1.0 = as tuned above; raise it (e.g. 1.5, 2.0)
# for chunkier lines. Pair with ROAD_WIDTH_SCALE (Knob 2, in road_style.py):
# thicker lines usually want wider roads so the asphalt still shows between.
ROAD_LINE_WEIGHT = 2.3
COLOR_CENTERLINE_DEBUG = (90, 200, 255)
COLOR_LEFT_EDGE = (255, 80, 80)
COLOR_RIGHT_EDGE = (80, 120, 255)
COLOR_CURB = palette.color("684c3c")

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

    def add_building(self, x, y, connection_node_ids=None, building_type="House", data=None):
        building = Building(id=self._next_building_id, x=x, y=y,
                             building_type=building_type,
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
        """True for a junction node (3+ connected roads). 1 road is an
        endpoint, 2 a continuation bend; only 3+ gets junction pavement."""
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
    TAPER_MIN = 12.0        # ft; floor so even a small step eases visibly
    TAPER_WIDE_SETBACK = 0.5  # ft; token trim on the wider road's side

    def road_trim_at_node(self, road, node_id):
        """Distance (feet) to trim `road` back from `node_id`, derived from
        the road's OWN carriageway width (not a shared/uniform radius), so
        the gap left for the junction surface follows each road's actual
        edge geometry. 0 if the node isn't an intersection, except at a
        2-road continuation node joining different total widths, where the
        narrower road is trimmed by a taper length (and the wider by a
        token setback) so a width-transition surface can be drawn on the
        narrower road's side."""
        roads_here = self.roads_for_node(node_id)
        if (len(roads_here) == 2 and not road.is_preview
                and not any(r.is_preview for r in roads_here)
                and any(r.id == road.id for r in roads_here)):
            other = roads_here[0] if roads_here[1].id == road.id else roads_here[1]
            # Genuine continuation (mouths roughly opposing, bend <= ~90 deg)
            # gets the smooth continuation band below. Sharper folds are ROUNDED
            # into a curved bend: a circular-arc-style curve tangent to both
            # arms, whose centerline radius scales with the arm angle, tighter
            # for sharper folds, widening toward the 90 deg boundary, floored at
            # the half-width so the inner edge never inverts. Trim each road
            # back to that arc's tangent point so the curved band + lane
            # connectors (drawn through the SAME continuation path as >=90 deg
            # bends) have room, and the straight edges are cut past where they
            # would otherwise cross into a bowtie.
            out_self = self.outward_tangent_at_node(road, node_id)
            out_other = self.outward_tangent_at_node(other, node_id)
            cos_arm = max(-1.0, min(1.0, out_self[0] * out_other[0] + out_self[1] * out_other[1]))
            if cos_arm > 0.0:
                alpha = math.acos(cos_arm)               # arm angle (rad), < 90 deg
                half = get_road_profile(road).total_width() / 2.0
                radius = half * (1.0 + math.degrees(alpha) / 90.0)
                tan_half = math.tan(alpha / 2.0)
                tangent_len = radius / tan_half if tan_half > 1e-6 else radius
                start = self.nodes[road.start_node_id].pos
                end = self.nodes[road.end_node_id].pos
                road_len = math.hypot(end[0] - start[0], end[1] - start[1])
                # Use the full tangent length when the road can fit it; else
                # take as much as the road allows, leaving ~one road-width of
                # straight stub. A road too short even for this is a degenerate
                # near-hairpin (the watchdog flags trim_overflow).
                return min(tangent_len, max(0.0, road_len - 2.0 * half))
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
            # Equal-width continuation/bend: trim both roads back like a mini
            # junction so the bend gets a smooth connector surface + lane-line
            # connectors (instead of two straight quads notching/overlapping
            # at the node). Same trim law as an intersection corner.
            return self._general_trim(road, node_id)
        if not self.is_intersection(node_id):
            return 0.0
        return self._general_trim(road, node_id)

    def _general_trim(self, road, node_id):
        """Distance to pull `road`'s mouth back from `node_id` for a corner
        connector: half the carriageway (where the asphalt edge meets the
        junction) PLUS half the full profile width (the curb-return radius
        used for sidewalks/shoulders/edge lines), so the straight boundary
        geometry ends exactly where the corner curve begins."""
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
        """Set the road's curve_offset (vector from the start->end midpoint)
        so its control point lands at control_pos (world space)."""
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

    def building_at(self, x, y):
        """Topmost placed building whose footprint square contains (x, y),
        else None. Footprint size comes from the building's BuildingType."""
        for b in reversed(list(self.buildings.values())):
            bt = BUILDING_TYPES.get(b.building_type)
            half = (BUILDING_SIZE_FT.get(bt.size, 30.0) if bt else 30.0) / 2.0
            if abs(x - b.x) <= half and abs(y - b.y) <= half:
                return b
        return None

    def remove_road(self, road_id):
        """Remove a road. Nodes are left in place (they may become dead ends
        or orphans, which the editor already handles)."""
        self.roads.pop(road_id, None)

    def remove_node(self, node_id):
        """Remove a node and everything that cannot exist without it: its
        connected roads (cascade), plus references to it in any building's
        connection list (buildings stay placed, just detached)."""
        for road in list(self.roads_for_node(node_id)):
            self.roads.pop(road.id, None)
        for b in self.buildings.values():
            if node_id in b.connection_node_ids:
                b.connection_node_ids = [n for n in b.connection_node_ids if n != node_id]
        self.nodes.pop(node_id, None)

    def remove_building(self, building_id):
        self.buildings.pop(building_id, None)

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
        # Transforms don't depend on it, but it's the one value
        # anything (UI, future culling) reads when it needs it.
        self.viewport_width = CANVAS_WIDTH
        self.viewport_height = CANVAS_HEIGHT

    def set_viewport(self, width, height):
        """Update viewport size on resize/fullscreen. Position and zoom
        are left untouched; the world must not shift."""
        self.viewport_width = width
        self.viewport_height = height

    # Camera is the SINGLE conversion authority between world space (feet)
    # and screen space (pixels). Every other system (rendering, the
    # scale bar, hit-testing, placement) must go through these methods
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
    Basic UI shell at the top of the sidebar. Buttons that have a mapped icon
    (TOOL_ICONS) are drawn as icon TILES sized to the icon's aspect, packed
    into rows; buttons without an icon stay as full-width text bars below.
    Only one tool can be active at a time (InputController.current_tool).
    """

    BUTTON_HEIGHT = 32          # full-width text bars
    ICON_BTN_W = ICON_TILE_W    # icon tile (matches the icons' ~1.2:1 shape)
    ICON_BTN_H = ICON_TILE_H
    ICON_PAD = ICON_TILE_PAD
    ICON_GAP = ICON_TILE_GAP    # horizontal gap between icon tiles
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
            (TOOL_BUILDING, "Building Tool", True),
            (TOOL_ZONE, "Zone Tool (soon)", False),
        ]
        self.action_buttons = [
            (ACTION_SAVE, "Save Map", True),
            (ACTION_LOAD, "Load Map", True),
        ]

    def _items_layout(self, sidebar_rect):
        """Place every toolbar item, returning
        [(item_id, label, enabled, rect, kind, is_icon), ...]. Icon items pack
        into rows of tiles; non-icon items are full-width bars on their own
        line (closing any open icon row first)."""
        x0 = sidebar_rect.x + self.SIDE_MARGIN
        width = sidebar_rect.width - 2 * self.SIDE_MARGIN
        x, y = x0, sidebar_rect.y + self.TOP_MARGIN
        row_open = False
        out = []
        items = ([(b[0], b[1], b[2], "tool") for b in self.buttons]
                 + [(a[0], a[1], a[2], "action") for a in self.action_buttons])
        for item_id, label, enabled, kind in items:
            if item_id in TOOL_ICONS:
                if x + self.ICON_BTN_W > x0 + width:       # wrap the tile row
                    x, y = x0, y + self.ICON_BTN_H + self.BUTTON_GAP
                rect = pygame.Rect(x, y, self.ICON_BTN_W, self.ICON_BTN_H)
                out.append((item_id, label, enabled, rect, kind, True))
                x += self.ICON_BTN_W + self.ICON_GAP
                row_open = True
            else:
                if row_open:                               # close the tile row
                    x, y = x0, y + self.ICON_BTN_H + self.BUTTON_GAP
                    row_open = False
                rect = pygame.Rect(x0, y, width, self.BUTTON_HEIGHT)
                out.append((item_id, label, enabled, rect, kind, False))
                y += self.BUTTON_HEIGHT + self.BUTTON_GAP
        return out

    def full_bottom(self, sidebar_rect):
        items = self._items_layout(sidebar_rect)
        return max((it[3].bottom for it in items), default=sidebar_rect.y) + self.BUTTON_GAP

    def _button_color(self, item_id, enabled, active_id, hovered_id):
        now = pygame.time.get_ticks()
        pressed_active = self.pressed_id is not None and now < self.pressed_until
        if not enabled:
            return COLOR_BUTTON_DISABLED, COLOR_BUTTON_TEXT_DISABLED
        if item_id == active_id:
            return COLOR_BUTTON_ACTIVE, COLOR_BUTTON_TEXT       # active > hover > press
        if pressed_active and item_id == self.pressed_id:
            return COLOR_BUTTON_PRESSED, COLOR_BUTTON_TEXT
        if item_id == hovered_id:
            return COLOR_BUTTON_HOVER, COLOR_BUTTON_TEXT
        return COLOR_BUTTON, COLOR_BUTTON_TEXT

    def draw(self, surface, sidebar_rect, current_tool, hovered=None):
        hovered_id = hovered[1] if hovered is not None else None
        for item_id, label, enabled, rect, kind, is_icon in self._items_layout(sidebar_rect):
            # Only tool buttons can be "active"; actions never are.
            active_id = current_tool if kind == "tool" else None
            icon = get_icon(TOOL_ICONS[item_id], rect.height - 2 * self.ICON_PAD) if is_icon else None
            if icon is not None:
                # Icon-only button: NO background fill. The active tool's icon
                # is filtered pink; every other icon renders normally.
                if item_id == active_id:
                    icon = icon.copy()
                    icon.fill(COLOR_ICON_ACTIVE, special_flags=pygame.BLEND_RGB_MULT)
                surface.blit(icon, icon.get_rect(center=rect.center))
            else:
                color, text_color = self._button_color(item_id, enabled, active_id, hovered_id)
                pygame.draw.rect(surface, color, rect, border_radius=4)
                label_surf = self.font.render(label, True, text_color)
                surface.blit(label_surf, label_surf.get_rect(center=rect.center))

    def handle_hover(self, sidebar_rect, screen_pos):
        """Return (kind, id) for the enabled button under screen_pos, else
        None. Used for hover highlighting and tooltips."""
        for item_id, label, enabled, rect, kind, is_icon in self._items_layout(sidebar_rect):
            if enabled and rect.collidepoint(screen_pos):
                return (kind, item_id)
        return None

    def handle_click(self, sidebar_rect, screen_pos):
        """Return (kind, id) if an enabled button was clicked, else None.
        Also starts the brief press/click animation for that button."""
        clicked = self.handle_hover(sidebar_rect, screen_pos)
        if clicked is not None:
            self.pressed_id = clicked[1]
            self.pressed_until = pygame.time.get_ticks() + BUTTON_PRESS_DURATION_MS
        return clicked

    def tooltip_rect_for(self, sidebar_rect, item_id):
        for iid, label, enabled, rect, kind, is_icon in self._items_layout(sidebar_rect):
            if iid == item_id:
                return rect
        return None


class SimPanel:
    """Sidebar simulation controls: a Trips on/off toggle, a Paths on/off
    toggle (route overlay, not the cars), and a 'Trips at once' slider
    (concurrency cap). Pure UI: it draws the state passed in and reports user
    actions; it owns no simulation state. Hit rects are cached during draw()
    and reused for the next frame's click/drag tests."""

    HEADER_GAP = 6
    ROW_GAP = 8
    BUTTON_HEIGHT = 30
    SLIDER_HEIGHT = 18
    SIDE_MARGIN = 16
    KNOB_W = 10

    def __init__(self, font, header_font):
        self.font = font
        self.header_font = header_font
        self._trips_rect = None
        self._paths_rect = None
        self._track_rect = None
        self.dragging = False
        self._vmin = TRIPS_AT_ONCE_MIN
        self._vmax = TRIPS_AT_ONCE_MAX

    def draw(self, surface, rect, y, *, trips_on, paths_on, trips_value):
        x = rect.x + self.SIDE_MARGIN
        width = rect.width - 2 * self.SIDE_MARGIN

        header = self.header_font.render("Simulation", True, COLOR_SIDEBAR_HEADER)
        surface.blit(header, (x, y))
        y += header.get_height() + self.HEADER_GAP

        # Trips toggle: an icon-only TILE (same size as the toolbar icon
        # buttons), NO background; play icon when stopped, pause when
        # running, so the art alone shows the state. Text toggle fallback if
        # the icons are missing.
        icon = get_icon("pause-button" if trips_on else "play-button",
                        ICON_TILE_H - 2 * ICON_TILE_PAD)
        if icon is not None:
            self._trips_rect = pygame.Rect(x, y, ICON_TILE_W, ICON_TILE_H)
            surface.blit(icon, icon.get_rect(center=self._trips_rect.center))
            y += ICON_TILE_H + self.ROW_GAP
        else:
            self._trips_rect = pygame.Rect(x, y, width, self.BUTTON_HEIGHT)
            self._draw_toggle(surface, self._trips_rect,
                              f"Trips: {'On' if trips_on else 'Off'}", trips_on)
            y += self.BUTTON_HEIGHT + self.ROW_GAP

        self._paths_rect = pygame.Rect(x, y, width, self.BUTTON_HEIGHT)
        self._draw_toggle(surface, self._paths_rect,
                          f"Paths: {'On' if paths_on else 'Off'}", paths_on)
        y += self.BUTTON_HEIGHT + self.ROW_GAP

        label = self.font.render(f"Trips at once: {trips_value}", True,
                                 COLOR_SIDEBAR_TEXT)
        surface.blit(label, (x, y))
        y += label.get_height() + 4

        self._track_rect = pygame.Rect(x, y, width, self.SLIDER_HEIGHT)
        track_mid = y + self.SLIDER_HEIGHT // 2
        pygame.draw.line(surface, COLOR_BUTTON, (x, track_mid),
                         (x + width, track_mid), 4)
        knob = pygame.Rect(0, 0, self.KNOB_W, self.SLIDER_HEIGHT)
        knob.center = (self._value_to_x(trips_value), track_mid)
        pygame.draw.rect(surface, COLOR_BUTTON_ACTIVE, knob, border_radius=3)
        y += self.SLIDER_HEIGHT + self.ROW_GAP
        return y

    def _draw_toggle(self, surface, rect, label, on):
        pygame.draw.rect(surface, COLOR_BUTTON_ACTIVE if on else COLOR_BUTTON,
                         rect, border_radius=4)
        s = self.font.render(label, True, COLOR_BUTTON_TEXT)
        surface.blit(s, s.get_rect(center=rect.center))

    def _value_to_x(self, value):
        t = (value - self._vmin) / (self._vmax - self._vmin)
        t = max(0.0, min(1.0, t))
        return int(self._track_rect.x + t * self._track_rect.width)

    def value_at(self, pos):
        """Slider value at a screen x position (clamped, integer)."""
        t = (pos[0] - self._track_rect.x) / max(1, self._track_rect.width)
        t = max(0.0, min(1.0, t))
        return int(round(self._vmin + t * (self._vmax - self._vmin)))

    def handle_click(self, pos):
        """Return 'trips' | 'paths' | 'slider' for a click, else None. A
        slider click also begins a drag."""
        if self._trips_rect and self._trips_rect.collidepoint(pos):
            return "trips"
        if self._paths_rect and self._paths_rect.collidepoint(pos):
            return "paths"
        if self._track_rect and self._track_rect.inflate(0, 14).collidepoint(pos):
            self.dragging = True
            return "slider"
        return None

    def handle_motion(self, pos):
        """While dragging, the new slider value, else None."""
        if self.dragging and self._track_rect is not None:
            return self.value_at(pos)
        return None

    def release(self):
        self.dragging = False


class BuildingPanel:
    """Sidebar building-type picker, shown only while the Building tool is
    active: a radio list of the archetypes with a category-color swatch. Pure
    UI that reports the clicked type; the active type lives on the controller."""

    HEADER_GAP = 6
    ROW_GAP = 5
    BUTTON_HEIGHT = 26
    SIDE_MARGIN = 16

    def __init__(self, font, header_font):
        self.font = font
        self.header_font = header_font
        self._rects = []   # [(type_name, rect), ...], refreshed each draw()

    def draw(self, surface, rect, y, active_type):
        x = rect.x + self.SIDE_MARGIN
        width = rect.width - 2 * self.SIDE_MARGIN
        header = self.header_font.render("Building", True, COLOR_SIDEBAR_HEADER)
        surface.blit(header, (x, y))
        y += header.get_height() + self.HEADER_GAP

        self._rects = []
        for name in BUILDING_TYPE_ORDER:
            r = pygame.Rect(x, y, width, self.BUTTON_HEIGHT)
            bt = BUILDING_TYPES.get(name)
            swatch = (BUILDING_CATEGORY_COLORS.get(bt.category, BUILDING_DEFAULT_COLOR)
                      if bt else BUILDING_DEFAULT_COLOR)
            active = (name == active_type)
            pygame.draw.rect(surface, COLOR_BUTTON_ACTIVE if active else COLOR_BUTTON,
                             r, border_radius=4)
            pygame.draw.rect(surface, swatch,
                             pygame.Rect(r.x + 6, r.y + 6, 14, r.height - 12), border_radius=2)
            label = self.font.render(name, True, COLOR_BUTTON_TEXT)
            surface.blit(label, (r.x + 28, r.y + (r.height - label.get_height()) // 2))
            self._rects.append((name, r))
            y += self.BUTTON_HEIGHT + self.ROW_GAP
        return y

    def handle_click(self, pos):
        for name, r in self._rects:
            if r.collidepoint(pos):
                return name
        return None


class GridPanel:
    """Sidebar placement-grid controls (shown for the Node/Road tools): an
    on/off toggle and a size stepper. Pure UI that reports the action; the grid
    state lives in PlacementManager."""

    HEADER_GAP = 6
    ROW_GAP = 6
    BUTTON_HEIGHT = 28
    SIDE_MARGIN = 16

    def __init__(self, font, header_font):
        self.font = font
        self.header_font = header_font
        self._toggle_rect = None
        self._minus_rect = None
        self._plus_rect = None

    def draw(self, surface, rect, y, enabled, size):
        x = rect.x + self.SIDE_MARGIN
        width = rect.width - 2 * self.SIDE_MARGIN
        header = self.header_font.render("Grid", True, COLOR_SIDEBAR_HEADER)
        surface.blit(header, (x, y))
        y += header.get_height() + self.HEADER_GAP

        self._toggle_rect = pygame.Rect(x, y, width, self.BUTTON_HEIGHT)
        pygame.draw.rect(surface, COLOR_BUTTON_ACTIVE if enabled else COLOR_BUTTON,
                         self._toggle_rect, border_radius=4)
        lbl = self.font.render(f"Grid: {'On' if enabled else 'Off'}  (Alt: bypass)",
                               True, COLOR_BUTTON_TEXT)
        surface.blit(lbl, lbl.get_rect(center=self._toggle_rect.center))
        y += self.BUTTON_HEIGHT + self.ROW_GAP

        size_lbl = self.font.render(f"Size: {int(size)} ft", True, COLOR_SIDEBAR_TEXT)
        surface.blit(size_lbl, (x, y + (self.BUTTON_HEIGHT - size_lbl.get_height()) // 2))
        bw = self.BUTTON_HEIGHT
        self._plus_rect = pygame.Rect(x + width - bw, y, bw, self.BUTTON_HEIGHT)
        self._minus_rect = pygame.Rect(x + width - 2 * bw - 6, y, bw, self.BUTTON_HEIGHT)
        for r, glyph in ((self._minus_rect, "-"), (self._plus_rect, "+")):
            pygame.draw.rect(surface, COLOR_BUTTON, r, border_radius=4)
            g = self.font.render(glyph, True, COLOR_BUTTON_TEXT)
            surface.blit(g, g.get_rect(center=r.center))
        y += self.BUTTON_HEIGHT + self.ROW_GAP
        return y

    def handle_click(self, pos):
        if self._toggle_rect and self._toggle_rect.collidepoint(pos):
            return "toggle"
        if self._minus_rect and self._minus_rect.collidepoint(pos):
            return "size_down"
        if self._plus_rect and self._plus_rect.collidepoint(pos):
            return "size_up"
        return None


class SettingsPanel:
    """Sidebar settings (always shown): clock format toggle + two live tuning
    sliders: Line weight (Knob 1) and Road width (Knob 2). Pure UI: reports
    clicks/drags and the chosen values; the caller applies them to the knobs."""

    HEADER_GAP = 6
    ROW_GAP = 8
    BUTTON_HEIGHT = 28
    SLIDER_HEIGHT = 18
    SIDE_MARGIN = 16
    KNOB_W = 10
    LINE_RANGE = (0.5, 3.0)
    WIDTH_RANGE = (0.5, 3.0)

    def __init__(self, font, header_font):
        self.font = font
        self.header_font = header_font
        self._clock_rect = None
        self._line_track = None
        self._width_track = None
        self._dragging = None        # "line" | "width" | None

    def draw(self, surface, rect, y, clock_24h, line_weight, width_scale):
        x = rect.x + self.SIDE_MARGIN
        width = rect.width - 2 * self.SIDE_MARGIN
        header = self.header_font.render("Settings", True, COLOR_SIDEBAR_HEADER)
        icon = get_icon("settings-button", header.get_height())
        hx = x
        if icon is not None:
            surface.blit(icon, (hx, y))
            hx += icon.get_width() + 6
        surface.blit(header, (hx, y))
        y += header.get_height() + self.HEADER_GAP

        self._clock_rect = pygame.Rect(x, y, width, self.BUTTON_HEIGHT)
        pygame.draw.rect(surface, COLOR_BUTTON, self._clock_rect, border_radius=4)
        label = self.font.render(
            f"Clock: {'24-hour' if clock_24h else '12-hour (AM/PM)'}",
            True, COLOR_BUTTON_TEXT)
        surface.blit(label, label.get_rect(center=self._clock_rect.center))
        y += self.BUTTON_HEIGHT + self.ROW_GAP

        self._line_track, y = self._slider(surface, x, y, width,
                                           "Line weight", line_weight, self.LINE_RANGE)
        self._width_track, y = self._slider(surface, x, y, width,
                                            "Road width", width_scale, self.WIDTH_RANGE)
        return y

    def _slider(self, surface, x, y, width, label, value, rng):
        lbl = self.font.render(f"{label}: x{value:.1f}", True, COLOR_SIDEBAR_TEXT)
        surface.blit(lbl, (x, y))
        y += lbl.get_height() + 2
        track = pygame.Rect(x, y, width, self.SLIDER_HEIGHT)
        mid = y + self.SLIDER_HEIGHT // 2
        pygame.draw.line(surface, COLOR_BUTTON, (x, mid), (x + width, mid), 4)
        t = max(0.0, min(1.0, (value - rng[0]) / (rng[1] - rng[0])))
        knob = pygame.Rect(0, 0, self.KNOB_W, self.SLIDER_HEIGHT)
        knob.center = (int(x + t * width), mid)
        pygame.draw.rect(surface, COLOR_BUTTON_ACTIVE, knob, border_radius=3)
        return track, y + self.SLIDER_HEIGHT + self.ROW_GAP

    def _value_at(self, track, rng, pos):
        t = max(0.0, min(1.0, (pos[0] - track.x) / max(1, track.width)))
        return round((rng[0] + t * (rng[1] - rng[0])) * 10) / 10    # step 0.1

    def value_for(self, which, pos):
        if which == "line":
            return self._value_at(self._line_track, self.LINE_RANGE, pos)
        return self._value_at(self._width_track, self.WIDTH_RANGE, pos)

    def handle_click(self, pos):
        if self._clock_rect and self._clock_rect.collidepoint(pos):
            return "clock"
        if self._line_track and self._line_track.inflate(0, 14).collidepoint(pos):
            self._dragging = "line"
            return "line"
        if self._width_track and self._width_track.inflate(0, 14).collidepoint(pos):
            self._dragging = "width"
            return "width"
        return None

    def handle_motion(self, pos):
        """While dragging a slider, return (which, value), else None."""
        if self._dragging:
            return (self._dragging, self.value_for(self._dragging, pos))
        return None

    def release(self):
        self._dragging = None

    @property
    def dragging(self):
        return self._dragging is not None


class Sidebar:
    """Draws the toolbar + snap-mode panel + simulation panel + scrollable
    instructions panel."""

    def __init__(self, surface, font, header_font, toolbar):
        self.surface = surface
        self.font = font
        self.header_font = header_font
        self.toolbar = toolbar
        # Snap Mode overlay UI: lightweight radio panel below the
        # action buttons. Pure UI; mode state lives in SnapModeController.
        self.snap_panel = SnapModePanel(font, header_font)
        # Simulation controls (trips/paths toggles + concurrency slider).
        self.sim_panel = SimPanel(font, header_font)
        # Building-type picker (only shown while the Building tool is active).
        self.building_panel = BuildingPanel(font, header_font)
        # Placement-grid controls (only shown for the Node/Road tools).
        self.grid_panel = GridPanel(font, header_font)
        # Settings (always shown): clock format, future global options.
        self.settings_panel = SettingsPanel(font, header_font)

    def draw(self, rect, current_tool, status_message="", scroll=0, context_hint="",
             hovered=None, snap_mode=SNAP_AUTO, trips_on=False, paths_on=True,
             trips_value=TRIPS_AT_ONCE_DEFAULT, active_building_type="House",
             grid_enabled=False, grid_size=GRID_SIZE_DEFAULT, clock_24h=True,
             mouse_pos=None, line_weight=1.0, width_scale=1.0):
        pygame.draw.rect(self.surface, COLOR_SIDEBAR_BG, rect)

        self.toolbar.draw(self.surface, rect, current_tool, hovered=hovered)

        x = rect.x + 16
        y = self.toolbar.full_bottom(rect) + 4
        y = self.snap_panel.draw(self.surface, rect, y, snap_mode) + 10
        y = self.sim_panel.draw(self.surface, rect, y, trips_on=trips_on,
                                paths_on=paths_on, trips_value=trips_value) + 8
        y = self.settings_panel.draw(self.surface, rect, y, clock_24h,
                                     line_weight, width_scale) + 8
        if current_tool == TOOL_BUILDING:
            y = self.building_panel.draw(self.surface, rect, y, active_building_type) + 8
        if current_tool in (TOOL_NODE, TOOL_ROAD):
            y = self.grid_panel.draw(self.surface, rect, y, grid_enabled, grid_size) + 8

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

        # Icon-only panel buttons have no text, so describe them on hover.
        if mouse_pos is not None:
            self._panel_tooltip(self.sim_panel._trips_rect, mouse_pos,
                                "Trips", "Start / stop the daily trip simulation")

    def _panel_tooltip(self, anchor_rect, mouse_pos, title, desc):
        """A small two-line hover popup for a non-toolbar (panel) button,
        anchored under `anchor_rect`. No-op unless the mouse is over it."""
        if anchor_rect is None or not anchor_rect.collidepoint(mouse_pos):
            return
        surfs = [self.header_font.render(title, True, COLOR_SIDEBAR_HEADER),
                 self.font.render(desc, True, COLOR_SIDEBAR_TEXT)]
        width = max(s.get_width() for s in surfs) + 16
        height = sum(s.get_height() for s in surfs) + 12
        panel = pygame.Rect(anchor_rect.left, anchor_rect.bottom + 4, width, height)
        pygame.draw.rect(self.surface, COLOR_TOOLTIP_BG, panel, border_radius=4)
        pygame.draw.rect(self.surface, COLOR_TOOLTIP_BORDER, panel, 1, border_radius=4)
        ty = panel.y + 6
        for s in surfs:
            self.surface.blit(s, (panel.x + 8, ty))
            ty += s.get_height()

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
    camera.zoom, never on camera position, window size beyond drawing
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


# Junction-corner bow strength: peak control-point offset as a fraction of
# the half-chord, reached at the angular extremes (a fully closed convex
# wedge and a fully open reflex gap). Larger = deeper scallops / taller flares.
FILLET_BOW = 0.55


def _fillet_points(point_a, point_b, node_pos, sector, samples=6):
    """Corner edge between two adjacent road edge points at a junction. The
    curvature is set by `sector`: the corner's angular span in radians (the
    CCW gap between the two roads' outward directions, 0..2*pi), which is what
    distinguishes a convex corner from a reflex one (the dot product between
    tangents cannot: a 120 deg convex corner and a 240 deg reflex corner
    have the same tangent angle):

        sector < 180 deg (convex, incl. right angles): concave, bows INTO the
            junction; deeper as the corner sharpens, fading to flat at 180.
        sector = 180 deg (straight-through): flat.
        sector > 180 deg (reflex gap): convex, bows OUTWARD away from the
            node, growing as the gap opens past 180.

    One linear law does all of it: the perpendicular bow is half_chord *
    FILLET_BOW * (pi - sector)/pi, positive (inward) for convex, negative
    (outward) for reflex, zero at 180 deg. A symmetric quadratic offset
    perpendicular to the chord, so it can never self-intersect. `node_pos`
    only fixes which perpendicular is "inward". Returns interior points only
    (endpoints excluded)."""
    chord = (point_b[0] - point_a[0], point_b[1] - point_a[1])
    clen = math.hypot(chord[0], chord[1])
    if clen < 1e-9:
        return []

    # (pi - sector)/pi: +1 fully-closed convex .. 0 at 180 .. -1 fully-open reflex.
    bow_scale = (math.pi - sector) / math.pi
    if abs(bow_scale) < 1e-3:
        return []                                        # straight-through -> flat

    # Unit perpendicular to the chord, oriented toward the node ("inward").
    perp = (-chord[1] / clen, chord[0] / clen)
    to_node = (node_pos[0] - point_a[0], node_pos[1] - point_a[1])
    if perp[0] * to_node[0] + perp[1] * to_node[1] < 0:
        perp = (-perp[0], -perp[1])

    bow = (clen * 0.5) * FILLET_BOW * bow_scale          # >0 inward, <0 outward
    mx, my = (point_a[0] + point_b[0]) * 0.5, (point_a[1] + point_b[1]) * 0.5
    ctrl = (mx + perp[0] * bow, my + perp[1] * bow)

    pts = []
    for i in range(1, samples):
        t = i / samples
        mt = 1 - t
        x = mt * mt * point_a[0] + 2 * mt * t * ctrl[0] + t * t * point_b[0]
        y = mt * mt * point_a[1] + 2 * mt * t * ctrl[1] + t * t * point_b[1]
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
# profile widths) and reports it for visualization; it does NOT modify or
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
    angle; with >=4 roads a road's own left/right edge points can be on
    opposite sides of the node, so sorting points directly produces a
    self-intersecting polygon).

    Each entry is one road: {"left", "right", "outward", "color"}, where
    "left"/"right" are that road's near-end edge points using a consistent
    convention (perpendicular to the OUTWARD tangent, rotated +90 = left).

    Going counter-clockwise by outward-tangent angle, road i contributes its
    own chord [right_i, left_i], then fills the gap to the next road's
    right_(i+1) point with a Bezier fillet whose shape is set by that corner's
    angular span (the CCW gap to the next road): convex corners (< 180 deg)
    bow inward, the straight-through (180 deg) is flat, and reflex gaps
    (> 180 deg) bow outward (see _fillet_points).

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
        # are themselves the curve's start/end points, with no further
        # pullback is needed. A tangent-continuous Bezier fillet bridges
        # them directly, replacing the straight segment entirely (the
        # straight boundary geometry simply doesn't extend past these
        # points anymore).
        # Corner's angular span: the CCW gap from road a's outward direction
        # to road b's (0..2pi). < pi = convex corner, > pi = reflex gap --
        # the sign that flips the fillet from concave to outward.
        ang_a = math.atan2(a["outward"][1], a["outward"][0])
        ang_b = math.atan2(b["outward"][1], b["outward"][0])
        sector = (ang_b - ang_a) % (2 * math.pi)
        fillet = _fillet_points(a["left"], b["right"], node_pos, sector)
        polygon.extend(fillet)

        edge_lines.append(([a["left"]] + fillet + [b["right"]], a["color"]))
    return polygon, edge_lines


def _is_width_taper(entries):
    """True for a 2-road continuation whose two mouths differ in width, the
    case that wants an S-curve width-transition surface. Equal-width bends
    (and 3+ way junctions) are False, so they use the corner-fillet polygon."""
    if len(entries) != 2:
        return False
    def mw(e):
        return math.hypot(e["left"][0] - e["right"][0], e["left"][1] - e["right"][1])
    return abs(mw(entries[0]) - mw(entries[1])) > 1e-3


def _build_continuation_polygon(entries, samples=8):
    """Asphalt band through an equal-width 2-road continuation/bend. Instead
    of an intersection's concave corner cuts, the two roads' mouths are joined
    edge-to-edge by tangent-continuous cubics (the SAME curves used for the
    lane-line connectors), so the surface follows the bend smoothly with no
    notch or overlap, and the painted edge lines sit exactly on the asphalt
    edge. entries: two {left, right, outward, color}. Returns
    (polygon, edge_lines)."""
    a, b = entries

    def edge_curve(p, out_p, q, out_q):
        gap = math.hypot(q[0] - p[0], q[1] - p[1])
        if gap < 1e-9:
            return [p, q]
        handle = 0.4 * gap
        c1 = (p[0] - out_p[0] * handle, p[1] - out_p[1] * handle)   # toward node
        c2 = (q[0] - out_q[0] * handle, q[1] - out_q[1] * handle)   # tangent to q's road
        return sample_cubic_bezier(p, c1, c2, q, samples)

    al, ar = a["left"], a["right"]
    bl, br = b["left"], b["right"]
    # Pair each A edge to the B edge on the same physical side (the non-
    # crossing pairing = smaller total endpoint distance).
    straight = (math.hypot(al[0] - bl[0], al[1] - bl[1])
                + math.hypot(ar[0] - br[0], ar[1] - br[1]))
    crossed = (math.hypot(al[0] - br[0], al[1] - br[1])
               + math.hypot(ar[0] - bl[0], ar[1] - bl[1]))
    b_for_left, b_for_right = (bl, br) if straight <= crossed else (br, bl)

    side1 = edge_curve(al, a["outward"], b_for_left, b["outward"])
    side2 = edge_curve(b_for_right, b["outward"], ar, a["outward"])
    polygon = [ar, al] + side1 + [b_for_left, b_for_right] + side2
    edge_lines = [([al] + side1 + [b_for_left], a["color"]),
                  ([b_for_right] + side2 + [ar], a["color"])]
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
    a taper length down its own corridor, so the whole transition lives
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
        # Larger font for the screen-fixed sim clock (top-right overlay).
        self.clock_font = pygame.font.SysFont("monospace", 26, bold=True)
        # Hit-rects for the lane-count context menu, refreshed each draw()
        # while a road is selected: [(rect, profile_key, delta), ...].
        self.lane_menu_buttons = []
        # Sprite caches for the generic "sprite" visual layer: base images
        # by path (None = failed load), plus the last rotated/scaled result
        # per path so straight-line motion at constant zoom costs nothing.
        self._sprite_images = {}
        self._sprite_rendered = {}

    def _outline_px(self, world_size_ft):
        """Outline width (screen px) for an element `world_size_ft` across,
        mirroring the icons' ~3.8%-of-size border with a visible floor."""
        return max(OUTLINE_MIN_PX,
                   round(OUTLINE_RATIO * world_size_ft * self.camera.zoom))

    def _line_px(self, world_size_ft, ratio):
        """Road line width (screen px): `ratio` of the element's width, scaled
        by Knob 1 (ROAD_LINE_WEIGHT), floored so it stays visible."""
        return max(ROAD_LINE_MIN_PX,
                   round(ratio * ROAD_LINE_WEIGHT * world_size_ft * self.camera.zoom))

    def _draw_thick_polyline(self, color, screen_pts, width):
        """Draw a polyline with rounded caps/joints (circles at the vertices),
        to match the icons' rounded thick strokes (pygame lines are square)."""
        if not screen_pts:
            return
        if len(screen_pts) >= 2:
            pygame.draw.lines(self.surface, color, False, screen_pts, width)
        if width >= 3:                       # round the joints + end caps
            r = width // 2
            for p in screen_pts:
                pygame.draw.circle(self.surface, color, (int(p[0]), int(p[1])), r)

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
        # the RoadProfile, NOT from road.width; the spline/edge/polygon
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
            # Shoulders use the lighter palette "frame" tone (the icon's outer
            # panel); their own curb edge becomes the dark road outline.
            for region in profile_shoulder_regions(geometry["sampled_points"], profile):
                region_screen = cam.world_to_screen_list(region["polygon"])
                pygame.draw.polygon(self.surface, COLOR_ROAD_FRAME, region_screen)
            median = profile_median_region(geometry["sampled_points"], profile)
            if median is not None:
                pygame.draw.polygon(self.surface, median["color"],
                                     cam.world_to_screen_list(median["polygon"]))

            # Icon-style layered edges: a thin lighter rim just inside the heavy
            # dark outline, on both carriageway/strip edges. Open polylines, so
            # trimmed mouths stay open (the junction surface covers the seam).
            ow = self._line_px(profile.total_width(), ROAD_OUTLINE_RATIO)
            inset = ow / cam.zoom            # rim sits one outline-width inboard
            rim_w = max(1, ow // 2)
            for edge, sign in ((left, -1.0), (right, 1.0)):
                rim = offset_polyline(edge, sign * inset)
                self._draw_thick_polyline(COLOR_ROAD_RIM, cam.world_to_screen_list(rim), rim_w)
            for edge in (left, right):
                self._draw_thick_polyline(COLOR_ROAD_OUTLINE, cam.world_to_screen_list(edge), ow)

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

        All markings (including the center line) are trimmed back at
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
        RoadProfile. Purely cosmetic; reads geometry, never recomputes
        the spline. All markings use `trimmed_points` so every line
        (including the center line) stops at the junction boundary instead
        of meeting/crossing other roads' lines in the intersection."""
        cam = self.camera
        # Thick palette lines (icon style): center line amber, the rest cream;
        # width proportional to the carriageway, floored so it stays visible.
        width_px = self._line_px(profile.carriageway_width(), ROAD_MARK_RATIO)
        for marking, offset in profile_markings(profile):
            base = trimmed_points
            if len(base) < 2:
                continue
            color = COLOR_ROAD_MARK_CENTER if abs(offset) < 1e-6 else COLOR_ROAD_MARK_EDGE
            line_pts = offset_polyline(base, offset) if offset else base
            for segment in marking_segments(line_pts, marking):
                screen_pts = cam.world_to_screen_list(segment)
                self._draw_thick_polyline(color, screen_pts, width_px)

    def draw_continuation_markings(self, network, node_id):
        """Connect the lane markings (centerline + edge/lane lines) of the two
        roads meeting at a same-width continuation node, so painted lines flow
        smoothly THROUGH the bend instead of stopping/kinking at the node.

        Each marking gets a tangent-continuous cubic bridging the two roads'
        trimmed mouths, tangent to each road's line (no kink), matched to the
        same physical side in the through-travel frame (no crossing). Applies
        to sharp folds too: a fold is trimmed back to its arc's tangent point
        (road_trim_at_node), so the same cubic sweeps the curved bend. Skipped
        only for width-transition (taper) nodes."""
        roads = [r for r in network.roads_for_node(node_id) if not r.is_preview]
        if len(roads) != 2:
            return
        a, b = roads
        prof_a = get_road_profile(a)
        prof_b = get_road_profile(b)
        if abs(prof_a.total_width() - prof_b.total_width()) > 1e-3:
            return  # width transition: the taper surface owns this node

        node_pos = network.nodes[node_id].pos
        cam = self.camera

        def mouth_line(road, offset):
            geom = network.geometry_for_road(road)
            pts = _trim_polyline(
                geom["sampled_points"],
                network.road_trim_at_node(road, road.start_node_id),
                network.road_trim_at_node(road, road.end_node_id))
            line = offset_polyline(pts, offset) if abs(offset) > 1e-9 else pts
            if len(line) < 2:
                return None
            # Orient so index 0 is the node end.
            if (math.hypot(line[0][0] - node_pos[0], line[0][1] - node_pos[1]) >
                    math.hypot(line[-1][0] - node_pos[0], line[-1][1] - node_pos[1])):
                line = list(reversed(line))
            return line

        width_px = self._line_px(prof_a.carriageway_width(), ROAD_MARK_RATIO)

        # Resolve which physical SIDE of the node each mouth sits on, in the
        # through-travel frame (a car driving a -> b). Matching by side is
        # exact at any bend angle; the old nearest-endpoint match crossed at
        # sharp bends, because one road's inner edge can land closer to the
        # OTHER road's far edge than to its near edge.
        ca = mouth_line(a, 0.0)
        cb = mouth_line(b, 0.0)
        if ca is None or cb is None:
            return
        c0a, c0b = ca[0], cb[0]
        din_a = _normalize2(ca[1][0] - c0a[0], ca[1][1] - c0a[1])   # node -> into a
        din_b = _normalize2(cb[1][0] - c0b[0], cb[1][1] - c0b[1])   # node -> into b
        travel_a = (-din_a[0], -din_a[1])   # heading as the through-car exits a
        travel_b = din_b                    # heading as it enters b

        def node_side(p, c0, heading):
            """Signed left/right of point `p` about the centerline mouth `c0`,
            measured along the through-travel `heading`."""
            return heading[0] * (p[1] - c0[1]) - heading[1] * (p[0] - c0[0])

        for marking, offset in profile_markings(prof_a):
            line_a = mouth_line(a, offset)
            if line_a is None:
                continue
            pa = line_a[0]
            side_a = node_side(pa, c0a, travel_a)
            # Pick b's line on the SAME hand of the through-travel, trying both
            # +/- offset (b's "left" is flipped from a's when their travel
            # senses oppose through the node).
            offs_b = (offset,) if abs(offset) < 1e-9 else (offset, -offset)
            line_b = None
            for o in offs_b:
                lb = mouth_line(b, o)
                if lb is None:
                    continue
                if line_b is None:
                    line_b = lb   # fallback if neither side matches
                if (node_side(lb[0], c0b, travel_b) >= 0) == (side_a >= 0):
                    line_b = lb
                    break
            if line_b is None:
                continue
            pb = line_b[0]
            d_in = _normalize2(pa[0] - line_a[1][0], pa[1] - line_a[1][1])    # into node
            d_out = _normalize2(line_b[1][0] - pb[0], line_b[1][1] - pb[1])   # out into b
            gap = math.hypot(pb[0] - pa[0], pb[1] - pa[1])
            if gap < 1e-6:
                continue
            handle = 0.4 * gap
            c1 = (pa[0] + d_in[0] * handle, pa[1] + d_in[1] * handle)
            c2 = (pb[0] - d_out[0] * handle, pb[1] - d_out[1] * handle)
            screen = cam.world_to_screen_list(sample_cubic_bezier(pa, c1, c2, pb, 10))
            color = COLOR_ROAD_MARK_CENTER if abs(offset) < 1e-6 else COLOR_ROAD_MARK_EDGE
            self._draw_thick_polyline(color, screen, width_px)

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

    def draw_building(self, network, building, debug, selected=False, count=None):
        """Draw a placed building as a category-colored footprint square,
        sized by its BuildingType's size, with a faint connector to each
        attached road node. `count`, if given, is the live car-occupancy shown
        centered on the footprint. Pure UI: reads building/BuildingType data,
        draws primitives. Never mutates the graph, never persisted."""
        bt = BUILDING_TYPES.get(building.building_type)
        color = (BUILDING_CATEGORY_COLORS.get(bt.category, BUILDING_DEFAULT_COLOR)
                 if bt else BUILDING_DEFAULT_COLOR)
        side = (BUILDING_SIZE_FT.get(bt.size, 30.0) if bt else 30.0)
        cam = self.camera
        cx, cy = building.pos
        h = side / 2.0
        corners = [(cx - h, cy - h), (cx + h, cy - h),
                   (cx + h, cy + h), (cx - h, cy + h)]
        screen_corners = cam.world_to_screen_list(corners)

        # Axis-aligned footprint -> a rounded rect, with the icon-style dark
        # outline (proportional width + rounded corners) to match the PNG icons.
        xs = [p[0] for p in screen_corners]
        ys = [p[1] for p in screen_corners]
        rect = pygame.Rect(min(xs), min(ys), max(xs) - min(xs), max(ys) - min(ys))
        ow = self._outline_px(side)
        radius = max(3, round(0.12 * side * cam.zoom))

        surf = pygame.Surface(self.surface.get_size(), pygame.SRCALPHA)
        # Faint connector(s) to attached node(s), showing the road attachment.
        for node_id in building.connection_node_ids:
            node = network.nodes.get(node_id)
            if node is not None:
                pygame.draw.line(surf, (*color, 110),
                                 cam.world_to_screen(building.pos),
                                 cam.world_to_screen(node.pos), 2)
        pygame.draw.rect(surf, (*color, BUILDING_FILL_ALPHA), rect, border_radius=radius)
        pygame.draw.rect(surf, (*COLOR_OUTLINE, 255), rect, width=ow, border_radius=radius)
        if selected:
            pygame.draw.rect(surf, (*COLOR_NODE_SELECTED, 255), rect.inflate(4, 4),
                             width=max(2, ow), border_radius=radius + 2)
        self.surface.blit(surf, (0, 0))

        # Live car-occupancy count, centered on the footprint (with a dark
        # pill behind it for legibility over any color).
        if count is not None:
            center = cam.world_to_screen(building.pos)
            txt = self.font.render(str(count), True, (255, 255, 255))
            pill = txt.get_rect(center=center).inflate(8, 4)
            pill_surf = pygame.Surface(pill.size, pygame.SRCALPHA)
            pill_surf.fill((20, 22, 26, 190))
            self.surface.blit(pill_surf, pill.topleft)
            self.surface.blit(txt, txt.get_rect(center=center))

        if debug:
            label = self.font.render(building.building_type, True, COLOR_DEBUG_TEXT)
            self.surface.blit(label, (cam.world_to_screen(building.pos)[0],
                                      cam.world_to_screen(building.pos)[1] - 16))

    def draw_building_preview(self, building_type, pos, node_pos):
        """Translucent ghost footprint for the Building tool. When node_pos is
        set, it would attach there (connector shown); when None, no node is in
        range so it's dimmed with a plain outline (wouldn't attach)."""
        bt = BUILDING_TYPES.get(building_type)
        color = (BUILDING_CATEGORY_COLORS.get(bt.category, BUILDING_DEFAULT_COLOR)
                 if bt else BUILDING_DEFAULT_COLOR)
        side = (BUILDING_SIZE_FT.get(bt.size, 30.0) if bt else 30.0)
        cam = self.camera
        cx, cy = pos
        h = side / 2.0
        corners = cam.world_to_screen_list([(cx - h, cy - h), (cx + h, cy - h),
                                            (cx + h, cy + h), (cx - h, cy + h)])
        xs = [p[0] for p in corners]
        ys = [p[1] for p in corners]
        rect = pygame.Rect(min(xs), min(ys), max(xs) - min(xs), max(ys) - min(ys))
        ow = self._outline_px(side)
        radius = max(3, round(0.12 * side * cam.zoom))
        surf = pygame.Surface(self.surface.get_size(), pygame.SRCALPHA)
        if node_pos is not None:
            pygame.draw.line(surf, (*color, 150), cam.world_to_screen(pos),
                             cam.world_to_screen(node_pos), 2)
            pygame.draw.rect(surf, (*color, BUILDING_PREVIEW_ALPHA), rect, border_radius=radius)
            pygame.draw.rect(surf, (*COLOR_OUTLINE, 255), rect, width=ow, border_radius=radius)
        else:
            pygame.draw.rect(surf, (*color, BUILDING_PREVIEW_ALPHA // 2), rect, border_radius=radius)
            pygame.draw.rect(surf, (150, 150, 150, 200), rect, width=1, border_radius=radius)
        self.surface.blit(surf, (0, 0))

    def draw_sim_clock(self, day, day_name, time_label):
        """Screen-fixed day/time readout, top-right of the canvas. Drawn over
        the world so the trip-demo clock is always visible."""
        text = f"{day_name}  Day {day}   {time_label}"
        surf = self.clock_font.render(text, True, COLOR_SIDEBAR_HEADER)
        pad = 10
        panel = pygame.Rect(0, 0, surf.get_width() + 2 * pad,
                            surf.get_height() + 2 * pad)
        panel.topright = (self.surface.get_width() - 12, 12)
        bg = pygame.Surface(panel.size, pygame.SRCALPHA)
        bg.fill((20, 22, 26, 205))
        self.surface.blit(bg, panel.topleft)
        pygame.draw.rect(self.surface, COLOR_TOOLTIP_BORDER, panel, 1, border_radius=6)
        self.surface.blit(surf, (panel.x + pad, panel.y + pad))

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
        debug, ...); it only knows how to draw a handful of primitive
        shapes in world space, supplied as plain dicts:

          {"shape": "circle",  "pos": (x, y), "radius": r,
           "color": (r,g,b), "alpha": 0-255}
          {"shape": "polygon", "points": [(x,y), ...],
           "color": (r,g,b), "alpha": 0-255, "outline": bool}
          {"shape": "line",    "points": [(x,y), ...],
           "color": (r,g,b), "width": px}
          {"shape": "sprite",  "pos": (x, y), "heading": (dx, dy),
           "length_ft": L, "image": path}
            is an image whose source art points UP (head at the top),
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

    def draw_grid_overlay(self, grid_size):
        """PLACEHOLDER ground grid: faint lines at the snap spacing, as a
        visual cue for grid placement.

        This is a STAND-IN for future tiled ground GRAPHICS; the intent is
        to replace the drawing in THIS method (visual only) with real ground
        tiles/textures later. The snap logic lives in PlacementManager and is
        completely independent of whatever gets rendered here. Drawn as the
        background layer, beneath everything else."""
        cam = self.camera
        if grid_size * cam.zoom < 6:      # too dense on-screen to be useful
            return
        w, h = self.surface.get_size()
        tl = cam.screen_to_world((0, 0))
        br = cam.screen_to_world((w, h))
        minx, maxx = min(tl[0], br[0]), max(tl[0], br[0])
        miny, maxy = min(tl[1], br[1]), max(tl[1], br[1])
        x = math.floor(minx / grid_size) * grid_size
        while x <= maxx:
            pygame.draw.line(self.surface, COLOR_GRID,
                             cam.world_to_screen((x, miny)),
                             cam.world_to_screen((x, maxy)), 1)
            x += grid_size
        y = math.floor(miny / grid_size) * grid_size
        while y <= maxy:
            pygame.draw.line(self.surface, COLOR_GRID,
                             cam.world_to_screen((minx, y)),
                             cam.world_to_screen((maxx, y)), 1)
            y += grid_size

    def draw(self, network, preview_road, preview_geometry, preview_node, preview_snapped,
             pending_start_node, selected_road, hovered_node, selected_node,
             current_tool, debug, visual_layers=None, preview_snap_mode=None,
             sim_clock=None, building_preview=None, selected_building=None,
             building_occupancy=None, grid_enabled=False, grid_size=GRID_SIZE_DEFAULT):
        self.surface.fill(COLOR_BG)

        # Background ground layer (PLACEHOLDER grid -> future ground graphics).
        if grid_enabled:
            self.draw_grid_overlay(grid_size)

        for zone in network.zones.values():
            self.draw_zone(zone, debug)

        # Building footprints sit on the ground, beneath roads/nodes/overlays.
        sel_building_id = selected_building.id if selected_building is not None else None
        for building in network.buildings.values():
            count = building_occupancy.get(building.id) if building_occupancy else None
            self.draw_building(network, building, debug,
                               selected=(building.id == sel_building_id), count=count)

        # Per-node collection of (left_edge_pt, right_edge_pt, surface_color)
        # contributed by each connected road's trimmed end, the basis for
        # the lane-aware junction surface (replaces the old circular patch).
        junction_edge_points = {}
        junction_outer_points = {}

        for road in network.roads.values():
            geometry = network.geometry_for_road(road)
            surface_color = (COLOR_ROAD_SURFACE_SELECTED if road is selected_road
                             else road_surface_color(road.id))
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
                        # (immutable) centerline, never a shared half-width,
                        # so an asymmetric profile produces an asymmetric
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
                        # direction), which flips the perpendicular, so swap
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
            if _is_width_taper(entries):
                # 2-road continuation with DIFFERING widths: width-taper
                # surface (S-curve edges), not a corner-fillet junction.
                polygon, outer_edge_lines = _build_taper_polygon(outer_entries)
            elif len(entries) == 2:
                # Equal-width bend: smooth edge-to-edge band.
                polygon, outer_edge_lines = _build_continuation_polygon(outer_entries)
            else:
                # 3+ way: rounded corner-fillet polygon.
                polygon, outer_edge_lines = _build_junction_polygon(outer_entries, network.nodes[node_id].pos)
            color = next(e["outer_color"] for e in entries if e.get("shoulder_width", 0.0) > 0)
            pygame.draw.polygon(self.surface, color, self.camera.world_to_screen_list(polygon))

            # Curb-return curves: the outer (sidewalk/shoulder) boundary
            # also gets a smooth connecting curve between each pair of
            # trimmed edges, derived the same way as the asphalt edge
            # connectors, giving the classic "curb wraps around the
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
            if _is_width_taper(entries):
                polygon, edge_lines = _build_taper_polygon(entries)
            elif len(entries) == 2:
                polygon, edge_lines = _build_continuation_polygon(entries)
            else:
                polygon, edge_lines = _build_junction_polygon(entries, network.nodes[node_id].pos)

            screen_polygon = self.camera.world_to_screen_list(polygon)
            pygame.draw.polygon(self.surface, road_surface_color(node_id), screen_polygon)

            # Icon-style heavy dark outline along the junction's outer boundary
            # (the fillet connectors), matching the roads' edge outline so they
            # join into one continuous border. For true intersections (3+ roads)
            # also lay the cream edge line along the same curve, so the painted
            # edge lines sweep AROUND the corner instead of stopping at it.
            mouth_w = math.hypot(entries[0]["left"][0] - entries[0]["right"][0],
                                 entries[0]["left"][1] - entries[0]["right"][1])
            ow = self._line_px(mouth_w, ROAD_OUTLINE_RATIO)
            ew = self._line_px(mouth_w, ROAD_MARK_RATIO)
            for curve_points, _color in edge_lines:
                screen_pts = self.camera.world_to_screen_list(curve_points)
                self._draw_thick_polyline(COLOR_ROAD_OUTLINE, screen_pts, ow)
                if len(entries) >= 3:
                    self._draw_thick_polyline(COLOR_ROAD_MARK_EDGE, screen_pts, ew)

        # Rounded dead-end caps: nodes with exactly one connected road get a
        # circular pavement cap (radius = full profile width / 2) so the
        # road end isn't a flat-cut polygon edge.
        for node in network.nodes.values():
            roads = [r for r in network.roads_for_node(node.id) if not r.is_preview]
            if len(roads) == 1:
                radius_ft = get_road_profile(roads[0]).total_width() / 2.0
                p = self.camera.world_to_screen(node.pos)
                radius_px = self.camera.feet_to_pixels(radius_ft)
                pygame.draw.circle(self.surface, road_surface_color(roads[0].id), p, radius_px)
                # Icon-style heavy dark outline ring around the dead-end cap.
                ow = self._line_px(radius_ft * 2.0, ROAD_OUTLINE_RATIO)
                pygame.draw.circle(self.surface, COLOR_ROAD_OUTLINE, p, radius_px, ow)

        # Road Marking Renderer pass: runs after all surfaces/junction/cap
        # patches are painted, so markings sit cleanly on top and remain
        # fully independent of surface geometry. Uses the FULL (untrimmed)
        # centerline so markings run continuously into junctions/caps.
        for road in network.roads.values():
            self.draw_road_markings(network, road, network.geometry_for_road(road))

        # Continuation bends: connect the two roads' lane lines across the
        # node so they flow through the bend (drawn after per-road markings).
        for node_id in network.nodes:
            if sum(1 for r in network.roads_for_node(node_id)
                   if not r.is_preview) == 2:
                self.draw_continuation_markings(network, node_id)

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
            # preview only: white for a straight preview, cyan for a
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

        # Sim clock (top-right), shown while the trip demo is running.
        if sim_clock is not None:
            self.draw_sim_clock(sim_clock[0], sim_clock[1], sim_clock[2])

        # Watchdog overlay: read-only diagnostics, debug mode only. Marks
        # suspicious geometry (crossings without nodes, collapsed trims,
        # degenerate widths) WITHOUT changing any geometry.
        if debug:
            self.draw_watchdog_overlay(detect_geometry_issues(network))

        # Building tool: ghost footprint following the cursor (on top).
        if building_preview is not None:
            self.draw_building_preview(*building_preview)

        # Lane-count context menu for the selected road (TOOL_SELECT only).
        self.lane_menu_buttons = []
        if current_tool == TOOL_SELECT and selected_road is not None and not selected_road.is_preview:
            self.draw_lane_menu(network, selected_road)


class SnapSystem:
    """
    Centralized snapping: given a world position, returns the best valid
    snap position (a nearby existing node) for any placement preview.
    Visual-only; never mutates the graph.
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
        # road preview and committing a new road; it never touches
        # existing roads or any other system. `last_preview_mode` mirrors
        # the most recent resolved preview mode (STRAIGHT/CURVE) purely so
        # the renderer can color the preview centerline; None when no road
        # preview is active.
        self.snap = SnapModeController()
        self.last_preview_mode = None

        # Placement grid: quantize new positions to a regular spacing. Pure
        # logic (no graphics here). Existing-node snapping takes priority;
        # holding Alt temporarily bypasses the grid for one-off placement.
        self.grid_enabled = False
        self.grid_size = GRID_SIZE_DEFAULT

    def snap_to_grid(self, pos):
        """Quantize a free world position to the placement grid, unless the
        grid is off or Alt is held (bypass). Returns pos unchanged otherwise."""
        if not self.grid_enabled or (pygame.key.get_mods() & pygame.KMOD_ALT):
            return pos
        g = self.grid_size
        return (round(pos[0] / g) * g, round(pos[1] / g) * g)

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
            self.network.add_node(*self.snap_to_grid(world_pos))

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
            # preview anyway, so let it fall through to camera zoom instead
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
        # Existing-node snap wins; otherwise fall back to the placement grid.
        pos = snap_target.pos if snap_target is not None else self.snap_to_grid(world_pos)
        snapped = snap_target is not None

        if config["object"] == "road" and self.pending_start_node is not None:
            # Snap Mode overlay decides the offset the preview is built
            # with (straight line / bezier bulge / auto), wrapping (not
            # replacing) the manual wheel offset. Same geometry function
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
        self.selected_building = None
        self.hovered_node = None

        # A node that was pressed but hasn't yet moved past the drag
        # threshold, used to distinguish a click (select/chain) from a
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
        # Destination trip demo (T key): a TripScheduler releasing trips over
        # an accelerated day; None when the demo is off.
        self.trip_scheduler = None
        # Show the route overlay (path lines) under the cars (Paths toggle).
        self.show_trip_paths = True
        # Live cap on concurrent cars (Trips-at-once slider).
        self.trips_at_once = TRIPS_AT_ONCE_DEFAULT
        # Building tool: the archetype the next placed building will use.
        self.active_building_type = BUILDING_TYPE_ORDER[0]
        # Live per-building car occupancy while the trip demo runs
        # ({building_id: count}); empty when the demo is off.
        self.building_occupancy = {}
        # Settings: clock display format (True = 24h, False = 12h AM/PM).
        self.clock_24h = True

    # ------------------------------------------------------------------
    # Tool state system
    # ------------------------------------------------------------------
    def set_tool(self, tool_id):
        if tool_id == self.current_tool:
            return
        if tool_id not in (TOOL_SELECT, TOOL_NODE, TOOL_ROAD, TOOL_BUILDING, TOOL_ZONE):
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
        self.selected_building = None
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
        elif event.key == pygame.K_b:
            self.load_test_city()
        elif event.key == pygame.K_t:
            self.toggle_trip_demo()
        elif event.key == pygame.K_ESCAPE:
            self.placement.cancel()
        elif event.key == pygame.K_s:
            self.save_to_file()
        elif event.key == pygame.K_l:
            self.load_from_file()
        elif event.key in (pygame.K_DELETE, pygame.K_BACKSPACE):
            self.delete_selected()
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
            elif self.current_tool == TOOL_BUILDING:
                self._place_building(world_pos)
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
            # Don't decide drag-vs-click yet; motion/up resolves it.
            self.mousedown_node = existing
            self.mousedown_pos = world_pos
            self.selected_road = None
            self.selected_building = None
            return

        road_threshold = 6 / self.camera.zoom
        road = self.network.road_at(world_pos[0], world_pos[1], threshold=road_threshold)
        if road is not None:
            self.selected_road = road
            self.selected_node = None
            self.selected_building = None
            return

        building = self.network.building_at(*world_pos)
        if building is not None:
            self.selected_building = building
            self.selected_road = None
            self.selected_node = None
            return

        # Empty space: deselect everything.
        self.selected_road = None
        self.selected_node = None
        self.selected_building = None

    def _handle_node_click(self, node):
        """A plain click (no drag) on an existing node, in TOOL_SELECT: select it."""
        if self.current_tool != TOOL_SELECT:
            return
        if self.selected_node is not None and self.selected_node.id == node.id:
            self.selected_node = None
        else:
            self.selected_node = node
            self.selected_road = None
            self.selected_building = None

    def delete_selected(self):
        """Delete whatever is selected (road, node, or building) in the Select
        tool. Deleting a node cascades to its roads; any delete clears the
        transient sim/placement state that referenced the removed objects."""
        if self.selected_road is not None:
            rid = self.selected_road.id
            self.network.remove_road(rid)
            self.selected_road = None
            self.status_message = f"Deleted road {rid}"
        elif self.selected_node is not None:
            nid = self.selected_node.id
            self.network.remove_node(nid)
            self.selected_node = None
            self.status_message = f"Deleted node {nid} (and its roads)"
        elif self.selected_building is not None:
            bid = self.selected_building.id
            self.network.remove_building(bid)
            self.selected_building = None
            self.status_message = f"Deleted building {bid}"
        else:
            return
        # The removed objects may be referenced by live vehicles / scheduled
        # trips / a pending road start; clear those so nothing dangles.
        self.traffic.reset()
        self.trip_scheduler = None
        self.placement.cancel()
        self.mousedown_node = None
        self.dragging_node = None
        self.dragging_control_point = False

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
        so it stays the one authoritative copy; no new RoadNetwork is
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
        self.selected_node = None
        self.selected_building = None

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

    def _building_target(self, world_pos):
        """(node, footprint_pos) for placing/previewing a building near
        world_pos: the road node under the cursor (generous, zoom-stable
        radius) plus a footprint point offset off that node toward the
        cursor (so the click side picks the side). (None, world_pos) when no
        node is in range."""
        node = self.network.node_at(*world_pos, radius=NODE_HIT_RADIUS / self.camera.zoom)
        if node is None:
            return None, world_pos
        dx, dy = world_pos[0] - node.x, world_pos[1] - node.y
        dist = math.hypot(dx, dy)
        ux, uy = (0.0, -1.0) if dist < 1e-6 else (dx / dist, dy / dist)
        return node, (node.x + ux * BUILDING_PLACE_OFFSET,
                      node.y + uy * BUILDING_PLACE_OFFSET)

    def _place_building(self, world_pos):
        node, pos = self._building_target(world_pos)
        if node is None:
            self.status_message = "Building tool: click a road node to attach a building"
            return
        self.network.add_building(pos[0], pos[1], connection_node_ids=[node.id],
                                  building_type=self.active_building_type)
        self.status_message = f"Placed {self.active_building_type} on node {node.id}"

    def get_building_preview(self, world_pos):
        """Ghost preview for the Building tool: (building_type, pos, node_pos),
        or None when the tool isn't active. node_pos is None when no node is in
        range (free-floating ghost that wouldn't attach)."""
        if self.current_tool != TOOL_BUILDING:
            return None
        node, pos = self._building_target(world_pos)
        return (self.active_building_type, pos, node.pos if node else None)

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
                return "Drag red dot to bend curve, scroll to nudge; Del to delete"
            if self.selected_node is not None:
                return "Drag node to move it; Del to delete (also its roads)"
            if self.selected_building is not None:
                return "Building selected; Del to delete"
            return "Click a node, road, or building to select"
        if self.current_tool == TOOL_BUILDING:
            return f"Click a road node to place: {self.active_building_type}"
        if self.current_tool == TOOL_ZONE:
            return "Zone tool coming soon"
        return ""

    def load_test_city(self):
        """Replace the active network's contents with the handcrafted
        destination test city (in memory only, NOT saved over map_save.json
        unless the user presses S). Mutates the existing RoadNetwork in place
        so all references (placement, traffic) stay valid."""
        src = create_test_city()
        net = self.network
        net.nodes = src.nodes
        net.roads = src.roads
        net.zones = src.zones
        net.buildings = src.buildings
        net._next_node_id = src._next_node_id
        net._next_road_id = src._next_road_id
        net._next_zone_id = src._next_zone_id
        net._next_building_id = src._next_building_id

        self.traffic.reset()
        self.trip_scheduler = None
        self.placement.cancel()
        self.selected_road = None
        self.selected_node = None
        self.selected_building = None
        self.hovered_node = None
        self.status_message = ("Loaded test city (unsaved -- press T to run "
                               "trips, S to overwrite map_save.json)")
        print(self.status_message)

    def toggle_trip_demo(self):
        """Start/stop the destination trip demo on the current network.
        Generates a watchable subset of the day's trips and drives them with
        a TripScheduler; toggling off clears the cars."""
        if self.trip_scheduler is not None:
            self.trip_scheduler = None
            self.traffic.reset()
            self.building_occupancy = {}   # hide counts when the demo is off
            self.status_message = "Trip demo: off"
            return
        if not self.network.buildings:
            self.status_message = "No buildings -- press B to load the test city first"
            return

        def day_trips(day_index):
            # day_index 0 = Monday; 5/6 = Sat/Sun (no work on weekends). Each
            # day gets its own deterministic rng so days vary but replay the
            # same. The scheduler calls this once per day, forever.
            weekend = (day_index % 7) >= 5
            return generate_trips(self.network, random.Random(DEMO_SEED + day_index),
                                  limit=DEMO_TRIP_LIMIT, weekend=weekend)

        if not day_trips(0):
            self.status_message = "No trips could be generated for this map"
            return
        self.traffic.reset()
        self.traffic.prepare_routes()
        # Seed occupancy: homes start "full" (cars parked), everything else
        # empty; arrivals/departures move the counts from there.
        self.building_occupancy = {}
        for b in self.network.buildings.values():
            bt = BUILDING_TYPES.get(b.building_type)
            self.building_occupancy[b.id] = (
                bt.capacity if (bt and bt.category == RESIDENTIAL) else 0)
        self.trip_scheduler = TripScheduler(day_trips, start_hour=DEMO_START_HOUR,
                                             hours_per_second=DEMO_HOURS_PER_SEC)
        self.status_message = "Trip demo: on (weekly cycle; no work Sat/Sun)"
        print(self.status_message)

    def update_traffic(self, dt):
        """Per-frame simulation step: release any due trips, drop arrived
        cars, then advance all vehicles. Replaces the bare traffic.update()
        call so the scheduler and the V-key demo share one update path."""
        if self.trip_scheduler is not None:
            # Cull first so finished cars free up slots this frame; each
            # arrival credits its destination building's occupancy (+1),
            # capped at that building's capacity so counts stay in a sane
            # 0..capacity range (the demo trip flow isn't conservation-exact).
            for v in self.traffic.cull_arrived():
                bid = v.dest_building_id
                building = self.network.buildings.get(bid) if bid is not None else None
                if building is not None:
                    bt = BUILDING_TYPES.get(building.building_type)
                    cap = bt.capacity if bt else self.building_occupancy.get(bid, 0) + 1
                    self.building_occupancy[bid] = min(
                        cap, self.building_occupancy.get(bid, 0) + 1)

            def spawn(trip):
                # Release only while under the concurrency cap. A car that
                # actually leaves drops its origin building's occupancy (-1).
                if len(self.traffic.vehicles) < self.trips_at_once:
                    v = self.traffic.spawn_trip(trip.origin_node_id, trip.dest_node_id,
                                                trip.dest_building_id)
                    if v is not None and trip.origin_building_id is not None:
                        self.building_occupancy[trip.origin_building_id] = max(
                            0, self.building_occupancy.get(trip.origin_building_id, 0) - 1)

            self.trip_scheduler.update(dt, spawn)
            self.status_message = (
                f"{self.trip_scheduler.day_name} (Day {self.trip_scheduler.day}) "
                f"{self.trip_scheduler.clock_label(self.clock_24h)}  "
                f"cars: {len(self.traffic.vehicles)}/{self.trips_at_once}")
        self.traffic.update(dt)

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
        layers += self.traffic.visual_layers(show_paths=self.show_trip_paths)
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
            # road.data each frame, with no caches to invalidate, and the
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


# Future GitHub link target (placeholder, not opened yet).
GITHUB_URL = "https://github.com/"  # TODO: real repo URL


class StartScreen:
    """Begin-simulation landing screen shown before the editor. PLACEHOLDER
    visuals: a title and a centered column of buttons (Start, Settings,
    Credits, GitHub, Quit). Pure UI that reports the clicked button id; the
    caller decides what each does. Settings reuses the settings icon as a
    stand-in for a future settings screen."""

    BTN_W = 320
    BTN_H = 48
    BTN_GAP = 14

    # (id, label); order is top-to-bottom. All placeholders for now.
    ITEMS = [
        ("start", "Start Simulation"),
        ("settings", "Settings"),
        ("credits", "Credits"),
        ("github", "GitHub (soon)"),
        ("quit", "Quit"),
    ]

    def __init__(self, font, header_font, title_font):
        self.font = font
        self.header_font = header_font
        self.title_font = title_font
        self.show_credits = False
        self._rects = []          # [(id, label, rect), ...] from last draw
        self.status = ""          # transient note (e.g. placeholder clicks)

    def _layout(self, size):
        w, h = size
        n = len(self.ITEMS)
        total = n * self.BTN_H + (n - 1) * self.BTN_GAP
        x = (w - self.BTN_W) // 2
        y = (h - total) // 2 + 40       # nudge down to leave room for the title
        rects = []
        for iid, label in self.ITEMS:
            rects.append((iid, label, pygame.Rect(x, y, self.BTN_W, self.BTN_H)))
            y += self.BTN_H + self.BTN_GAP
        return rects

    def draw(self, surface, mouse_pos):
        w, h = surface.get_size()
        surface.fill(COLOR_BG)

        title = self.title_font.render("FLOWSCAPE", True, COLOR_SIDEBAR_HEADER)
        surface.blit(title, title.get_rect(center=(w // 2, h // 2 - 170)))
        sub = self.font.render("Traffic Simulation  ::  placeholder start screen",
                               True, COLOR_SIDEBAR_TEXT)
        surface.blit(sub, sub.get_rect(center=(w // 2, h // 2 - 134)))

        self._rects = self._layout(surface.get_size())
        for iid, label, rect in self._rects:
            hot = rect.collidepoint(mouse_pos)
            pygame.draw.rect(surface, COLOR_BUTTON_HOVER if hot else COLOR_BUTTON,
                             rect, border_radius=6)
            pygame.draw.rect(surface, COLOR_TOOLTIP_BORDER, rect, 1, border_radius=6)
            if iid == "settings":     # settings icon placeholder, left of label
                icon = get_icon("settings-button", rect.height - 16)
                if icon is not None:
                    surface.blit(icon, (rect.x + 12, rect.centery - icon.get_height() // 2))
            ls = self.font.render(label, True, COLOR_BUTTON_TEXT)
            surface.blit(ls, ls.get_rect(center=rect.center))

        if self.status:
            note = self.font.render(self.status, True, COLOR_SIDEBAR_TEXT)
            surface.blit(note, note.get_rect(center=(w // 2, self._rects[-1][2].bottom + 28)))

        if self.show_credits:
            self._draw_credits(surface)

    def _draw_credits(self, surface):
        w, h = surface.get_size()
        panel = pygame.Rect(0, 0, 460, 220)
        panel.center = (w // 2, h // 2)
        veil = pygame.Surface((w, h), pygame.SRCALPHA)
        veil.fill((0, 0, 0, 150))
        surface.blit(veil, (0, 0))
        pygame.draw.rect(surface, COLOR_TOOLTIP_BG, panel, border_radius=8)
        pygame.draw.rect(surface, COLOR_TOOLTIP_BORDER, panel, 1, border_radius=8)
        lines = [("Credits", COLOR_SIDEBAR_HEADER),
                 ("Flowscape", COLOR_SIDEBAR_TEXT),
                 ("Design & code: Victoria Tynan", COLOR_SIDEBAR_TEXT),
                 ("Built with pygame.", COLOR_SIDEBAR_TEXT),
                 ("", None),
                 ("click anywhere to close", COLOR_SIDEBAR_TEXT)]
        y = panel.y + 24
        for text, color in lines:
            if text:
                f = self.header_font if color == COLOR_SIDEBAR_HEADER else self.font
                s = f.render(text, True, color)
                surface.blit(s, s.get_rect(center=(panel.centerx, y)))
            y += 30

    def handle_click(self, pos):
        """Return the clicked button id, or None. A credits overlay swallows
        the next click (to close it)."""
        if self.show_credits:
            self.show_credits = False
            return None
        for iid, label, rect in self._rects:
            if rect.collidepoint(pos):
                return iid
        return None


def run_start_screen(screen, clock, font, header_font, title_font):
    """Run the begin-simulation landing screen until the user picks an action.
    Returns "start" (enter the editor) or "quit" (exit). Settings/GitHub are
    placeholders for now (they just show a transient note)."""
    pygame.display.set_caption("Flowscape")
    ss = StartScreen(font, header_font, title_font)
    while True:
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                return "quit"
            elif event.type == pygame.VIDEORESIZE:
                pygame.display.set_mode((max(event.w, MIN_WINDOW_WIDTH),
                                         max(event.h, MIN_WINDOW_HEIGHT)), pygame.RESIZABLE)
            elif event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE:
                ss.show_credits = False
            elif event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
                action = ss.handle_click(event.pos)
                if action == "start":
                    return "start"
                if action == "quit":
                    return "quit"
                if action == "credits":
                    ss.show_credits = True
                    ss.status = ""
                elif action == "settings":
                    ss.status = "Settings: coming soon (placeholder)"
                elif action == "github":
                    ss.status = f"GitHub: {GITHUB_URL} (link coming soon)"
        ss.draw(pygame.display.get_surface(), pygame.mouse.get_pos())
        pygame.display.flip()
        clock.tick(60)


def main():
    pygame.init()
    window_size = (CANVAS_WIDTH + SIDEBAR_WIDTH, CANVAS_HEIGHT)
    screen = pygame.display.set_mode(window_size, pygame.RESIZABLE)
    pygame.display.set_caption("Road Editor - Phase 3")
    clock = pygame.time.Clock()
    font = pygame.font.SysFont("monospace", 14)
    header_font = pygame.font.SysFont("monospace", 16, bold=True)
    title_font = pygame.font.SysFont("monospace", 48, bold=True)

    # Begin-simulation landing screen first; only enter the editor on "start".
    if run_start_screen(screen, clock, font, header_font, title_font) == "quit":
        pygame.quit()
        sys.exit()
    pygame.display.set_caption("Road Editor - Phase 3")
    # The window may have been resized on the start screen; re-sync.
    screen = pygame.display.get_surface()
    window_size = screen.get_size()

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

    # Startup: load the handcrafted test city so the editor opens on a ready
    # map (Load Map / L still pulls the saved map_save.json on demand).
    controller.load_test_city()

    running = True
    while running:
        raw_screen_pos = pygame.mouse.get_pos()
        screen_pos = (min(raw_screen_pos[0], canvas_rect.width - 1), raw_screen_pos[1])
        in_canvas = raw_screen_pos[0] < canvas_rect.width
        world_pos = camera.screen_to_world(screen_pos)

        for event in pygame.event.get():
            # While dragging the Trips-at-once slider, the sim panel owns
            # mouse motion/release (so dragging over the canvas doesn't
            # pan or draw).
            if sidebar.sim_panel.dragging:
                if event.type == pygame.MOUSEMOTION:
                    controller.trips_at_once = sidebar.sim_panel.handle_motion(event.pos)
                    continue
                if event.type == pygame.MOUSEBUTTONUP and event.button == 1:
                    sidebar.sim_panel.release()
                    continue
            if sidebar.settings_panel.dragging:
                if event.type == pygame.MOUSEMOTION:
                    m = sidebar.settings_panel.handle_motion(event.pos)
                    if m is not None:
                        controller.status_message = set_road_knob(m[0], m[1])
                    continue
                if event.type == pygame.MOUSEBUTTONUP and event.button == 1:
                    sidebar.settings_panel.release()
                    continue

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
                # Fullscreen toggle: rendering/layout only; camera
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
                    sim_clicked = (None if snap_clicked is not None
                                   else sidebar.sim_panel.handle_click(raw_screen_pos))
                    building_clicked = (None if (snap_clicked is not None or sim_clicked is not None)
                                        else sidebar.building_panel.handle_click(raw_screen_pos))
                    grid_clicked = (sidebar.grid_panel.handle_click(raw_screen_pos)
                                    if (snap_clicked is None and sim_clicked is None
                                        and building_clicked is None
                                        and controller.current_tool in (TOOL_NODE, TOOL_ROAD))
                                    else None)
                    settings_clicked = (None if (snap_clicked or sim_clicked or building_clicked
                                                 or grid_clicked) else
                                        sidebar.settings_panel.handle_click(raw_screen_pos))
                    if settings_clicked == "clock":
                        controller.clock_24h = not controller.clock_24h
                        controller.status_message = (
                            f"Clock: {'24-hour' if controller.clock_24h else '12-hour (AM/PM)'}")
                    elif settings_clicked in ("line", "width"):
                        controller.status_message = set_road_knob(
                            settings_clicked,
                            sidebar.settings_panel.value_for(settings_clicked, raw_screen_pos))
                    elif grid_clicked is not None:
                        pm = controller.placement
                        if grid_clicked == "toggle":
                            pm.grid_enabled = not pm.grid_enabled
                            controller.status_message = f"Grid snap: {'on' if pm.grid_enabled else 'off'}"
                        else:
                            step = -1 if grid_clicked == "size_down" else 1
                            try:
                                idx = GRID_SIZES_FT.index(pm.grid_size)
                            except ValueError:
                                idx = GRID_SIZES_FT.index(GRID_SIZE_DEFAULT)
                            pm.grid_size = GRID_SIZES_FT[max(0, min(len(GRID_SIZES_FT) - 1, idx + step))]
                            controller.status_message = f"Grid size: {int(pm.grid_size)} ft"
                    elif snap_clicked is not None:
                        controller.placement.snap.set_mode(snap_clicked)
                        controller.status_message = (
                            f"Snap mode: {SNAP_MODE_LABELS[snap_clicked]}")
                    elif building_clicked is not None:
                        controller.active_building_type = building_clicked
                        controller.status_message = f"Building type: {building_clicked}"
                    elif sim_clicked is not None:
                        if sim_clicked == "trips":
                            controller.toggle_trip_demo()
                        elif sim_clicked == "paths":
                            controller.show_trip_paths = not controller.show_trip_paths
                            controller.status_message = (
                                f"Trip paths: {'on' if controller.show_trip_paths else 'off'}")
                        elif sim_clicked == "slider":
                            controller.trips_at_once = sidebar.sim_panel.value_at(raw_screen_pos)
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
        # Advance the simulation by real elapsed time (ms since the previous
        # frame's tick): release due trips (trip demo), cull arrived cars, and
        # move all vehicles. No-op when nothing is spawned.
        controller.update_traffic(clock.get_time() / 1000.0)

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
            sim_clock=((controller.trip_scheduler.day,
                        controller.trip_scheduler.day_name,
                        controller.trip_scheduler.clock_label(controller.clock_24h))
                       if controller.trip_scheduler is not None else None),
            building_preview=controller.get_building_preview(world_pos),
            selected_building=controller.selected_building,
            building_occupancy=controller.building_occupancy,
            grid_enabled=controller.placement.grid_enabled,
            grid_size=controller.placement.grid_size,
        )

        sidebar.draw(sidebar_rect, controller.current_tool,
                      controller.status_message, controller.sidebar_scroll,
                      controller.get_context_hint(), hovered=hovered,
                      snap_mode=controller.placement.snap.mode,
                      trips_on=controller.trip_scheduler is not None,
                      paths_on=controller.show_trip_paths,
                      trips_value=controller.trips_at_once,
                      active_building_type=controller.active_building_type,
                      grid_enabled=controller.placement.grid_enabled,
                      grid_size=controller.placement.grid_size,
                      clock_24h=controller.clock_24h,
                      mouse_pos=raw_screen_pos,
                      line_weight=ROAD_LINE_WEIGHT,
                      width_scale=road_style.ROAD_WIDTH_SCALE)

        pygame.display.flip()
        clock.tick(60)

    pygame.quit()
    sys.exit()


if __name__ == "__main__":
    main()
