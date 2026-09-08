"""The @node decorator and the descriptor it puts on the class."""

import functools
from collections.abc import Callable
from typing import Any, overload

from .compiler import compile_node
from .runtime import DEFAULT, make_key


class Marker:
    """A property a node is declared with, as in @node(node.Stored)."""

    def __init__(self, name):
        self.name = name

    def __repr__(self):
        return self.name


#: Persist this node's value with its object. Stored nodes take no parameters.
Stored = Marker("Stored")


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

    def __call__(self, *args, **kwargs) -> Any:
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

    def __init__(self, func, markers=()):
        self.func = func
        self.owner = None
        self.compiled = None
        self.stored = Stored in markers
        functools.update_wrapper(self, func)

    def __set_name__(self, owner, name):
        # The class body is complete here, so every self.<method>() in the
        # source can be checked against it.
        self.owner = owner
        self.compiled = compile_node(self.func, owner, is_node)
        if self.stored and self.compiled.signature.parameters:
            raise ValueError(
                f"stored node {name} takes parameters; what is persisted is a "
                "cell, and only a node without parameters has one cell per "
                "object"
            )

    # Overloaded so that Calc.a is a Node and calc.a is a BoundNode, rather
    # than the union of the two: a type checker must know that calc.a has
    # set_value on it and takes the node's own arguments.
    @overload
    def __get__(self, obj: None, objtype: type | None = None) -> "Node": ...

    @overload
    def __get__(self, obj: object, objtype: type | None = None) -> "BoundNode": ...

    def __get__(self, obj, objtype=None) -> "Node | BoundNode":
        return self if obj is None else BoundNode(self, obj)

    def __call__(self, obj=None, *args, **kwargs) -> Any:
        if self.owner is None:
            raise TypeError(
                f"@node {self.func.__name__} must be defined inside a class"
            )
        return DEFAULT.evaluate(make_key(obj, self, args, kwargs))

    def __repr__(self):
        return f"<node {self.__qualname__}>"


def is_node(obj):
    return isinstance(obj, Node)


def stored_nodes(cls):
    """The names of a class's stored nodes, base classes first."""
    names = {}
    for klass in reversed(cls.__mro__):
        for name, attr in vars(klass).items():
            if not isinstance(attr, Node):
                continue
            if attr.stored:
                names[name] = None
            else:
                # An override that drops Stored drops it for the subclass.
                names.pop(name, None)
    return tuple(names)


class _Decorator:
    """The @node decorator.

    An object rather than a function so that the markers it accepts hang off
    it as real attributes: @node(node.Stored).
    """

    Stored = Stored

    # Overloaded so that @node gives a Node, rather than the union of a Node
    # and the decorator the marker form returns.
    @overload
    def __call__(self, func: Callable, /) -> Node: ...

    @overload
    def __call__(self, *markers: Marker) -> Callable[[Callable], Node]: ...

    def __call__(self, *markers) -> "Node | Callable[[Callable], Node]":
        """Mark a method as a node (a "cell") in the dependency graph.

        Used bare as @node, or with markers as @node(node.Stored).
        """
        if len(markers) == 1 and not isinstance(markers[0], Marker):
            return Node(markers[0])
        unknown = [m for m in markers if not isinstance(m, Marker)]
        if unknown:
            raise TypeError(f"@node does not take {unknown[0]!r}")
        return lambda func: Node(func, markers)

    def __repr__(self):
        return "<@node>"


node = _Decorator()
