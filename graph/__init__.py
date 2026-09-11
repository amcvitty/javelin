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

A cell can also be given a value directly, which shadows its body and marks
everything downstream of it dirty:

    sheet.fib.set_value(2.0, args=(0,))

Inside a `diddle()` scope that change is temporary, and undoing it costs no
recomputation:

    with diddle((md.spot, 110.0), (call.strike, 95.0)):
        note.pv()      # sees the overrides
    note.pv()          # pre-diddle value, straight from the restored cache
"""

from .ir import Call, CallEdge, CompiledNode, Edge, Input, Local, MapEdge, Value
from .node import BoundNode, Marker, Node, Stored, node, stored_nodes
from .runtime import DEFAULT, Graph, make_key

__all__ = [
    "DEFAULT",
    "BoundNode",
    "Call",
    "CallEdge",
    "CompiledNode",
    "Edge",
    "Graph",
    "Input",
    "Local",
    "MapEdge",
    "Marker",
    "Node",
    "Stored",
    "Value",
    "all_nodes",
    "clear",
    "code",
    "deps",
    "diddle",
    "dirty",
    "inputs",
    "make_key",
    "node",
    "stored_nodes",
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


def dirty():
    """Every cell in the default graph whose memoised value is stale."""
    return DEFAULT.dirty()


def diddle(*entries):
    """Set values temporarily, restoring the default graph exactly on exit.

    Each entry is a bound node followed by the arguments set_value takes:
    diddle((md.spot, 110.0), (sheet.fib, 5.0, (3,))).
    """
    return DEFAULT.diddle(*entries)


def clear():
    """Forget every cell in the default graph."""
    DEFAULT.clear()
