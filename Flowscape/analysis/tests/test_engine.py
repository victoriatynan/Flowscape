"""
Engine tests: registry, dependency resolution, caching, and pipeline execution.

These use tiny FIXTURE plugins with a real dependency chain (A -> B -> C) and a
cycle, so the ordering + single-compute guarantees are exercised WITHOUT forcing
an artificial dependency into the shipped (independent) observations.
"""

import pytest

from analysis.observations.base import Observation, ObservationResult
from analysis.metrics.base import Metric, MetricResult
from analysis.findings.base import Finding, FindingResult
from analysis.snapshot.models import Snapshot, SnapshotMeta
from analysis.engine.registry import Registry, DuplicatePluginError
from analysis.engine.dependency_graph import (
    resolve_order, CycleError, MissingDependencyError)
from analysis.engine.cache import ResultCache
from analysis.engine.pipeline import Pipeline


def _empty_snapshot():
    return Snapshot(roads=(), nodes=(), buildings=(), vehicles=(),
                    meta=SnapshotMeta(source_kind="static", is_running=False))


# --- fixture plugins: A independent, B needs A, C needs A and B -------------

class A(Observation):
    id = "A"
    category = "fixture"
    def compute(self, snapshot, deps):
        return ObservationResult(self.id, self.category, value=1)


class B(Observation):
    id = "B"
    category = "fixture"
    requires = ("A",)
    def compute(self, snapshot, deps):
        return ObservationResult(self.id, self.category, value=deps["A"].value + 1)


class C(Observation):
    id = "C"
    category = "fixture"
    requires = ("A", "B")
    def compute(self, snapshot, deps):
        return ObservationResult(self.id, self.category,
                                 value=deps["A"].value + deps["B"].value)


class D(Observation):   # independent, unrelated to A/B/C
    id = "D"
    category = "fixture"
    def compute(self, snapshot, deps):
        return ObservationResult(self.id, self.category, value=99)


# --- registry ---------------------------------------------------------------

def test_registry_registers_and_gets():
    reg = Registry(kind="observation")
    a = reg.register(A())
    assert reg.get("A") is a
    assert "A" in reg and len(reg) == 1
    assert reg.ids() == ["A"]


def test_registry_rejects_duplicate_id():
    reg = Registry()
    reg.register(A())
    with pytest.raises(DuplicatePluginError):
        reg.register(A())


def test_registry_rejects_idless_plugin():
    class NoId(Observation):
        id = ""
    with pytest.raises(ValueError):
        Registry().register(NoId())


# --- dependency ordering ----------------------------------------------------

def test_resolve_order_puts_dependencies_first():
    order = [p.id for p in resolve_order([C(), B(), A()])]
    assert order.index("A") < order.index("B") < order.index("C")


def test_resolve_order_detects_cycle():
    class X(Observation):
        id = "X"; requires = ("Y",)
    class Y(Observation):
        id = "Y"; requires = ("X",)
    with pytest.raises(CycleError):
        resolve_order([X(), Y()])


def test_resolve_order_flags_missing_dependency():
    class Lonely(Observation):
        id = "L"; requires = ("nope",)
    with pytest.raises(MissingDependencyError):
        resolve_order([Lonely()])


def test_only_restricts_to_requested_plus_transitive_deps():
    order = [p.id for p in resolve_order([A(), B(), C(), D()], only=["B"])]
    assert set(order) == {"A", "B"}          # C and D excluded
    assert order.index("A") < order.index("B")


# --- cache: shared dependency computed exactly once -------------------------

def test_cache_computes_shared_dependency_once():
    cache = ResultCache(_empty_snapshot())
    for plugin in resolve_order([A(), B(), C()]):
        deps = {r: cache.results()[r] for r in plugin.requires}
        cache.get_or_compute(plugin, deps)
    # A is required by both B and C but must run only once.
    assert cache.compute_counts == {"A": 1, "B": 1, "C": 1}
    # Dependency values threaded correctly: B = A+1 = 2, C = A+B = 3.
    assert cache.results()["B"].value == 2
    assert cache.results()["C"].value == 3


def test_cache_second_get_returns_memoized():
    cache = ResultCache(_empty_snapshot())
    first = cache.get_or_compute(A(), {})
    second = cache.get_or_compute(A(), {})
    assert first is second
    assert cache.compute_counts["A"] == 1


# --- pipeline ---------------------------------------------------------------

def test_pipeline_runs_all_and_reports_metadata():
    reg = Registry()
    for cls in (A, B, C):
        reg.register(cls())
    result = Pipeline(reg).run(_empty_snapshot())
    assert set(result.observations) == {"A", "B", "C"}
    assert result.metadata["source_kind"] == "static"
    assert result.metadata["observation_ids"].index("A") < \
        result.metadata["observation_ids"].index("C")


def test_pipeline_only_subset_still_returns_deps():
    reg = Registry()
    for cls in (A, B, C, D):
        reg.register(cls())
    result = Pipeline(reg).run(_empty_snapshot(), only=["B"])
    assert set(result.observations) == {"A", "B"}


# --- multi-stage (M2): cross-kind deps resolve + results bucket by kind -----

class Obs(Observation):
    id = "obs"; category = "fixture"
    def compute(self, snapshot, deps):
        return ObservationResult(self.id, self.category, value=10)


class Met(Metric):                          # metric depends on an observation
    id = "met"; category = "fixture"; requires = ("obs",)
    def compute(self, snapshot, deps):
        return MetricResult(self.id, self.category, value=deps["obs"].value * 2)


class Find(Finding):                        # finding depends on a metric
    id = "find"; category = "fixture"; requires = ("met",)
    def compute(self, snapshot, deps):
        return FindingResult(id=self.id, category=self.category, name="F",
                             severity="high", evidence=[{"v": deps["met"].value}],
                             explanation="x")


def test_pipeline_resolves_cross_kind_deps_and_buckets_by_kind():
    reg = Registry()
    # Register out of dependency order to prove the resolver sorts across kinds.
    for p in (Find(), Met(), Obs()):
        reg.register(p)
    result = Pipeline(reg).run(_empty_snapshot())

    # Cross-stage dependency values threaded through the single shared cache.
    assert result.observations["obs"].value == 10
    assert result.metrics["met"].value == 20          # 10 * 2
    assert result.findings["find"].evidence == [{"v": 20}]

    # Each result landed in the bucket for its plugin's kind.
    assert set(result.observations) == {"obs"}
    assert set(result.metrics) == {"met"}
    assert set(result.findings) == {"find"}
    assert result.recommendations == {}

    # Metadata lists the ids per stage, in dependency order.
    assert result.metadata["metric_ids"] == ["met"]
    assert result.metadata["finding_ids"] == ["find"]


def test_cross_kind_shared_dep_computed_once():
    # A metric and a finding both depend on the same observation -> one compute.
    class Met2(Metric):
        id = "met2"; category = "fixture"; requires = ("obs",)
        def compute(self, snapshot, deps):
            return MetricResult(self.id, self.category, value=deps["obs"].value)

    cache = ResultCache(_empty_snapshot())
    for plugin in resolve_order([Find(), Met(), Met2(), Obs()]):
        deps = {r: cache.results()[r] for r in plugin.requires}
        cache.get_or_compute(plugin, deps)
    assert cache.compute_counts["obs"] == 1
