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
slot is resolved as the view's slots are built, since doing so is free; any
other waits for `resolve`, reporting `UNRESOLVED` until then -- a different
answer from a guarded-off call site that resolves to no cells at all.
"""

from dataclasses import dataclass, replace

from .ir import Edge, Input, InputKind, guarded
from .runtime import DEFAULT, Graph


class _Unresolved:
    """The answer to "which cells?" before anyone has gone and looked.

    A singleton rather than None, which a caller would read as "no cells".
    """

    __slots__ = ()

    def __repr__(self):
        return "not yet resolved"


#: What a slot's cells are until something resolves them.
UNRESOLVED = _Unresolved()


@dataclass(frozen=True)
class Slot:
    """One `ivs` slot, described.

    `source` is the slot as written -- a parameter's name, a hoisted local's
    assignment, an edge's call site -- with the guard kept apart in
    `guard_source` so either can be shown on its own.

    `blocked_by` is the edges in `reads`: the slots that have to be evaluated
    before this one's cells can be named. Empty means statically resolvable.
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


def _slot(inp: Input, edges: frozenset):
    """Describe one input, given which of the node's slots are edges.

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
        blocked_by=inp.reads & edges,
    )


class Cell:
    """A read-only view of one cell of a graph.

    Built from a key on demand and thrown away again: the graph holds keys,
    not cells. Equality and hashing are the key's, so a cell can be used
    wherever its key can -- a set of cells equals the set of their keys.
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
        self._slots: list[Slot] | None = None

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

        Built on first use and kept, so that a slot resolved through this view
        stays resolved in it. Statically resolvable slots are resolved as the
        slots are built, which runs no body; the rest wait to be asked for.
        """
        if self._slots is None:
            inputs = self.node.compiled.inputs
            edges = frozenset(inp.index for inp in inputs if isinstance(inp, Edge))
            self._slots = [_slot(inp, edges) for inp in inputs]
            for slot in list(self._slots):
                if slot.statically_resolvable:
                    self._resolve(slot.index)
        return tuple(self._slots)

    def resolve(self, index):
        """The cells one of this cell's inputs names, as cells.

        Evaluates only what that input reads -- the cost its `blocked_by`
        warned about, and no more. Statically resolvable slots are filled in
        already, and resolving one twice costs nothing the second time.
        """
        cells = self.slots[index].cells
        if isinstance(cells, _Unresolved):
            cells = self._resolve(index)
        return cells

    def _resolve(self, index):
        """Fill one slot in, in place of the record built without it."""
        assert self._slots is not None  # only ever called once `slots` is built
        cells = tuple(self._cell(key) for key in self.graph.resolve(self.key, index))
        self._slots[index] = replace(self._slots[index], cells=cells)
        return cells

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
        return frozenset(self._cell(key) for key in keys)

    def _cell(self, key):
        """Another cell of the same graph."""
        return Cell(key, self.graph)

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
