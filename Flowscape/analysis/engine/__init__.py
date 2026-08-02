"""Stage-generic execution engine: registry, dependency resolver, cache, pipeline."""

from .registry import Registry, DuplicatePluginError
from .dependency_graph import (resolve_order, DependencyError,
                               MissingDependencyError, CycleError)
from .cache import ResultCache
from .pipeline import Pipeline
