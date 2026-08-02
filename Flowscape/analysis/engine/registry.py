"""
Stage-generic plugin registry.

A Registry holds plugin instances keyed by their unique `id`. It is deliberately
agnostic to plugin TYPE: it stores observations today and will store metrics,
findings and recommendations later with no change here. The only contract a
plugin must satisfy is a non-empty `.id` (and, for the resolver, a `.requires`).
"""


class DuplicatePluginError(ValueError):
    """Raised when two plugins register the same id."""


class Registry:
    def __init__(self, kind="plugin"):
        self.kind = kind
        self._by_id = {}

    def register(self, plugin):
        """Register a plugin instance. Returns it (usable as a decorator)."""
        pid = getattr(plugin, "id", "")
        if not pid:
            raise ValueError(f"{self.kind} has no id: {plugin!r}")
        if pid in self._by_id:
            raise DuplicatePluginError(
                f"duplicate {self.kind} id {pid!r}")
        self._by_id[pid] = plugin
        return plugin

    def get(self, pid):
        return self._by_id[pid]

    def all(self):
        """Plugins in registration order."""
        return list(self._by_id.values())

    def ids(self):
        return list(self._by_id.keys())

    def __contains__(self, pid):
        return pid in self._by_id

    def __len__(self):
        return len(self._by_id)
