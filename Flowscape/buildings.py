from dataclasses import dataclass, field


@dataclass
class Building:
    id: int
    x: float = 0.0
    y: float = 0.0
    type: str = "building"
    # IDs of road-graph Nodes this building connects to (entrances). Each
    # of these is a normal Node -- no special type/marker on the node.
    connection_node_ids: list = field(default_factory=list)
    data: dict = field(default_factory=dict)

    @property
    def pos(self):
        return (self.x, self.y)
