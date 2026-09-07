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


def make_fib(evaluated=None):
    """Recursive fibonacci, optionally recording the order bodies run in."""

    class Fib:
        @node
        def fib(self, n):
            if evaluated is not None:
                evaluated.append(n)
            return n if n < 2 else self.fib(n - 1) + self.fib(n - 2)

    return Fib
