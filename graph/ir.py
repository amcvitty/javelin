"""Intermediate representation is the compiled form of a node: what the
compiler emits and the runtime runs.

A node is compiled once, when its class is created, into a `CompiledNode`: the
rewritten body as a callable, plus an ordered list of inputs describing how to
produce each of its input values.

Those inputs are the whole point. A cell's dependencies are found by walking
them and asking each edge to `resolve` -- never running the body -- so a cell's
own body never runs to find out what it depends on.

An edge resolves to a list of calls, not one: `CallEdge` names at most one cell,
`MapEdge` one per element of a collection. The runtime turns calls into cell
keys and does not care how many an edge produced, so a further kind of edge is a
new `resolve`, not a new branch everywhere.
"""

import enum
import inspect
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from typing import ClassVar, NamedTuple


class InputKind(enum.Enum):
    """Which kind of input fills a slot, in the words a reader wants.

    Each input class names its own kind, so a further kind of edge is one more
    member here rather than a branch in everything that describes a slot.
    """

    TERMINAL = "terminal"
    LOCAL = "hoisted local"
    CALL_EDGE = "call edge"
    MAP_EDGE = "map edge"

    def __str__(self):
        return self.value


def guarded(source, guard_source):
    """A call site and the guard it is reached under, written as one line."""
    if guard_source is None:
        return source
    return f"{source} if {guard_source}"


@dataclass(frozen=True)
class Input:
    """What fills one `ivs` slot, and what filling it costs.

    `reads` is that cost: the slots resolving this one input reads, and none
    of the rest. It is closed through the hoisted locals among them, since
    reading a local's slot means evaluating it, which means reading whatever
    *it* reads. Edges are not followed -- an edge in a read set is resolved
    for its cell, not opened up.

    Usually far smaller than `CompiledNode.needed`, which is every slot
    expansion evaluates for the node as a whole. Keeping the sets apart is
    what lets one input be resolved on its own.
    """

    kind: ClassVar[InputKind]

    index: int
    reads: frozenset


@dataclass(frozen=True)
class Value(Input):
    """A terminal input: one of the cell's own arguments.

    Reads nothing: an argument's value comes free with the key.
    """

    kind = InputKind.TERMINAL

    name: str

    def __str__(self):
        return self.name


@dataclass(frozen=True)
class Local(Input):
    """An intermediate hoisted out of the body and above it.

    A plain `name = <expr>` assignment whose right-hand side, once rewritten,
    reads only the node's parameters, earlier inputs and names from outside the
    method. It fills an `ivs` slot exactly like an argument expression does, so
    a later edge's arguments or guard may refer to it. `expr` is a pure function
    of `(self, node, ivs)`; the input adds no dependency of its own.
    """

    kind = InputKind.LOCAL

    name: str
    expr: Callable[..., object]  # (self, node, ivs) -> the intermediate's value
    source: str

    def __str__(self):
        return f"{self.name} = {self.source}"


class Call(NamedTuple):
    """One resolved call site: which object, which method, which arguments.

    What an edge produces. Whether it names a cell is the runtime's business --
    `target` may turn out to be an ordinary method.
    """

    receiver: object
    target: str
    positional: tuple
    keywords: dict


@dataclass(frozen=True)
class Edge(Input):
    """An input reached by calling `target` on objects the graph produced.

    Which cells is only known once the edge is resolved against the earlier
    inputs, and only if `guard` -- the condition under which the original call
    site is reached -- holds. Subclasses say how many cells one call site names.

    The guard is carried twice: `guard` to run, `guard_source` to read. Keeping
    the readable form off `source` is what lets a guard be shown in its own
    right rather than parsed back out of the call site's text.

    What such an edge `reads` is whatever names its cell: its receiver, its
    arguments, the collection it maps over, and its guard.
    """

    target: str
    guard: Callable[..., bool] | None  # (self, node, ivs) -> bool
    source: str
    guard_source: str | None  # the guard as written, or None if unconditional

    #: Whether this edge's ivs slot holds a *list* of its cells' values rather
    #: than a single one. The runtime needs to know before it has resolved
    #: anything, because an empty result means "no cells" either way.
    collects = False

    def resolve(self, obj, key, ivs) -> list[Call]:
        """The calls this edge names, given the input values so far."""
        raise NotImplementedError

    def blocked(self, obj, key, ivs):
        """Whether the guard says this call site is not reached at all."""
        return self.guard is not None and not self.guard(obj, key, ivs)

    def __str__(self):
        return guarded(self.source, self.guard_source)


@dataclass(frozen=True)
class CallEdge(Edge):
    """One call site, one cell: `self.spot()`, `self.Market().spot()`.

    `receiver` returns `self` for an ordinary self.<node>() call, and another
    object for a call reaching across the graph. Both it and `args` are pure
    functions of (self, node, ivs).
    """

    kind = InputKind.CALL_EDGE

    receiver: Callable[..., object]
    args: Callable[..., tuple]

    def resolve(self, obj, key, ivs):
        if self.blocked(obj, key, ivs):
            return []
        positional, keywords = self.args(obj, key, ivs)
        return [Call(self.receiver(obj, key, ivs), self.target, positional, keywords)]


@dataclass(frozen=True)
class MapEdge(Edge):
    """One call site, one cell per element: `[p.pv() for p in self.Positions()]`.

    `over` produces the collection, as a pure function of (self, node, ivs);
    `receiver` and `args` take the element as a fourth argument, so the loop
    variable stays a plain name in the compiled lambdas rather than being
    rewritten into an ivs slot.

    The ivs slot holds the cells' values as a list, in the collection's own
    order and with duplicates kept -- what the comprehension would have built.
    """

    kind = InputKind.MAP_EDGE

    over: Callable[..., Iterable]
    receiver: Callable[..., object]
    args: Callable[..., tuple]
    var: str  # the loop variable's name, for error messages

    collects = True

    def resolve(self, obj, key, ivs):
        if self.blocked(obj, key, ivs):
            return []
        # Materialised so that expansion and evaluation see the same elements in
        # the same order, however the collection was produced.
        elements = list(self.over(obj, key, ivs))
        calls = []
        for element in elements:
            positional, keywords = self.args(obj, key, ivs, element)
            calls.append(
                Call(
                    self.receiver(obj, key, ivs, element),
                    self.target,
                    positional,
                    keywords,
                )
            )
        return calls


@dataclass(frozen=True)
class CompiledNode:
    """One node, compiled."""

    impl: object
    inputs: tuple[Input, ...]  # one per ivs slot, in slot order
    signature: inspect.Signature  # without self
    needed: frozenset  # union of the edges' read sets: what expansion evaluates
    code: str
