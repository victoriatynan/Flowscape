"""
Vehicle Spawn Queue -- the release/visibility stage between the TripScheduler
(WHEN a trip is due) and the TrafficSimulation (a car actually on the road).

Why this exists: the scheduler can make many trips come due in the same frame
(rush hour). Spawning them all at once -- or, worse, dropping the ones that
don't immediately fit -- is what made departures invisible. The queue instead
holds released trips and lets them out over time, so the player sees a steady,
ordered stream of cars leaving buildings.

Each frame the queue:
  - EXPIRES trips that have waited too long (bounds the backlog and stops one
    day's congestion bleeding into the next), and
  - DRAINS the rest into the simulation under two limits:
      * capacity  -- how many cars may exist at once (free_slots), and
      * rate (R)  -- how many may *appear* per real second (token bucket).
A trip the simulation can't place yet (its origin lane start is still occupied)
stays pending and is retried next frame: it waits, it is not dropped.

Priority order (also the debugging order):
    1. Scheduler decides who is READY     (releases due trips)
    2. Queue     decides who is ELIGIBLE  (route resolved, not expired)
    3. Capacity  decides who can EXIST    (free_slots)
    4. Rate (R)  decides who is VISIBLE   (token bucket) this frame

Pure logic: no pygame, no rendering. Determinism is preserved -- the queue only
changes WHEN a car appears, never which trips exist or their order. A trip's
route is resolved ONCE before it is enqueued, so retries never re-run
pathfinding; expiry never credits building occupancy (a failed attempt means
the origin stays truthfully "full").
"""

from collections import deque
from enum import Enum, auto

# Defaults (tunable -- expect to nudge these while watching the sim).
DEFAULT_RATE_PER_SEC = 4.0     # cars made visible per real second
DEFAULT_TOKEN_CAP = 2.0        # max burst the bucket can save up after a lull
DEFAULT_MAX_WAIT_HOURS = 3.0   # sim-hours a trip may wait before it expires.
# Measured: with the ~0.1 clock, grace 1h->3h cuts evening trip loss ~29%->~12%
# (more trips complete) at the cost of a slightly smeared peak -- cars can pull
# out up to this many sim-hours after their scheduled departure.


class SpawnResult(Enum):
    """Outcome of a single spawn attempt, returned by the drain callback."""
    SPAWNED = auto()   # a car was placed -- consumes a slot and a token
    BLOCKED = auto()   # origin lane start occupied -- keep pending, retry later
    INVALID = auto()   # route no longer exists (map changed) -- drop it


class _Pending:
    __slots__ = ("trip", "path", "enqueued_time")

    def __init__(self, trip, path, enqueued_time):
        self.trip = trip
        self.path = path
        self.enqueued_time = enqueued_time


class SpawnQueue:
    """Holds released-but-unspawned trips and drains them under a rate + slot
    budget. See module docstring for the four-gate model."""

    def __init__(self, rate_per_sec=DEFAULT_RATE_PER_SEC,
                 token_cap=DEFAULT_TOKEN_CAP,
                 max_wait_hours=DEFAULT_MAX_WAIT_HOURS):
        self.rate = rate_per_sec
        self.token_cap = token_cap
        self.max_wait = max_wait_hours
        self._pending = deque()
        self._tokens = 0.0
        # Running tallies for status/debug overlays.
        self.dropped_no_path = 0
        self.expired = 0
        self.spawned_total = 0

    @property
    def depth(self):
        return len(self._pending)

    def enqueue(self, trip, path, now):
        """Add a released trip whose route is ALREADY resolved (the caller drops
        no-path trips before calling this). `now` is the scheduler's sim-time,
        used as the start of this trip's wait clock."""
        self._pending.append(_Pending(trip, path, now))

    def expire(self, now):
        """Drop trips that have waited longer than `max_wait`. Returns the list
        of expired trips. Expiry does NOT credit occupancy: the attempt failed,
        so the origin building stays "full" (truthful congestion)."""
        if not self._pending:
            return []
        kept = deque()
        expired = []
        for p in self._pending:
            if now - p.enqueued_time > self.max_wait:
                expired.append(p.trip)
            else:
                kept.append(p)
        self._pending = kept
        self.expired += len(expired)
        return expired

    def drain(self, dt_seconds, free_slots, spawn):
        """Spawn pending trips into the simulation under the rate + slot budget.

        `spawn(trip, path) -> SpawnResult`. Returns the list of trips actually
        spawned this frame (so the caller can decrement origin occupancy).

        FIFO order: a BLOCKED trip is retained for next frame (no token spent,
        so a busy origin never head-of-line-blocks the queue), an INVALID trip
        is dropped, and any trip left unattempted when the budget runs out stays
        pending in order."""
        self._tokens = min(self.token_cap, self._tokens + self.rate * dt_seconds)
        spawned = []
        if not self._pending:
            return spawned
        kept = deque()
        slots = free_slots
        items = list(self._pending)
        i, n = 0, len(items)
        while i < n:
            if self._tokens < 1.0 or slots <= 0:
                kept.extend(items[i:])   # budget spent -- keep the rest in order
                break
            p = items[i]
            i += 1
            res = spawn(p.trip, p.path)
            if res == SpawnResult.SPAWNED:
                spawned.append(p.trip)
                self._tokens -= 1.0
                slots -= 1
            elif res == SpawnResult.BLOCKED:
                kept.append(p)           # waits its turn, retried next frame
            # SpawnResult.INVALID: dropped (not kept)
        self._pending = kept
        self.spawned_total += len(spawned)
        return spawned

    def clear(self):
        self._pending.clear()
        self._tokens = 0.0
