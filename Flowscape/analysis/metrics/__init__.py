"""Metric plugins (M2 traffic operations + M3 horizontal geometry) + defaults."""

from .base import Metric, MetricResult
from .traffic import (RoadCapacity, VolumeCapacityRatio, LevelOfService,
                      VehicleMilesTraveled)
from .geometry import (RequiredSSD, AvailableSSD, CurveAdvisorySpeed,
                       IntersectionDensity)

# The M2 traffic-operations and M3 horizontal-geometry metrics, in a dependency-
# friendly registration order (the resolver reorders by `requires`, but a stable
# order keeps output stable).
DEFAULT_METRICS = (
    RoadCapacity,
    VolumeCapacityRatio,
    LevelOfService,
    VehicleMilesTraveled,
    RequiredSSD,
    AvailableSSD,
    CurveAdvisorySpeed,
    IntersectionDensity,
)
