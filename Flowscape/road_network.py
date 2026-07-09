"""
The RoadNetwork domain model: committed nodes, roads, zones and buildings in
WORLD space. No rendering, no input handling, no pygame.

Extracted verbatim from road_editor.py (REFACTOR_PLAN.md step 1) so the data
model can be imported without pulling in the editor/UI monolith.
"""

import math

import road_style
from road_style import get_road_profile
from road_geometry import (Node, Road, Zone, compute_control_point,
                            compute_road_geometry, _normalize2)
from buildings import Building
from destinations import BUILDING_TYPES, SMALL, MEDIUM, LARGE
from intersection_control import CONTROL_YIELD

NODE_HIT_RADIUS = 12

# Footprint side length (feet) by BuildingType.size; drawing and hit-testing
# both derive the square from this single table.
BUILDING_SIZE_FT = {SMALL: 30.0, MEDIUM: 55.0, LARGE: 80.0}


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

    def add_building(self, x, y, connection_node_ids=None,
                     building_type="Small House", data=None, seed=None):
        bid = self._next_building_id
        # Give each placement a stable seed so its randomized demand (vehicle
        # count, activity mix, departures) is reproducible. Default to the id:
        # deterministic, and re-rollable later by assigning a fresh seed.
        building = Building(id=bid, x=x, y=y,
                             building_type=building_type,
                             connection_node_ids=list(connection_node_ids or []),
                             seed=bid if seed is None else seed,
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

    def add_building_with_driveway(self, footprint_pos, main_node_id,
                                   building_type="Small House"):
        """Place a building with its first DRIVEWAY (model B). Shared by the
        Building tool and create_test_city. Extra driveways (higher egress
        throughput) can be added with add_driveway_to_building. Returns the
        building."""
        fx, fy = footprint_pos
        building = self.add_building(fx, fy, connection_node_ids=[],
                                     building_type=building_type)
        self.add_driveway_to_building(building.id, footprint_pos, main_node_id)
        return building

    def add_driveway_to_building(self, building_id, entrance_pos, main_node_id):
        """Give a building a DRIVEWAY: an off-road entrance node at `entrance_pos`
        + a short, narrow driveway road into `main_node_id` (which becomes a
        yielding junction). Cars originate at the entrance -- off the main road --
        and the existing routing / spawn / merge carry them on.

        A building may have SEVERAL driveways: generation picks among its entrance
        nodes (rng.choice), so the driveways spawn cars IN PARALLEL -- the fix for
        'a big building's fleet can't clear through one driveway'. Entrance nodes
        should be spaced apart (> spawn clearance) so they don't gate each other.
        Each driveway is recorded on building.data['driveways'] for the delete
        lifecycle. Returns the driveway road."""
        building = self.buildings[building_id]
        ex, ey = entrance_pos
        entrance = self.add_node(ex, ey)
        driveway = self.add_road(entrance.id, main_node_id)
        driveway.width = road_style.DRIVEWAY_ROAD_WIDTH
        driveway.data["profile"] = {"preset": "driveway"}
        # The driveway car turns onto the main road, so the junction YIELDS:
        # through (STRAIGHT) traffic keeps priority, turners defer. Safe even at
        # a shared intersection (the base reservation still prevents collisions).
        self.nodes[main_node_id].data["control"] = CONTROL_YIELD
        building.connection_node_ids.append(entrance.id)
        building.data.setdefault("driveways", []).append(
            {"entrance": entrance.id, "road": driveway.id, "main": main_node_id})
        return driveway

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
                # Centerline radius scales with the arm angle. The 1.25 floor
                # (vs the bare 1.0 = half-width) keeps the inner edge radius at
                # >= 0.25*half so the sharpest folds round into a small pocket
                # instead of pinching to a cusp; it still reaches 2*half at the
                # 90 deg boundary, matching the gentler continuation bends.
                radius = half * (1.25 + 0.75 * math.degrees(alpha) / 90.0)
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
