"""Shared fixtures-by-hand for the graph tests.

The classes are built by factory functions rather than defined once at module
level, so each test gets its own freshly compiled nodes and cannot be affected
by cells another test left behind.
"""

from graph import node


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
