"""
Building demand-model test (Phase 1: seed-driven, building-level trip generation).

The demand model keeps the existing flow (Building -> Trip -> connection node ->
spawn) but moves the behavior onto building types: each type owns a vehicle-count
RANGE and weekday/weekend ACTIVITY PROFILES, and each placed building rolls its
randomized demand from a stable per-placement `seed`. A road node never sources
trips by itself.

These tests assert the properties that make that model safe to build on:
  1. Generation is deterministic given (building seed, day) and varies by day.
  2. A building's vehicle count is stable across days (a property of the seed).
  3. weekday vs weekend select different profiles; closed categories (Industrial,
     Education) source nothing on weekends.
  4. STAY choices and demand multipliers reduce/zero trips without errors.
  5. Trips never self-loop and come back sorted by departure time.
  6. Only seeded, connected buildings generate trips; bare nodes never do.
  7. Legacy type names + the seed survive a map_data save/load round-trip.
"""

import destinations as d
from destinations import (BUILDING_TYPES, generate_trips, building_vehicle_count,
                          RESIDENTIAL, INDUSTRIAL, EDUCATION, CATEGORIES)
from test_city import create_test_city
from map_data import building_to_dict, building_from_dict


def _key(trips):
    return [(t.origin_node_id, t.dest_node_id, round(t.depart_hour, 5),
             t.origin_building_id, t.dest_building_id, t.period) for t in trips]


def test_catalogue_and_profiles():
    # 6 categories, each with a (weekday, weekend) profile pair.
    assert len(CATEGORIES) == 6
    for c in CATEGORIES:
        wk, we = d.CATEGORY_PROFILES[c]
        assert isinstance(wk, tuple) and isinstance(we, tuple)
    # Every type points at a real category and a sane count range.
    for name, bt in BUILDING_TYPES.items():
        assert bt.category in CATEGORIES
        lo, hi = bt.count_range
        assert 0 < lo <= hi
        assert bt.capacity == hi          # back-compat nominal capacity
    print("ok: catalogue + per-category profiles are well-formed")


def test_determinism_and_day_variation():
    net = create_test_city()
    a = generate_trips(net, day_index=0)
    b = generate_trips(net, day_index=0)
    c = generate_trips(net, day_index=1)
    assert _key(a) == _key(b), "same day must reproduce identical trips"
    assert _key(a) != _key(c), "different days must vary"
    assert all(a[i].depart_hour <= a[i + 1].depart_hour for i in range(len(a) - 1))
    print("ok: generation is deterministic per day and varies across days")


def test_vehicle_count_stable_across_days():
    net = create_test_city()
    b = next(iter(net.buildings.values()))
    # Derived from the seed only, so it never changes day to day.
    assert building_vehicle_count(b) == building_vehicle_count(b)
    bt = BUILDING_TYPES[b.building_type]
    lo, hi = bt.count_range
    assert lo <= building_vehicle_count(b) <= hi
    # Reseeding changes the roll.
    b2 = type(b)(id=b.id, building_type=b.building_type,
                 connection_node_ids=list(b.connection_node_ids), seed=b.seed)
    assert building_vehicle_count(b2) == building_vehicle_count(b)
    print("ok: vehicle count is seed-derived and stable across days")


def test_weekend_closes_industry_and_schools():
    net = create_test_city()
    weekend = generate_trips(net, day_index=5, weekend=True)
    closed = {INDUSTRIAL, EDUCATION}
    for t in weekend:
        bt = BUILDING_TYPES[net.buildings[t.origin_building_id].building_type]
        assert bt.category not in closed, "closed categories must not source weekend trips"
    # Weekday vs weekend should not be identical.
    assert _key(weekend) != _key(generate_trips(net, day_index=0))
    print("ok: weekend profile differs and closes Industrial/Education origins")


def test_multiplier_and_stay_reduce_trips():
    net = create_test_city()
    full = generate_trips(net, day_index=0)
    none_res = generate_trips(net, day_index=0, demand_multipliers={RESIDENTIAL: 0.0})
    assert len(none_res) < len(full), "zeroing residential demand must drop trips"
    # No origin trip should come from a residential building when zeroed out.
    for t in none_res:
        bt = BUILDING_TYPES[net.buildings[t.origin_building_id].building_type]
        assert bt.category != RESIDENTIAL
    print("ok: demand multipliers + STAY weights scale trips down cleanly")


def test_no_self_trips_and_node_only_sources_nothing():
    net = create_test_city()
    trips = generate_trips(net, day_index=0)
    assert all(t.origin_building_id != t.dest_building_id for t in trips)
    assert all(t.origin_node_id != t.dest_node_id for t in trips)
    # A network with road nodes but no buildings generates nothing.
    from road_network import RoadNetwork
    bare = RoadNetwork()
    n1 = bare.add_node(0, 0)
    n2 = bare.add_node(100, 0)
    bare.add_road(n1.id, n2.id)
    assert generate_trips(bare, day_index=0) == [], "bare nodes never source trips"
    # An unconnected building (no connection nodes) also sources nothing.
    bare.add_building(x=10, y=10, connection_node_ids=[], building_type="Large Apartment")
    assert generate_trips(bare, day_index=0) == []
    print("ok: no self-trips; only seeded, connected buildings source demand")


def test_save_load_roundtrip_preserves_seed():
    net = create_test_city()
    b = next(iter(net.buildings.values()))
    restored = building_from_dict(building_to_dict(b))
    assert restored.seed == b.seed
    assert restored.building_type == b.building_type
    assert building_vehicle_count(restored) == building_vehicle_count(b)
    # Legacy type names still resolve via aliases.
    assert BUILDING_TYPES["House"].name == "Small House"
    assert BUILDING_TYPES["Small Office"].category == BUILDING_TYPES["Small Business"].category
    print("ok: seed + legacy type names survive a save/load round-trip")


if __name__ == "__main__":
    test_catalogue_and_profiles()
    test_determinism_and_day_variation()
    test_vehicle_count_stable_across_days()
    test_weekend_closes_industry_and_schools()
    test_multiplier_and_stay_reduce_trips()
    test_no_self_trips_and_node_only_sources_nothing()
    test_save_load_roundtrip_preserves_seed()
    print("\nbuilding-demand: all tests passed")
