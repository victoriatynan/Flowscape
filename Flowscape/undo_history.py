"""
Undo/redo system (Command pattern).

Strict separation, mirroring the rest of the codebase:
  - This module knows NOTHING about pygame, the editor, or geometry. It only
    stores reversible edits and replays them. Callers supply read/write
    closures, so any future edit (delete, create, re-style) can become a
    Command without changing this file.

Drag semantics (the motivating use case):
  A mouse drag mutates objects directly every frame for smooth visual
  feedback, but must collapse into ONE undo step. That is handled by
  MoveTransaction: it snapshots each grabbed object's movable state up front,
  the editor moves the live objects during the drag (recording nothing), and
  on release the transaction emits a single MoveCommand (before -> after).
  No movement, or a cancelled drag, emits no command at all.
"""


class Command:
    """One reversible edit. Subclasses implement undo()/redo()."""

    def undo(self):
        raise NotImplementedError

    def redo(self):
        raise NotImplementedError


class MoveCommand(Command):
    """A single atomic move of one or more objects.

    Each entry is (write, before, after) where `write(state)` restores an
    object's movable state (e.g. a node's (x, y) or a road's curve_offset).
    Storing both endpoints lets the whole drag reverse/replay in one step,
    independent of however many intermediate frames the drag spanned.
    """

    def __init__(self, entries):
        self._entries = list(entries)

    @property
    def is_empty(self):
        """True when nothing actually moved (before == after everywhere), so
        the caller can drop it instead of polluting history."""
        return all(before == after for _, before, after in self._entries)

    def undo(self):
        for write, before, _after in self._entries:
            write(before)

    def redo(self):
        for write, _before, after in self._entries:
            write(after)


class MoveTransaction:
    """Accumulates the before-state of objects grabbed for a drag, then on
    commit builds a single MoveCommand from before/after.

    The objects are mutated directly by the editor during the drag (for
    visual feedback); this transaction records only the endpoints.
    """

    def __init__(self):
        # Each target: (read, write, before_state).
        self._targets = []

    def add(self, read, write):
        """Register an object by its movable-state accessors. `read()` returns
        its current state; `write(state)` sets it. The current value is
        captured now as the 'before' snapshot."""
        self._targets.append((read, write, read()))

    def cancel(self):
        """Revert every target to its captured before-state (drag aborted)."""
        for read, write, before in self._targets:
            write(before)

    def build_command(self):
        """Return a single MoveCommand (before -> after) for the whole drag,
        or None if nothing moved. Read the 'after' state lazily here, at
        commit time, so it reflects the final drag position."""
        entries = [(write, before, read())
                   for read, write, before in self._targets]
        command = MoveCommand(entries)
        return None if command.is_empty else command


class UndoStack:
    """Linear undo/redo history. push() clears the redo branch, matching the
    behavior of standard desktop editors."""

    def __init__(self):
        self._undo = []
        self._redo = []

    def push(self, command):
        """Add an already-applied command and start a fresh redo branch."""
        self._undo.append(command)
        self._redo.clear()

    def undo(self):
        if not self._undo:
            return False
        command = self._undo.pop()
        command.undo()
        self._redo.append(command)
        return True

    def redo(self):
        if not self._redo:
            return False
        command = self._redo.pop()
        command.redo()
        self._undo.append(command)
        return True

    def can_undo(self):
        return bool(self._undo)

    def can_redo(self):
        return bool(self._redo)

    def clear(self):
        """Drop all history (e.g. when a new map is loaded, so undo can never
        reach into objects that no longer exist)."""
        self._undo.clear()
        self._redo.clear()
