"""
Destination System: the background DATA layer for trip generation.

Strict separation (same philosophy as map_data.py): this module is pure
simulation data + logic. No pygame, no rendering, no input handling. It turns
*buildings on the road network* into *trips* (origin node -> destination node
+ a departure time), which the existing traffic_sim.TrafficSimulation then
turns into vehicles.

Design:
  - BuildingType  : shared, reusable definition (category, size, capacity,
                    operating hours). One per archetype, held in BUILDING_TYPES.
  - Building       : a lightweight placed instance that REFERENCES a
                    BuildingType by name (see buildings.Building). Category,
                    size, capacity and hours are NEVER duplicated onto an
                    instance; they are looked up from the type here.

What this module deliberately does NOT do (later-stage features): zoning, land
value, parking, transit, freight, procedural city generation, hundreds of
building types. Keep it simple and extensible.
"""

from dataclasses import dataclass

# ----------------------------------------------------------------------
# Categories: drive traffic demand and daily travel patterns.
# ----------------------------------------------------------------------
RESIDENTIAL = "Residential"
OFFICE = "Office"
RETAIL = "Retail"
SCHOOL = "School"
RECREATION = "Recreation"

CATEGORIES = (RESIDENTIAL, OFFICE, RETAIL, SCHOOL, RECREATION)

# ----------------------------------------------------------------------
# Sizes.
# ----------------------------------------------------------------------
SMALL = "Small"
MEDIUM = "Medium"
LARGE = "Large"

# ----------------------------------------------------------------------
# Operating hours per category, as 24h decimal hours (open_hour, close_hour).
# Residential is always-on (0 -> 24). These are the per-category defaults;
# a BuildingType carries its own hours (seeded from these) so individual
# types can diverge later without touching this table.
# ----------------------------------------------------------------------
CATEGORY_HOURS = {
    RESIDENTIAL: (0.0, 24.0),    # 24 hr
    OFFICE: (8.0, 17.0),         # 8 AM - 5 PM
    SCHOOL: (7.0, 15.0),         # 7 AM - 3 PM
    RETAIL: (9.0, 21.0),         # 9 AM - 9 PM
    RECREATION: (11.0, 23.0),    # 11 AM - 11 PM
}


@dataclass(frozen=True)
class BuildingType:
    """Shared, reusable definition of a building archetype. Frozen because a
    type is a constant: instances reference it, they never mutate it."""
    name: str
    category: str
    size: str
    capacity: int          # people/visitors -> how many trips it can source/sink
    open_hour: float       # 24h decimal
    close_hour: float      # 24h decimal


def _bt(name, category, size, capacity):
    """BuildingType with operating hours seeded from its category default."""
    open_hour, close_hour = CATEGORY_HOURS[category]
    return BuildingType(name, category, size, capacity, open_hour, close_hour)


# ----------------------------------------------------------------------
# Initial archetypes, the only building types for now. Enough to generate
# realistic commuting, school, shopping and evening-return traffic.
#   capacity = resident population (Residential), workers (Office/School staff
#   are folded into the student count for School), or peak visitors
#   (Retail/Recreation).
# NOTE: School (200 students) and Park (50 visitors) capacities were not
# specified; reasonable starting values, trivially tunable here.
# ----------------------------------------------------------------------
BUILDING_TYPES = {
    "House":        _bt("House",        RESIDENTIAL, SMALL,    3),
    "Apartment":    _bt("Apartment",    RESIDENTIAL, LARGE,   40),
    "Small Office": _bt("Small Office", OFFICE,      SMALL,   20),
    "Large Office": _bt("Large Office", OFFICE,      LARGE,  300),
    "Store":        _bt("Store",        RETAIL,      SMALL,   30),
    "School":       _bt("School",       SCHOOL,      MEDIUM, 200),
    "Park":         _bt("Park",         RECREATION,  MEDIUM,  50),
}


def building_type_of(building):
    """The BuildingType a placed Building instance references."""
    return BUILDING_TYPES[building.building_type]


# ----------------------------------------------------------------------
# Daily travel patterns: (origin_category -> destination_category) per period.
# Intentionally minimal; no advanced behavior yet.
# ----------------------------------------------------------------------
MORNING = "morning"
MIDDAY = "midday"
EVENING = "evening"

# Weekday patterns: work/school commute drives the day.
TRAVEL_PATTERNS = {
    MORNING: [
        (RESIDENTIAL, OFFICE),
        (RESIDENTIAL, SCHOOL),
    ],
    MIDDAY: [
        (OFFICE, RETAIL),
        (OFFICE, RECREATION),
    ],
    EVENING: [
        (OFFICE, RESIDENTIAL),
        (RETAIL, RESIDENTIAL),
        (RECREATION, RESIDENTIAL),
    ],
}

