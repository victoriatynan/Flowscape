"""Finding plugins (M2 traffic operations + M3 horizontal geometry) + defaults."""

from .base import Finding, FindingResult
from .traffic import OverCapacity, ExcessCapacity
from .geometry import SSDDeficiency, CurveSpeedAdvisory, ShortBlockSpacing

DEFAULT_FINDINGS = (
    OverCapacity,
    ExcessCapacity,
    SSDDeficiency,
    CurveSpeedAdvisory,
    ShortBlockSpacing,
)
