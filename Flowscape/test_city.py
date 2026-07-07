"""
Handcrafted destination-system test city (the permanent fixed map).

A deterministic RoadNetwork with a simple grid road network and a fixed set of
buildings, the spec's reference city:

    20 Small Houses, 2 Large Apartments, 1 High School, 1 Large Business,
    2 Small Businesses, 2 Retail, 1 Park

Each building references a BuildingType (destinations.BUILDING_TYPES) and gets
its own DRIVEWAY (model B): an off-road entrance node + a short driveway road
into its grid node, so cars originate off the road and merge on. This lets
destinations.generate_trips() + the existing traffic_sim drive it end to end.
Pure data: no rendering, no input.
"""

from destinations import generate_trips  # noqa: F401 (convenience re-export)

GRID_COLS = 6
GRID_ROWS = 5
GRID_SPACING_FT = 300.0
BUILDING_OFFSET_FT = 45.0   # nudge each building off its road node

# building_type -> count. Sums to 29.
CITY_BUILDINGS = [
    ("Small House", 20),
    ("Large Apartment", 2),
    ("High School", 1),
    ("Large Business", 1),
    ("Small Business", 2),
    ("Retail", 2),
    ("Park", 1),
]


def _grid_node_order(grid):
    """Deterministic node iteration: row-major by (row, col)."""
    return [grid[(c, r)] for r in range(GRID_ROWS) for c in range(GRID_COLS)]


def create_test_city():
    """Build and return the fixed test-city RoadNetwork (grid roads + the
    fixed building set, each attached to a node)."""
    from road_editor import RoadNetwork  # runtime import: avoids a module cycle

    net = RoadNetwork()

    # Grid intersection nodes.
    grid = {}
    for r in range(GRID_ROWS):
        for c in range(GRID_COLS):
            grid[(c, r)] = net.add_node(c * GRID_SPACING_FT, r * GRID_SPACING_FT)

    # Horizontal street segments.
    for r in range(GRID_ROWS):
        for c in range(GRID_COLS - 1):
            net.add_road(grid[(c, r)].id, grid[(c + 1, r)].id)
    # Vertical street segments.
    for c in range(GRID_COLS):
        for r in range(GRID_ROWS - 1):
            net.add_road(grid[(c, r)].id, grid[(c, r + 1)].id)

    # Place buildings, one per node in deterministic order, each attached to
    # the node it sits beside.
    nodes = _grid_node_order(grid)
    flat = [bt for bt, count in CITY_BUILDINGS for _ in range(count)]
    for building_type, node in zip(flat, nodes):
        # Each building gets its own driveway (model B): an off-road entrance
        # node + a short driveway road into the grid node, so cars originate off
        # the road and merge on. Same path the Building tool uses.
        net.add_building_with_driveway(
            (node.x + BUILDING_OFFSET_FT, node.y + BUILDING_OFFSET_FT),
            node.id, building_type=building_type)

    return net


if __name__ == "__main__":
    net = create_test_city()
    print(f"Test city: {len(net.nodes)} nodes, {len(net.roads)} roads, "
          f"{len(net.buildings)} buildings")
    trips = generate_trips(net, day_index=0)
    print(f"Generated {len(trips)} trips")
    for t in trips[:8]:
        print(f"  {t.depart_hour:5.2f}h  node {t.origin_node_id} -> "
              f"{t.dest_node_id}  ({t.period})")
