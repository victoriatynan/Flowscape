"""
Dependency resolution: turn a set of plugins with declared `requires` into a
valid execution order.

The resolver is stage-generic -- it only reads `.id` and `.requires`. It:
  * validates every declared dependency exists,
  * optionally restricts to a requested subset plus its transitive dependencies,
  * topologically sorts so each plugin runs after everything it requires,
  * detects and reports cycles.

Ordering is deterministic: within the constraints, plugins keep their given
(registration) order.
"""


class DependencyError(ValueError):
    """Base class for resolution failures."""


class MissingDependencyError(DependencyError):
    """A plugin requires an id that no plugin provides."""


class CycleError(DependencyError):
    """The dependency graph contains a cycle."""


def resolve_order(plugins, only=None):
    """Return `plugins` ordered so dependencies precede dependents.

    `plugins` -- iterable of plugin instances (each with `.id`, `.requires`).
    `only`    -- optional iterable of ids to compute; the result is those ids
                 plus their transitive dependencies. None means "all".
    """
    plugins = list(plugins)
    by_id = {p.id: p for p in plugins}

    # 1. Every declared dependency must exist.
    for p in plugins:
        for req in p.requires:
            if req not in by_id:
                raise MissingDependencyError(
                    f"{p.id!r} requires unknown plugin {req!r}")

    # 2. Determine the target set (requested + transitive deps).
    if only is None:
        targets = set(by_id)
    else:
        targets = set()
        stack = list(only)
        while stack:
            pid = stack.pop()
            if pid not in by_id:
                raise MissingDependencyError(f"requested unknown plugin {pid!r}")
            if pid in targets:
                continue
            targets.add(pid)
            stack.extend(by_id[pid].requires)

    # 3. Topological sort (DFS) over the target set, cycle-detecting. State:
    #    absent = unvisited, "open" = on the current path, "done" = emitted.
    order = []
    state = {}

    def visit(pid, path):
        s = state.get(pid)
        if s == "done":
            return
        if s == "open":
            cycle = " -> ".join(path + [pid])
            raise CycleError(f"dependency cycle: {cycle}")
        state[pid] = "open"
        for req in by_id[pid].requires:
            visit(req, path + [pid])
        state[pid] = "done"
        order.append(pid)

    # Iterate in registration order so the output is stable.
    for p in plugins:
        if p.id in targets:
            visit(p.id, [])

    return [by_id[pid] for pid in order]
