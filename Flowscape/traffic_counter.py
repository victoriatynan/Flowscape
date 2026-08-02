"""
Simulation-derived traffic volume: count how many vehicles actually TRAVERSE
each road over a rolling, configurable time window.

This is the honest measure of volume the Analysis Platform's V/C and Level of
Service metrics consume: not trips requested (demand) and not theoretical
capacity, but the vehicles that really passed over each road. Volume is a
property of where cars travel, so we observe road ENTRIES from the live sim.

Design (deliberately non-invasive):
  * The counter lives at the SESSION level and never touches Vehicle/traffic_sim.
    Each tick, after physics, `record()` reads every vehicle's current road id
    (`vehicle.current_lane[0]`) and, when it differs from the road that vehicle
    was last seen on, logs one traversal event `(sim_time_hours, road_id)`.
  * The log is a rolling window keyed on sim-hours; entries older than
    `window_hours` are pruned. `volume_per_hour()` turns the windowed counts
    into veh/hr per road.

Known limitations (acceptable for Milestone 2, documented for honesty):
  * In unified fast-forward the physics sub-steps run several times per tick but
    `record()` runs once per tick, so a vehicle that crosses more than one road
    within a single tick is undercounted. At normal speed each tick is ~one
    motion step, so this does not arise.
  * Right after start (or a window resize) fewer than `window_hours` of sim have
    elapsed, so dividing the count by the full window under-reports the rate
    until the window fills -- a normal warm-up artifact.
"""

from collections import deque

# Default rolling window, in decimal sim-HOURS (the demand-clock unit).
DEFAULT_WINDOW_HOURS = 1.0


class TrafficCounter:
    def __init__(self, window_hours=DEFAULT_WINDOW_HOURS):
        self.window_hours = window_hours
        # Rolling log of (sim_time_hours, road_id), oldest first.
        self._log = deque()
        # Last road id each vehicle (by stable vid) was seen on, so we log one
        # event per road ENTRY rather than once per tick.
        self._last_road = {}

    def record(self, vehicles, now):
        """Log a traversal for every vehicle that has entered a new road since
        it was last seen, then drop events older than the window.

        `vehicles` -- the live vehicle objects (each with `.vid` and
                      `.current_lane`, a lane_id tuple whose [0] is the road id).
        `now`      -- current sim time in decimal hours.
        """
        seen = set()
        for v in vehicles:
            lane = getattr(v, "current_lane", None)
            if not lane:                     # unrouted / blocked with no lane yet
                continue
            vid = v.vid
            seen.add(vid)
            road_id = lane[0]
            if self._last_road.get(vid) != road_id:
                self._log.append((now, road_id))
                self._last_road[vid] = road_id
        # Forget vehicles that are gone (arrived/culled); vids are never reused,
        # so this only bounds memory and never loses a real re-entry.
        if len(self._last_road) > len(seen):
            self._last_road = {vid: r for vid, r in self._last_road.items()
                               if vid in seen}
        self._prune(now)

    def _prune(self, now):
        cutoff = now - self.window_hours
        log = self._log
        while log and log[0][0] < cutoff:
            log.popleft()

    def counts(self, now):
        """{road_id: traversals within the current window}."""
        cutoff = now - self.window_hours
        out = {}
        for t, road_id in self._log:
            if t >= cutoff:
                out[road_id] = out.get(road_id, 0) + 1
        return out

    def volume_per_hour(self, now):
        """{road_id: veh/hr} over the window = windowed count / window_hours."""
        if self.window_hours <= 0:
            return {}
        return {road_id: n / self.window_hours
                for road_id, n in self.counts(now).items()}
