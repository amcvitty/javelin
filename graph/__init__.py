"""An Excel-style calculation engine.

A method decorated with @node is a cell. Its body is rewritten when the class
is created into a pure function of a list of input values, plus a note saying
how to produce each input:

    class Sheet:
        @node
        def fib(self, n):
            return n if n < 2 else self.fib(n - 1) + self.fib(n - 2)

    def fib(self, node, ivs):
        return ivs[0] if ivs[0] < 2 else ivs[1] + ivs[2]

    ivs[0] = n
    ivs[1] = self.fib(n - 1) if not n < 2
    ivs[2] = self.fib(n - 2) if not n < 2

Because each input carries the guard under which it is reached, the graph for
a given cell can be built without running any body -- `deps(sheet.fib, 6)` is
{fib(5), fib(4)} -- and evaluation follows the graph, so fib(1) runs first and
every cell runs at most once.
"""

from .ir import CompiledNode, Edge, Value
from .node import Node, node
from .runtime import DEFAULT, Graph, make_key

__all__ = [
    "DEFAULT",
    "CompiledNode",
    "Edge",
    "Graph",
    "Node",
    "Value",
    "all_nodes",
    "clear",
    "code",
    "deps",
    "inputs",
    "make_key",
    "node",
]


def _compiled_of(method):
    """Accept a node from the class (Calc.fib) or bound to an instance (calc.fib)."""
    try:
        return getattr(method, "__func__", method).compiled
    except AttributeError:
        raise KeyError(method) from None


def inputs(method):
    """The inputs of a node, in evaluation order."""
    return _compiled_of(method).inputs


def code(method):
    """The rewritten source of a node: a pure function of (self, node, ivs)."""
    return _compiled_of(method).code


def deps(method, *args, **kwargs):
    """The direct dependencies of the cell obj.method(*args), as node keys."""
    return DEFAULT.deps(method, *args, **kwargs)


def all_nodes():
    """Every known cell in the default graph, as (object, method, *args) keys."""
    return DEFAULT.all_nodes()


def clear():
    """Forget every cell in the default graph."""
    DEFAULT.clear()
