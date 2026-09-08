"""A namespace of well-named objects, on top of the graph.

Single objects are limited: real applications spread work across objects that
refer to each other by name. An McObject has a name and a namespace, and a node
may reach another object through either -- by looking it up, `self.ns['/x'].a()`,
or by getting one from another cell, `self.Market().spot()`. Either way the
dependency is a real graph edge, so setting a value on one object dirties the
cells on other objects that read it.

    class EquityMarket(McObject):
        @node(node.Stored)
        def StockPrice(self):
            return 25.0

    mkt = ns.lookup_or_new('/Equities/ABC', EquityMarket, StockPrice=20.0)
    mkt.store()          # persisted; a later lookup of the name finds it

Nodes marked `node.Stored` are the object's persisted state. `store()` evaluates
every one of them and writes it, so a saved object is whole; loading sets those
cells, so a reloaded object's bodies never run.
"""

from .mcobject import McObject
from .namespace import DEFAULT, Namespace
from .store import SqliteStore

__all__ = [
    "DEFAULT",
    "McObject",
    "Namespace",
    "SqliteStore",
    "all_objects",
    "clear",
    "lookup_or_new",
    "new",
]


def new(cls, **values):
    """A new object in the default namespace, with a generated name."""
    return DEFAULT.new(cls, **values)


def lookup_or_new(name, cls, **values):
    """The object called `name` in the default namespace, made if need be."""
    return DEFAULT.lookup_or_new(name, cls, **values)


def all_objects():
    """Every object the default namespace is holding."""
    return DEFAULT.all_objects()


def clear():
    """Forget every object in the default namespace."""
    DEFAULT.clear()
