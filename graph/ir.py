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
from dataclasses import dataclass


@dataclass(frozen=True)
class Value:
    """A terminal input: one of the cell's own arguments."""

    index: int
    name: str

    def __str__(self):
        return self.name


@dataclass(frozen=True)
class Edge:
    """An input that is itself a cell, reached by calling `target` on the
    same object.

    Which cell is only known once `args` is evaluated against the earlier
    inputs, and only if `guard` (the condition under which the original call
    site is reached) holds. Both are pure functions of (self, node, ivs).
    """

    index: int
    target: str
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
