"""Describing a cell: everything the engine knows about it, in one place.

A `Cell` is a view over a key and a graph, built on demand and never stored:
the object and node the key names, the value and the state that qualifies it,
one `Slot` per `ivs` slot, and the cells known to read it. Reading all of that
runs no body -- the compiler worked it out when the class was created, and the
graph has been holding it ever since.

A `Slot` says what fills its slot and what filling it would cost. The cost that
matters is whether the slot is **statically resolvable**: whether the cells it
names are known without evaluating anything. Reading nothing is the wrong test.
A recursive call site reads the node's own parameter, but a terminal's value
comes free with the key, so the call site still resolves for nothing; only
reaching an *edge* costs an evaluation.

That cost is what decides when a slot is filled in. A statically resolvable
slot is resolved as the slots are read, since doing so is free; any other waits
for `expand_slot`, reporting `UNRESOLVED` until then -- a different answer from
a guarded-off call site that resolves to no cells at all.

The view keeps none of this. Every slot it reports it reads back out of the
graph, which is where expansion records what it worked out, so two views of one
key answer alike and a slot one of them expanded is resolved in the other.
"""

from dataclasses import dataclass

from .ir import Edge, Input, InputKind, guarded
from .runtime import DEFAULT, UNRESOLVED, Graph, _Unresolved


@dataclass(frozen=True)
class Slot:
    """One `ivs` slot, described.

    `source` is the slot as written -- a parameter's name, a hoisted local's
    assignment, an edge's call site -- with the guard kept apart in
    `guard_source` so either can be shown on its own.

    `blocked_by` is the edges in `reads`: the slots that have to be evaluated
    before this one's cells can be named. Empty means statically resolvable.

    `cells` is what the graph has recorded for this slot: the cells it names,
    or `UNRESOLVED` if nothing has looked yet.
    """

    index: int
    kind: InputKind
    source: str
    guard_source: str | None
    reads: frozenset
    blocked_by: frozenset
    cells: tuple | _Unresolved = UNRESOLVED

    @property
    def statically_resolvable(self):
        """Whether this slot's cells are known without evaluating anything."""
        return not self.blocked_by

    def __str__(self):
        return guarded(self.source, self.guard_source)


def _slot(inp: Input, blocked_by: frozenset, cells):
    """Describe one input, given its blockers and what the graph has recorded.

    The one thing asked of the input is whether it is an edge -- not which
    kind of edge, which is the input's own business. Only an edge has a call
    site kept apart from its text, and only a call site can be guarded.
    """
    edge = isinstance(inp, Edge)
    return Slot(
        index=inp.index,
        kind=inp.kind,
        source=inp.source if edge else str(inp),
        guard_source=inp.guard_source if edge else None,
        reads=inp.reads,
        blocked_by=blocked_by,
        cells=cells,
    )


class Cell:
    """A view of one cell of a graph, read-only as to what the graph records.

    Built from a key on demand and thrown away again: the graph holds keys,
    not cells. Equality and hashing are the key's, so a cell can be used
    wherever its key can -- a set of cells equals the set of their keys.

    A view accumulates nothing: it reads through to the graph every time, so
    two views of one key answer alike, and a slot either of them expands is
    resolved for both and for every view built afterwards.
    """

    def __init__(self, key, graph: Graph = DEFAULT):
        obj, node, *args = key
        if hasattr(node, "__self__"):
            # A key holds the node itself. A bound node would compare equal to
            # nothing in the graph, and the cell would read as uncomputed
            # forever rather than saying anything was wrong.
            raise TypeError(
                "a key holds a node, not a bound one -- "
                "calc.fib.key(5) builds the key for calc.fib(5)"
            )
        if not hasattr(node, "compiled"):
            raise KeyError(node)
        self.key = tuple(key)
        self.graph = graph
        self.obj = obj
        self.node = node
        self.args = tuple(args)

    @property
    def method_name(self):
        """The name of the node, as written in the class."""
        return self.node.__name__

    @property
    def cls(self):
        """The object's own class, which a node may have been inherited into."""
        return type(self.obj)

    @property
    def value(self):
        """The cell's value and the state that qualifies it. Computes nothing."""
        return self.graph.value(self.key)

    @property
    def slots(self):
        """One `Slot` per `ivs` slot, in slot order, whatever fills it.

        Read off the graph's record of this cell, so a slot anything has
        expanded comes back resolved. Statically resolvable slots are resolved
        as the record is read, which runs no body; the rest wait to be asked.
        """
        compiled = self.node.compiled
        recorded = self.graph.slots(self.key)
        return tuple(
            _slot(inp, compiled.blocked_by[inp.index], self._cells(recorded[inp.index]))
            for inp in compiled.inputs
        )

    @property
    def expanded(self):
        """Whether every slot has been resolved -- read straight off them.

        What `expand` leaves behind, in other words, however it was reached:
        a cell every slot of which was expanded on its own is expanded. The
        invariant this stands next to: a cell carrying a value the graph hands
        out as clean is expanded. A dirty one need not be, since dirtying it
        forgets the slots a changed value could have moved.
        """
        return all(slot.cells is not UNRESOLVED for slot in self.slots)

    def expand_slot(self, index):
        """The cells one of this cell's inputs names, as cells.

        Evaluates only what that input reads -- the cost its `blocked_by`
        warned about, and no more. Statically resolvable slots are filled in
        already, and expanding one twice costs nothing the second time,
        whichever view did it first.
        """
        return self._ordered(self.graph.expand_slot(self.key, index))

    def _cells(self, recorded):
        """A recorded slot's keys as views, leaving `UNRESOLVED` as it is."""
        if recorded is UNRESOLVED:
            return recorded
        return self._ordered(recorded)

    def _ordered(self, keys):
        """The same cells, seen through the same graph, in the order given.

        A map edge names one cell per element, so the order and the duplicates
        are part of the answer -- which is why this is not `_view`.
        """
        return tuple(Cell(key, self.graph) for key in keys)

    @property
    def outputs(self):
        """The cells known to read this one.

        Only those already expanded: until something asks what a cell depends
        on, the graph has not been told that it reads this one.
        """
        return self._view(self.graph.outputs(self.key))

    def expand(self):
        """The cells this one depends on, found without running its body."""
        return self._view(self.graph.expand(self.key))

    def evaluate(self):
        """The cell's value, running whatever bodies that takes."""
        return self.graph.evaluate(self.key)

    def _view(self, keys):
        """The same cells, seen through the same graph."""
        return frozenset(Cell(key, self.graph) for key in keys)

    def __eq__(self, other):
        if isinstance(other, Cell):
            return self.key == other.key
        if isinstance(other, tuple):
            return self.key == other
        return NotImplemented

    def __hash__(self):
        return hash(self.key)

    def __str__(self):
        args = ", ".join(repr(arg) for arg in self.args)
        return f"{self.cls.__name__}.{self.method_name}({args})"

    def __repr__(self):
        return f"<cell {self}: {self.value}>"
