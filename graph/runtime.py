"""The graph itself: which cells exist, what they depend on, what they are worth.

A cell is one invocation of a node on an object, keyed `(object, method, *args)`.
Terminals are the argument values themselves; everything else is a cell.

Dependencies are held here rather than on the methods that define them, so the
graph can be explored without evaluating anything.
"""

from .ir import Value


def make_key(obj, node, args=(), kwargs=None):
    """The (object, method, *args) key for a cell.

    Canonicalises how the arguments were passed, so that fib(3) and fib(n=3)
    name the same cell.
    """
    bound = node.compiled.signature.bind(*args, **(kwargs or {}))
    bound.apply_defaults()
    return (obj, node, *bound.arguments.values())


class Graph:
    """A set of cells and their memoised values.

    Independent instances share compiled nodes -- compilation happens once per
    class -- but nothing else, so each evaluates from scratch.
    """

    def __init__(self):
        self._deps = {}  # key -> frozenset of dependency keys, once expanded
        self._known = set()  # every key referenced, expanded or not
        self._values = {}  # key -> memoised result

    # -- exploring ---------------------------------------------------------

    def all_nodes(self):
        """Every known cell, as (object, method, *args) keys."""
        return tuple(self._known)

    def deps(self, method, *args, **kwargs):
        """The direct dependencies of the cell obj.method(*args), as keys.

        `method` is bound, e.g. deps(calc.fib, 5). Worked out from the node's
        inputs, so the cell itself never runs. Raises KeyError if the
        method is not a node.
        """
        if not hasattr(method, "__self__"):
            raise TypeError("deps needs a bound method, e.g. deps(calc.fib, 5)")
        node = method.__func__
        if not hasattr(node, "compiled"):
            raise KeyError(method)
        return self.expand(make_key(method.__self__, node, args, kwargs))

    def clear(self):
        """Forget every cell. Mainly for building graphs in isolation."""
        self._deps.clear()
        self._known.clear()
        self._values.clear()

    # -- building and evaluating -------------------------------------------

    def expand(self, key):
        """This cell's dependencies, without running its body."""
        if key not in self._deps:
            self._record(key, self._run_inputs(key, evaluate_all=False)[0])
        return self._deps[key]

    def evaluate(self, key):
        """This cell's value, evaluating its dependencies first."""
        if key in self._values:
            return self._values[key]
        deps, ivs = self._run_inputs(key, evaluate_all=True)
        self._record(key, deps)
        obj, node, *_ = key
        self._values[key] = node.compiled.impl(obj, key, ivs)
        return self._values[key]

    def _record(self, key, deps):
        self._deps[key] = deps
        self._known.add(key)
        self._known.update(deps)

    def _run_inputs(self, key, evaluate_all):
        """Walk a cell's inputs in order, resolving each dependency.

        Returns (dependency keys, ivs). A dependency's *value* is only computed
        when evaluate_all is set, or when a later input reads it to work out
        which cell it refers to.
        """
        obj, node, *args = key
        compiled = node.compiled
        ivs = [None] * len(compiled.inputs)
        deps = []
        for inp in compiled.inputs:
            if isinstance(inp, Value):
                ivs[inp.index] = args[inp.index]
                continue
            if inp.guard is not None and not inp.guard(obj, key, ivs):
                continue
            positional, keywords = inp.args(obj, key, ivs)
            # Looked up on the object's own type, so a subclass may override
            # a node.
            dep = make_key(obj, getattr(type(obj), inp.target), positional, keywords)
            deps.append(dep)
            if evaluate_all or inp.index in compiled.needed:
                ivs[inp.index] = self.evaluate(dep)
        return frozenset(deps), ivs


DEFAULT = Graph()
