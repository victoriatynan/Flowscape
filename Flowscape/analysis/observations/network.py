"""
Network observations: factual counts and lengths over the static topology.

None of these make an engineering judgement. They are the simple, deterministic
facts that prove the pipeline and that later metrics build on (e.g. total road
length feeds network-density metrics; connected components will feed a future
"network is disconnected" finding).
"""

from .base import Observation, ObservationResult


class RoadCount(Observation):
    id = "road_count"
    category = "network"

    def compute(self, snapshot, deps):
        return ObservationResult(self.id, self.category,
                                 value=len(snapshot.roads), units="count")


class IntersectionCount(Observation):
    id = "intersection_count"
    category = "network"

    def compute(self, snapshot, deps):
        n = sum(1 for node in snapshot.nodes if node.is_intersection)
        return ObservationResult(self.id, self.category, value=n, units="count")


class TotalRoadLength(Observation):
    id = "total_road_length"
    category = "network"

    def compute(self, snapshot, deps):
        total = sum(road.length_ft for road in snapshot.roads)
        return ObservationResult(self.id, self.category, value=total, units="ft")


class BuildingCount(Observation):
    id = "building_count"
    category = "network"

    def compute(self, snapshot, deps):
        by_type = {}
        for b in snapshot.buildings:
            by_type[b.building_type] = by_type.get(b.building_type, 0) + 1
        return ObservationResult(self.id, self.category,
                                 value=len(snapshot.buildings), units="count",
                                 detail={"by_type": by_type})


class BuildingMix(Observation):
    """Building population as an engineering fact: counts by type and by land-use
    category, plus capacity-derived population (residential) and jobs
    (everything else). Unknown building types (no catalogue entry, hence no
    category) are excluded from the mix and the roll-ups but still counted in the
    total, mirroring the legacy /api/analysis endpoint this observation replaces.
    Capacity + the residential flag ride on the snapshot, resolved once at the
    builder boundary, so the observation reaches into no catalogue itself."""
    id = "building_mix"
    category = "network"

    def compute(self, snapshot, deps):
        by_type = {}
        by_category = {}
        population = 0
        jobs = 0
        for b in snapshot.buildings:
            by_type[b.building_type] = by_type.get(b.building_type, 0) + 1
            if b.category is None:        # unknown type -> not part of the mix
                continue
            by_category[b.category] = by_category.get(b.category, 0) + 1
            cap = b.capacity or 0
            if b.is_residential:
                population += cap
            else:
                jobs += cap
        return ObservationResult(
            self.id, self.category,
            value=len(snapshot.buildings), units="count",
            detail={"by_type": by_type, "by_category": by_category,
                    "population": population, "jobs": jobs})


class ConnectedComponents(Observation):
    """Number of disconnected road sub-networks -- connected components of the
    graph whose nodes are road endpoints and whose edges are roads. Isolated
    nodes with no road are not counted; an empty network has 0 components.

    `detail["main_component"]` lists the node ids of the largest component under
    *all-nodes* semantics (every node participates; isolated nodes are their own
    size-1 component; the largest wins, ties broken by first-seen node order).
    That is the membership the legacy /api/analysis connectivity warnings need;
    it is exposed as a fact so that endpoint can consume it instead of running
    its own union-find. The `value` above keeps its road-touched semantics."""
    id = "connected_components"
    category = "network"

    def compute(self, snapshot, deps):
        parent = {}

        def find(x):
            parent.setdefault(x, x)
            root = x
            while parent[root] != root:
                root = parent[root]
            while parent[x] != root:      # path compression
                parent[x], x = root, parent[x]
            return root

        for road in snapshot.roads:
            ra, rb = find(road.start_node_id), find(road.end_node_id)
            if ra != rb:
                parent[ra] = rb

        roots = {find(n) for n in parent}

        # Separate all-nodes pass for the largest-component membership (endpoint
        # semantics). Kept apart from the road-touched `value` so that count is
        # unchanged. Iteration order follows snapshot.nodes so a size tie breaks
        # exactly as the legacy endpoint's `max(..., key=len)` did.
        main_component = self._largest_component(snapshot)

        return ObservationResult(self.id, self.category,
                                 value=len(roots), units="count",
                                 detail={"main_component": main_component})

    @staticmethod
    def _largest_component(snapshot):
        parent = {n.id: n.id for n in snapshot.nodes}

        def find(x):
            while parent[x] != x:
                parent[x] = parent[parent[x]]
                x = parent[x]
            return x

        for road in snapshot.roads:
            if road.start_node_id in parent and road.end_node_id in parent:
                parent[find(road.start_node_id)] = find(road.end_node_id)

        groups = {}
        for n in snapshot.nodes:
            groups.setdefault(find(n.id), []).append(n.id)
        return max(groups.values(), key=len) if groups else []
