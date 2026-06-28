from dataclasses import dataclass, field


@dataclass
class Building:
    """A placed building INSTANCE. Deliberately lightweight: it references a
    shared BuildingType (by name, see destinations.BUILDING_TYPES) instead of
    duplicating category/size/capacity/operating-hours onto every instance.

    Reusable simulation characteristics live on the BuildingType; only the
    per-placement facts live here (which type, where, which road nodes it is
    attached to, and the RNG seed). 'data' is reserved for editor metadata /
    experimental fields, never for core simulation properties.
    """
    id: int
    # Key into destinations.BUILDING_TYPES (e.g. "Small House", "Large Business").
    building_type: str = "Small House"
    x: float = 0.0
    y: float = 0.0
    # IDs of road-graph Nodes this building attaches to (entrances). Each is a
    # normal Node, no special type/marker on the node.
    connection_node_ids: list = field(default_factory=list)
    # Stable RNG seed for this placement. Every randomized demand property
    # (vehicle count, activity distribution, departure times) is DERIVED from
    # this seed in destinations.py, so behavior is reproducible and only
    # changes when the building is reseeded. None -> callers fall back to `id`.
    seed: int = None
    # Editor metadata / experimental fields only (NOT simulation properties).
    data: dict = field(default_factory=dict)

    @property
    def pos(self):
        return (self.x, self.y)