# Weekend patterns: NO WORK. Offices and schools are closed, so there is no
# commute. People still run errands and go out (leisure), so the day is built
# from home<->retail/recreation round trips instead.
WEEKEND_TRAVEL_PATTERNS = {
    MORNING: [
        (RESIDENTIAL, RECREATION),
    ],
    MIDDAY: [
        (RESIDENTIAL, RETAIL),
        (RESIDENTIAL, RECREATION),
    ],
    EVENING: [
        (RETAIL, RESIDENTIAL),
        (RECREATION, RESIDENTIAL),
    ],
}

# ----------------------------------------------------------------------
# Departure-time windows (24h decimal hours). Each agent gets a random time
# uniformly within its window so traffic spreads out instead of everyone
# leaving at the same instant.
# ----------------------------------------------------------------------
WORK_DEPARTURE_WINDOW = (7.5, 8.5)     # 7:30 - 8:30
SCHOOL_DEPARTURE_WINDOW = (7.0, 8.0)   # 7:00 - 8:00
DEFAULT_DEPARTURE_WINDOW = (9.0, 18.0)  # midday/evening trips spread broadly

# Which window applies to a (period, destination_category) trip.
def _departure_window(period, dest_category):
    if period == MORNING and dest_category == OFFICE:
        return WORK_DEPARTURE_WINDOW
    if period == MORNING and dest_category == SCHOOL:
        return SCHOOL_DEPARTURE_WINDOW
    return DEFAULT_DEPARTURE_WINDOW


# ----------------------------------------------------------------------
# Trip generation.
# ----------------------------------------------------------------------
@dataclass
class Trip:
    """One generated trip: travel from one building's attached node to
    another's, departing at a random time within the applicable window.
    `depart_hour` is a 24h decimal time. Feed (origin_node_id, dest_node_id)
    straight into TrafficSimulation.spawn_vehicle()."""
    origin_node_id: int
    dest_node_id: int
    depart_hour: float
    origin_building_id: int
    dest_building_id: int
    period: str


def _buildings_by_category(network):
    """Group placed buildings by their type's category. Only buildings that
    are attached to at least one road node can source/sink trips."""
    groups = {c: [] for c in CATEGORIES}
    for b in network.buildings.values():
        if not b.connection_node_ids:
            continue
        bt = BUILDING_TYPES.get(b.building_type)
        if bt is None:
            continue
        groups[bt.category].append(b)
    return groups


def generate_trips(network, rng, limit=None, weekend=False):
    """Generate one day's trips for every building on `network`.

    For each travel pattern in each period, every origin building of the
    source category sends `capacity` trips to randomly chosen destination
    buildings of the target category. Each trip departs at a random time in
    the applicable window. Returns a list[Trip] sorted by departure time.

    `weekend` selects the pattern set: weekdays run the work/school commute
    (TRAVEL_PATTERNS); weekends have NO WORK and run home<->leisure trips
    (WEEKEND_TRAVEL_PATTERNS) instead.

    `limit`, if given, randomly samples down to that many trips (keeping a
    spread across the day), useful for an on-screen demo where the full,
    realistic trip count would be too many vehicles to watch at once.

    Pure and deterministic given `rng` (pass random.Random(seed)). Reads the
    network read-only; spawns nothing itself.
    """
    groups = _buildings_by_category(network)
    trips = []

    pattern_set = WEEKEND_TRAVEL_PATTERNS if weekend else TRAVEL_PATTERNS
    for period, patterns in pattern_set.items():
        for src_cat, dst_cat in patterns:
            origins = groups.get(src_cat, [])
            dests = groups.get(dst_cat, [])
            if not origins or not dests:
                continue
            lo, hi = _departure_window(period, dst_cat)
            for origin in origins:
                src_type = BUILDING_TYPES[origin.building_type]
                for _ in range(src_type.capacity):
                    dest = rng.choice(dests)
                    trips.append(Trip(
                        origin_node_id=rng.choice(origin.connection_node_ids),
                        dest_node_id=rng.choice(dest.connection_node_ids),
                        depart_hour=rng.uniform(lo, hi),
                        origin_building_id=origin.id,
                        dest_building_id=dest.id,
                        period=period,
                    ))

    if limit is not None and len(trips) > limit:
        trips = rng.sample(trips, limit)

    trips.sort(key=lambda t: t.depart_hour)
    return trips
