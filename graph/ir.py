"""Intermediate representation is the compiled form of a node: what the
compiler emits and the runtime runs.

A node is compiled once, when its class is created, into a `CompiledNode`: the
rewritten body as a callable, plus an ordered list of inputs describing how to
produce each of its input values.

Those inputs are the whole point. A cell's dependencies are found by walking
them and calling only `Edge.args` and `Edge.guard` -- never the body -- so the
graph can be built without evaluating anything.
"""

import inspect
from collections.abc import Callable
from dataclasses import dataclass


@dataclass(frozen=True)
class Value:
    """A terminal input: one of the cell's own arguments."""

    index: int
    name: str

    def __str__(self):
        return self.name


@dataclass(frozen=True)
class Local:
    """An intermediate hoisted out of the body and above it.

    A plain `name = <expr>` assignment whose right-hand side, once rewritten,
    reads only the node's parameters, earlier inputs and names from outside the
    method. It fills an `ivs` slot exactly like an argument expression does, so
    a later edge's arguments or guard may refer to it. `expr` is a pure function
    of `(self, node, ivs)`; the input adds no dependency of its own.
    """

    index: int
    name: str
    expr: Callable[..., object]  # (self, node, ivs) -> the intermediate's value
    source: str

    def __str__(self):
        return f"{self.name} = {self.source}"


@dataclass(frozen=True)
class Edge:
    """An input reached by calling `target` on the object `receiver` returns.

    Which cell is only known once `receiver` and `args` are evaluated against
    the earlier inputs, and only if `guard` (the condition under which the
    original call site is reached) holds. All three are pure functions of
    (self, node, ivs); `receiver` returns `self` for an ordinary self.<node>()
    call, and another object for a call reaching across the graph.
    """

    index: int
    target: str
    receiver: object
    args: object
    guard: object
    source: str

    def __str__(self):
        return self.source


@dataclass(frozen=True)
class CompiledNode:
    """One node, compiled."""

    impl: object
    inputs: tuple
    signature: inspect.Signature  # without self
    needed: frozenset  # input indices whose values some later input reads
    code: str
