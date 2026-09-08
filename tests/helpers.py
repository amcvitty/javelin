"""Shared fixtures-by-hand for the graph tests.

The classes are built by factory functions rather than defined once at module
level, so each test gets its own freshly compiled nodes and cannot be affected
by cells another test left behind.
"""

import datetime

import ns
from graph import node

#: Bodies that ran, for the namespace classes below. Cleared by each test that
#: cares -- these classes are module level so that the store can name them.
ran = []


class Params(ns.McObject):
    """A well-known object other objects look up by name."""

    @node
    def factor(self):
        ran.append("factor")
        return 2.0


class Market(ns.McObject):
    """An object with persisted state, reaching Params through the namespace."""

    @node(node.Stored)
    def spot(self):
        ran.append("spot")
        return 100.0

    @node(node.Stored)
    def asof(self):
        ran.append("asof")
        return datetime.date(2026, 1, 1)

    @node
    def scaled(self):
        ran.append("scaled")
        return self.spot() * self.ns["/Params"].factor()


class Unstorable(ns.McObject):
    """A stored node whose value JSON has no form for."""

    @node(node.Stored)
    def thing(self):
        return object()


def make_market_classes():
    """The namespace classes, defined at module level so the store can name
    them: a stored row says which class to rebuild, and a class defined inside
    a test function cannot be found again by that name."""
    ran.clear()
    return Params, Market


def names(keys):
    """Render node keys as "a" / "fib(5)" strings, for readable assertions."""
    return {
        f"{fn.__name__}({', '.join(map(repr, args))})" if args else fn.__name__
        for obj, fn, *args in keys
    }


def make_calc():
    """The shape from example.py: two leaves, a non-node, and an aggregate."""

    class Calc:
        @node
        def a(self):
            return 1

        @node
        def b(self):
            return 2

        def c(self):
            return 4

        @node
        def sum(self):
            return self.a() + self.b() + self.c() + 1

    return Calc


def make_pricer(evaluated=None):
    """A contract for difference: three leaves under a two-deep chain.

    `quantity` is a dependency of pv but not of payoff, so setting spot must
    leave it alone -- which catches an implementation that dirties everything
    the recomputed cell reads.
    """

    def record(name):
        if evaluated is not None:
            evaluated.append(name)

    class Pricer:
        @node
        def spot(self):
            record("spot")
            return 100.0

        @node
        def strike(self):
            record("strike")
            return 90.0

        @node
        def quantity(self):
            record("quantity")
            return 2.0

        @node
        def payoff(self):
            record("payoff")
            return self.spot() - self.strike()

        @node
        def pv(self):
            record("pv")
            return self.payoff() * self.quantity()

    return Pricer


def make_linked(evaluated=None):
    """Two objects, one reaching the other's nodes through a node of its own.

    Returns (Market, Option, market, option). The market is a closure variable
    rather than a member, since a node may not read member variables.
    """

    def record(name):
        if evaluated is not None:
            evaluated.append(name)

    class Market:
        @node
        def spot(self):
            record("spot")
            return 100.0

        @node
        def ticker(self):
            record("ticker")
            return "abc"

    market = Market()

    class Option:
        def helper(self):
            """Not a node, so calls to it stay in the body."""
            return 1.0

        @node
        def market(self):
            record("market")
            return market

        @node
        def strike(self):
            record("strike")
            return self.market().spot()

        @node
        def doubled(self):
            return self.market().spot() * 2

        @node
        def shout(self):
            return self.market().ticker().upper()

        @node
        def maybe(self, take):
            return self.market().spot() if take else 0.0

        @node
        def with_helper(self):
            return self.market().spot() + self.helper()

        @node
        def clamped(self):
            return max(self.market().spot(), 0.0)

    return Market, Option, market, Option()


def make_chooser():
    """A node whose dependency is named by another node's value.

    `pick` depends on item(1) or item(3) according to `which`, so changing
    `which` changes the shape of the graph, not just a number in it.
    """

    class Chooser:
        @node
        def which(self):
            return 1

        @node
        def item(self, n):
            return n * 10

        @node
        def pick(self):
            return self.item(self.which())

    return Chooser


def make_fib(evaluated=None):
    """Recursive fibonacci, optionally recording the order bodies run in."""

    class Fib:
        @node
        def fib(self, n):
            if evaluated is not None:
                evaluated.append(n)
            return n if n < 2 else self.fib(n - 1) + self.fib(n - 2)

    return Fib
