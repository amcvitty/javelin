"""The @node decorator and the descriptor it puts on the class."""

import functools
import types

from .compiler import compile_node
from .runtime import DEFAULT, make_key


class Node:
    """What @node puts on the class.

    Accessed on an instance it is a bound method that evaluates the cell
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
        return self if obj is None else types.MethodType(self, obj)

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
