"""Recommendation plugins (M2 traffic operations + M3 horizontal geometry)."""

from .base import Recommendation, RecommendationResult
from .traffic import AddCapacity, RightSizeRoad
from .geometry import (ImproveSightDistance, CurveWarningTreatment,
                       ConsolidateAccess)

DEFAULT_RECOMMENDATIONS = (
    AddCapacity,
    RightSizeRoad,
    ImproveSightDistance,
    CurveWarningTreatment,
    ConsolidateAccess,
)
