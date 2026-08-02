"""Immutable snapshots: models, sources, and the normalization builder."""

from .models import (RoadSnapshot, NodeSnapshot, BuildingSnapshot,
                     VehicleSnapshot, SnapshotMeta, Snapshot)
from .sources import StaticSource, RuntimeSource
from .builder import build_snapshot
