"""Prototype: the UNIFIED single-clock mode vs the DECOUPLED shipping default.

    ../venv/Scripts/python.exe prototype_unified.py

Why this exists
---------------
The DECOUPLED model (the default, SimulationSession(unified=False)) runs an
accelerated DEMAND clock over REAL-TIME motion: a 24 h day in ~4 real minutes,
with cars driving at a believable ~30 mph. It physically cannot show a full
day's realistic demand -- the road can't carry a whole day's trips in four
minutes -- so demand is throttled (DEMO_TRIP_LIMIT) to what the road absorbs.

The UNIFIED model (SimulationSession(unified=True)) runs ONE clock: motion,
demand, and expiry all advance together in sim-time at `time_scale` sim-seconds
per real second. The physics is SUB-STEPPED (ceil(time_scale) tick-sized steps
per tick) so it stays stable instead of teleporting 264 ft/tick. Because the
road now runs as fast as demand arrives, it absorbs the *full* day's trips with
~no expiry -- at the cost of ceil(time_scale)x the physics compute, and a day
that takes 86400/time_scale real seconds to watch.

Section A shows the trip funnel (does demand survive?). Section B shows the
compute/watch-time trade as time_scale climbs. Together they show why the demo
ships decoupled and why unified is a "real simulator" mode, not a drop-in.
"""

import time

from sim_session import (SimulationSession, DEMO_TRIP_LIMIT, DEMO_START_HOUR,
                         DEMO_HOURS_PER_SEC)
from test_city import create_test_city

FULL_DAY_SIM_HOURS = 24.0   # loss accrues across the whole day (both rushes)


def _run_window(sim_hours, **kw):
    """Build a session and tick until `sim_hours` of SIM time have elapsed.
    Returns the funnel + cost stats over that window."""
    s = SimulationSession(create_test_city(), **kw)
    end = s.scheduler.start_hour + sim_hours
    peak = 0
    max_sub = 0
    t0 = time.perf_counter()
    while s.scheduler.time < end:
        s.tick()
        peak = max(peak, len(s.traffic.vehicles))
        max_sub = max(max_sub, s.last_substeps)
    wall = time.perf_counter() - t0
    snap = s.snapshot()
    return dict(released=snap["released"], spawned=s.spawn_queue.spawned_total,
                expired=snap["expired"], no_path=snap["dropped_no_path"],
                peak=peak, substeps=max_sub, ticks=s.tick_count, wall=wall)


def section_a_funnel():
    print("=" * 74)
    print("SECTION A -- trip funnel over one full sim-day (same 4-min day for all)")
    print("=" * 74)
    scenarios = [
        ("decoupled  trips=60  (shipping default)",
         dict(trip_limit=60)),
        ("decoupled  trips=200 (overloaded -- demand >> real road)",
         dict(trip_limit=200)),
        ("unified    trips=200 time_scale=360 (road runs on the fast clock too)",
         dict(trip_limit=200, unified=True, time_scale=360.0)),
    ]
    hdr = (f"{'scenario':<64}{'rel':>5}{'spawn':>6}{'exp':>5}{'exp%':>6}"
           f"{'peak':>5}{'sub':>5}")
    print(hdr)
    print("-" * len(hdr))
    for label, kw in scenarios:
        r = _run_window(FULL_DAY_SIM_HOURS, **kw)
        exp_pct = r["expired"] / r["released"] if r["released"] else 0.0
        print(f"{label:<64}{r['released']:>5}{r['spawned']:>6}{r['expired']:>5}"
              f"{exp_pct:>6.0%}{r['peak']:>5}{r['substeps']:>5}")
    print("\nRead: the decoupled road caps at ~40 cars, so trips=200 sheds the")
    print("excess to expiry. Unified drives the SAME 4-min day, but the road runs")
    print("on the fast clock too, so it absorbs the same 200 trips with ~no loss")
    print("-- one honest clock, no throttle -- at 360 physics sub-steps/tick.\n")


def section_b_cost():
    print("=" * 74)
    print("SECTION B -- unified compute vs watch-time as time_scale climbs")
    print("=" * 74)
    print("(200 ticks each; per-tick cost ~ scales with the sub-step count)\n")
    hdr = (f"{'time_scale':>10}{'substeps/tick':>14}{'day-in-real':>14}"
           f"{'ms/tick':>10}")
    print(hdr)
    print("-" * len(hdr))
    for ts in (1, 4, 8, 16, 60, 360):
        s = SimulationSession(create_test_city(), trip_limit=200,
                              unified=True, time_scale=float(ts))
        s.run(60)                      # warm up (get some cars on the road)
        t0 = time.perf_counter()
        s.run(200)
        ms = (time.perf_counter() - t0) / 200 * 1000.0
        day_real_sec = 86400.0 / ts
        if day_real_sec >= 3600:
            day_str = f"{day_real_sec / 3600:.1f} hr"
        elif day_real_sec >= 60:
            day_str = f"{day_real_sec / 60:.1f} min"
        else:
            day_str = f"{day_real_sec:.0f} s"
        print(f"{ts:>10}{s.last_substeps:>14}{day_str:>14}{ms:>10.2f}")
    print("\nRead: matching the decoupled demo's 4-min day means time_scale=360 ->")
    print("360 physics sub-steps every tick. Realistic motion at a watchable")
    print("day-length lives around time_scale 8-16 (a 1.5-3 hr day) -- a")
    print("simulator you leave running, not a 4-minute demo.\n")


if __name__ == "__main__":
    print(f"\ndefaults: DEMO_TRIP_LIMIT={DEMO_TRIP_LIMIT}, "
          f"DEMO_HOURS_PER_SEC={DEMO_HOURS_PER_SEC} "
          f"(decoupled = a {24 / DEMO_HOURS_PER_SEC / 60:.0f}-min day)\n")
    section_a_funnel()
    section_b_cost()
