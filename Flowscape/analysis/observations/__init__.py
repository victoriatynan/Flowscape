"""Observation plugins + the default registry of the Milestone 1 seven."""

from .base import Observation, ObservationResult
from .network import (RoadCount, IntersectionCount, TotalRoadLength,
                      BuildingCount, ConnectedComponents, BuildingMix)
from .traffic import VehicleCount, AverageVehicleSpeed, TrafficVolume
from .geometry import HorizontalCurvature, BlockLength

# The seven M1 observations, the M2 traffic-volume observation, the M3
# horizontal-geometry observations, and the M4 convergence-track building-mix
# observation, in a stable registration order (new entries appended so existing
# ids/order are unchanged).
DEFAULT_OBSERVATIONS = (
    RoadCount,
    IntersectionCount,
    TotalRoadLength,
    BuildingCount,
    VehicleCount,
    AverageVehicleSpeed,
    ConnectedComponents,
    TrafficVolume,
    HorizontalCurvature,
    BuildingMix,
    BlockLength,
)


def default_observation_registry():
    """A Registry populated with one instance of each default observation.

    Retained for callers (and tests) that want the observation stage alone; the
    full pipeline uses `analysis.default_registry()`, which also registers the
    metric/finding/recommendation stages."""
    from ..engine.registry import Registry
    reg = Registry(kind="observation")
    for cls in DEFAULT_OBSERVATIONS:
        reg.register(cls())
    return reg
