"""
Per-run result cache.

A ResultCache is created for a single Snapshot and memoizes each plugin's result
so a shared dependency is computed exactly ONCE, no matter how many plugins
depend on it. Because a Snapshot is immutable, this is safe: the same plugin
over the same snapshot always yields the same result.

`compute_counts` records how many times each plugin actually ran -- used by
tests to prove the single-compute guarantee, and available for introspection.
"""


class ResultCache:
    def __init__(self, snapshot):
        self.snapshot = snapshot
        self._results = {}
        self.compute_counts = {}

    def get_or_compute(self, plugin, deps):
        """Return plugin's result, computing (and caching) it on first request."""
        if plugin.id in self._results:
            return self._results[plugin.id]
        result = plugin.compute(self.snapshot, deps)
        self._results[plugin.id] = result
        self.compute_counts[plugin.id] = self.compute_counts.get(plugin.id, 0) + 1
        return result

    def results(self):
        """Shallow copy of everything computed so far, {id: result}."""
        return dict(self._results)
