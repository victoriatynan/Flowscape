"""
Flowscape Analysis Platform (Milestone 1 -- core framework).

A read-only layer that observes an immutable Snapshot of simulation state and
produces reusable analysis results. It never influences vehicle behavior,
routing, demand, or geometry. See ANALYSIS_PLATFORM_M1.md for the design.

Typical use:

    from analysis import analyze, StaticSource, RuntimeSource

    result = analyze(StaticSource(world.network))            # editor/map state
    result = analyze(RuntimeSource(world.session))           # running sim
    result.to_dict()                                         # JSON for the API
"""

from .snapshot import (Snapshot, StaticSource, RuntimeSource, build_snapshot)
from .models import AnalysisResult
from .engine import Pipeline
from .engine.registry import Registry
from .observations import DEFAULT_OBSERVATIONS, default_observation_registry
from .metrics import DEFAULT_METRICS
from .findings import DEFAULT_FINDINGS
from .recommendations import DEFAULT_RECOMMENDATIONS


def default_registry():
    """One Registry holding every default plugin across all four stages
    (observations, metrics, findings, recommendations). The engine resolves
    cross-stage `requires` dependencies and computes each result once; the
    pipeline then buckets results by each plugin's `kind`."""
    reg = Registry(kind="plugin")
    for cls in (DEFAULT_OBSERVATIONS + DEFAULT_METRICS
                + DEFAULT_FINDINGS + DEFAULT_RECOMMENDATIONS):
        reg.register(cls())
    return reg


def analyze(source, only=None) -> AnalysisResult:
    """Build a snapshot from `source` and run the full analysis pipeline on
    demand -- observations, then the metrics/findings/recommendations that
    depend on them. `only` optionally restricts to specific plugin ids (plus
    their transitive dependencies)."""
    snapshot = build_snapshot(source)
    return Pipeline(default_registry()).run(snapshot, only=only)
