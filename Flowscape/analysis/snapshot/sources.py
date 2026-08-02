"""
Snapshot sources: adapters from live state to the builder.

Both sources implement the SAME small interface -- a `.network`, an
`.is_running`/`kind`/timing triplet, and `raw_vehicles()` -- so the builder
(and everything downstream) is agnostic to whether the facts came from the
editor's static map or a running/replayed simulation. A source holds RAW state
only; unit normalization happens in one place, the builder.
"""


class StaticSource:
    """Facts from the editor's map (a RoadNetwork), with no simulation running.
    Carries no vehicles and no clock."""

    kind = "static"
    is_running = False
    sim_time_hours = None
    tick = None

    def __init__(self, network):
        self.network = network

    def raw_vehicles(self):
        return ()

    def road_volumes(self):
        """No simulation -> no measured volume."""
        return {}


class RuntimeSource:
    """Facts from a live (or replayed) SimulationSession. Reads the session's
    plain-data snapshot ONCE at construction so a single analysis run sees a
    single, consistent instant -- and never advances or mutates the sim."""

    kind = "runtime"
    is_running = True

    def __init__(self, session):
        self.session = session
        self.network = session.network
        # SimulationSession.snapshot() is already the plain-data view a client
        # renders: vehicles (speed in ft/s), sim time in decimal hours, tick.
        self._snap = session.snapshot()
        self.sim_time_hours = self._snap.get("time")
        self.tick = self._snap.get("tick")

    def raw_vehicles(self):
        return self._snap.get("vehicles", ())

    def road_volumes(self):
        """Simulation-derived per-road volume, {road_id: veh_per_hr}, measured
        over the session's rolling window at this instant."""
        return self._snap.get("road_volumes", {})
