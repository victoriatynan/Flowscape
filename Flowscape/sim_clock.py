"""
Simulation clock + trip release (pure logic, no pygame, no rendering).

A TripScheduler advances a sim clock at an accelerated rate and releases each
trip exactly once when its departure time arrives, by invoking a spawn
callback. It does not know what "spawning" means (that's the traffic system's
job); it only decides WHEN each trip starts.

Trips are produced one DAY at a time by a `day_trip_factory(day_index)`
callback (day_index 0-based: 0 = the first day). The scheduler is open-ended:
as the clock crosses midnight it asks the factory for the next day's trips, so
the sim runs continuously, week after week. The factory is where day-of-week
rules live (e.g. no work on weekends); the scheduler stays oblivious to
what each day contains.

This is the bridge between the destination DATA layer and whatever consumes
trips: the editor wires the callback to TrafficSimulation.spawn_trip().
"""

HOURS_PER_DAY = 24
DAY_NAMES = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]


def format_time(time, use_24h=True):
    """A clock time (decimal hours, wraps past midnight) as a string:
    24-hour 'HH:MM', or 12-hour 'H:MM AM/PM' when use_24h is False."""
    h = int(time) % HOURS_PER_DAY
    m = int((time - int(time)) * 60)
    if use_24h:
        return f"{h:02d}:{m:02d}"
    suffix = "AM" if h < 12 else "PM"
    h12 = h % 12 or 12
    return f"{h12}:{m:02d} {suffix}"


class TripScheduler:
    """Releases trips over a continuous, multi-day accelerated clock.

    `time` advances by `hours_per_second` of sim-time per real second. Each
    day's trips come from `day_trip_factory(day_index)`, a list of trips
    whose `depart_hour` is in [0, 24); the scheduler shifts them to absolute
    time (day_index * 24 + depart_hour) and releases them in order, once each.
    """

    def __init__(self, day_trip_factory, start_hour=6.0, hours_per_second=0.5):
        self.factory = day_trip_factory
        self.start_hour = start_hour
        self.hours_per_second = hours_per_second
        self.time = start_hour
        # Absolute-time queue [(abs_depart_hour, trip), ...], kept in order;
        # _next is the index of the next trip to release.
        self._queue = []
        self._next = 0
        self._generated_through = -1   # highest day_index generated so far
        self._ensure_generated()

    def _ensure_generated(self):
        """Generate any day(s) the clock has reached but we haven't built yet.
        Days are generated in order and each day's departures are strictly
        later than the previous day's, so the queue stays sorted by appending
        (no re-sort needed)."""
        current_day = int(self.time // HOURS_PER_DAY)
        while self._generated_through < current_day:
            day = self._generated_through + 1
            base = day * HOURS_PER_DAY
            for trip in self.factory(day):
                self._queue.append((base + trip.depart_hour, trip))
            self._generated_through = day

    def update(self, dt_seconds, spawn):
        """Advance the clock by `dt_seconds` of real time, materialize any new
        day(s) reached, and release every trip now due. `spawn(trip)` is
        called once per released trip."""
        self.time += dt_seconds * self.hours_per_second
        self._ensure_generated()
        while self._next < len(self._queue) and self._queue[self._next][0] <= self.time:
            spawn(self._queue[self._next][1])
            self._next += 1

    @property
    def released(self):
        return self._next

    @property
    def day(self):
        """Day number, starting at 1 (sim time runs continuously past 24h)."""
        return int(self.time // HOURS_PER_DAY) + 1

    @property
    def day_name(self):
        """Weekday abbreviation; day 1 is Monday, day 6/7 are Sat/Sun."""
        return DAY_NAMES[(self.day - 1) % 7]

    @property
    def is_weekend(self):
        return (self.day - 1) % 7 >= 5

    def clock_label(self, use_24h=True):
        """Current sim time formatted 24h or 12h (AM/PM)."""
        return format_time(self.time, use_24h)

    @property
    def time_label(self):
        """Current sim time as an HH:MM 24h string (wraps past midnight)."""
        return format_time(self.time, use_24h=True)

    def reset(self):
        self.time = self.start_hour
        self._queue = []
        self._next = 0
        self._generated_through = -1
        self._ensure_generated()
