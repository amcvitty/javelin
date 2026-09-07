"""The @node decorator and the descriptor it puts on the class."""

import functools

from .compiler import compile_node
from .runtime import DEFAULT, make_key


class BoundNode:
    """A node bound to an object: callable like a method, and settable.

    This stands in for types.MethodType, which has nowhere to hang set_value.
    It keeps the names __self__ and __func__ so that anything duck-typing on a
    bound method -- graph.deps(calc.fib, 5), for one -- still works.
    """

    def __init__(self, node, obj):
        self.__func__ = node
        self.__self__ = obj
        self.__doc__ = node.__doc__

    def __call__(self, *args, **kwargs):
        return DEFAULT.evaluate(self.key(*args, **kwargs))

    def key(self, *args, **kwargs):
        """The graph key of the cell this node makes for these arguments."""
        return make_key(self.__self__, self.__func__, args, kwargs)

    def set_value(self, value, args=(), *, kwargs=None):
        """Give this cell a value directly, so its body never runs.

        `args` names which cell, for a node that takes parameters:
        sheet.fib.set_value(5.0, args=(3,)) sets fib(3) alone.
        """
        DEFAULT.set_value(self.key(*args, **(kwargs or {})), value)

    def clear_value(self, args=(), *, kwargs=None):
        """Drop a set value, so the cell computes again."""
        DEFAULT.clear_value(self.key(*args, **(kwargs or {})))

    def is_dirty(self, args=(), *, kwargs=None):
        """Whether this cell will recompute the next time it is asked for."""
        return DEFAULT.is_dirty(self.key(*args, **(kwargs or {})))

    def __getattr__(self, name):
        # __name__, __qualname__, compiled and the rest belong to the node.
        if name in ("__func__", "__self__"):
            # Not set yet; without this the getattr below would recurse.
            raise AttributeError(name)
        return getattr(self.__func__, name)

    def __eq__(self, other):
        if not isinstance(other, BoundNode):
            return NotImplemented
        return self.__func__ is other.__func__ and self.__self__ is other.__self__

    def __hash__(self):
        return hash((id(self.__self__), self.__func__))

    def __repr__(self):
        return f"<bound node {self.__func__.__qualname__} of {self.__self__!r}>"


class Node:
    """What @node puts on the class.

    Accessed on an instance it is a BoundNode, which evaluates the cell
    (obj, node, *args); accessed on the class it is the node itself.
    """

    # Copied from the wrapped function by functools.update_wrapper.
    __name__: str
    __qualname__: str

    def __init__(self, func):
        self.func = func
        self.owner = None
        self.compiled = None
        functools.update_wrapper(self, func)

    def __set_name__(self, owner, name):
        # The class body is complete here, so every self.<method>() in the
        # source can be checked against it.
        self.owner = owner
        self.compiled = compile_node(self.func, owner, is_node)

    def __get__(self, obj, objtype=None):
        return self if obj is None else BoundNode(self, obj)

    def __call__(self, obj=None, *args, **kwargs):
        if self.owner is None:
            raise TypeError(
                f"@node {self.func.__name__} must be defined inside a class"
            )
        return DEFAULT.evaluate(make_key(obj, self, args, kwargs))

    def __repr__(self):
        return f"<node {self.__qualname__}>"


def is_node(obj):
    return isinstance(obj, Node)


def node(func):
    """Decorator marking a method as a node (a "cell") in the dependency graph."""
    return Node(func)
