"""
The execution pipeline.

Pipeline wires the reusable primitives -- a Registry, the dependency resolver,
and a per-run ResultCache -- into one on-demand run over an immutable Snapshot.
It executes by DEPENDENCY, not by any hardcoded order, and computes each shared
result once.

Milestone 1 ran a single stage (observations). The primitives are stage-generic
by construction: a metric that `requires` an observation id is just an ordinary
dependency, so the resolver topologically sorts observations, metrics, findings
and recommendations together in ONE pass and the shared cache feeds each result
downstream as `deps` regardless of stage. Milestone 2 therefore adds NO resolver
or cache change -- it only PARTITIONS the single result cache by each plugin's
`kind` when packaging the AnalysisResult.
"""

import time

from .dependency_graph import resolve_order
from .cache import ResultCache
from ..models.result import AnalysisResult


class Pipeline:
    def __init__(self, registry):
        self.registry = registry

    def run(self, snapshot, only=None) -> AnalysisResult:
        """Resolve order, execute each plugin once, and package the results.

        `only` optionally restricts execution to the given ids plus their
        transitive dependencies (still returned in the result, so evidence is
        never hidden)."""
        order = resolve_order(self.registry.all(), only=only)
        cache = ResultCache(snapshot)

        for plugin in order:
            deps = {req: cache.results()[req] for req in plugin.requires}
            cache.get_or_compute(plugin, deps)

        # Partition the single result cache by each plugin's stage `kind`. A
        # plugin with an unrecognized kind falls back to observations so nothing
        # is ever silently dropped.
        results = cache.results()
        buckets = {"observation": {}, "metric": {},
                   "finding": {}, "recommendation": {}}
        computed_ids = {k: [] for k in buckets}
        for plugin in order:
            kind = getattr(plugin, "kind", "observation")
            if kind not in buckets:
                kind = "observation"
            buckets[kind][plugin.id] = results[plugin.id]
            computed_ids[kind].append(plugin.id)

        metadata = {
            "source_kind": snapshot.meta.source_kind,
            "is_running": snapshot.meta.is_running,
            "sim_time_hours": snapshot.meta.sim_time_hours,
            "tick": snapshot.meta.tick,
            "snapshot": snapshot.describe(),
            "snapshot_hash": hash(snapshot),
            "observation_ids": computed_ids["observation"],
            "metric_ids": computed_ids["metric"],
            "finding_ids": computed_ids["finding"],
            "recommendation_ids": computed_ids["recommendation"],
            "generated_at": time.time(),
        }
        return AnalysisResult(
            observations=buckets["observation"],
            metrics=buckets["metric"],
            findings=buckets["finding"],
            recommendations=buckets["recommendation"],
            metadata=metadata,
        )
