"""The graph itself: which cells exist, what they depend on, what they are worth.

A cell is one invocation of a node on an object, keyed `(object, method, *args)`.
Terminals are the argument values themselves; everything else is a cell.

Dependencies are held here rather than on the methods that define them, so the
graph can be explored without evaluating anything.

A cell's value can also be set directly, which shadows its body and marks
everything downstream of it dirty. Doing that inside `diddle()` makes the change
temporary: the scope remembers what it displaced and puts it back on exit.
"""

import contextlib

from .ir import Local, Value

_MISSING = object()


def _targets(edge, calls):
    """Pair each resolved call with the node it names, or None for a plain call.

    Looked up on the receiver's own type, so a subclass may override a node.

    An edge naming many cells has to name them all the same way: a collection
    that is part cells and part plain values would contribute dependencies for
    some of its members and silently not for others, which is the kind of
    half-connected graph this whole layer exists to prevent.
    """
    resolved = [
        (call, getattr(type(call.receiver), call.target, None)) for call in calls
    ]
    found = [target if hasattr(target, "compiled") else None for _, target in resolved]
    if edge.collects and any(t is not None for t in found) and not all(found):
        odd = next(call for (call, _), target in zip(resolved, found) if target is None)
        raise TypeError(
            f"{edge.source}: {type(odd.receiver).__name__}.{odd.target} is not "
            "a node, but other elements' are; every element of a comprehension "
            "must resolve the same way"
        )
    return [(call, target) for (call, _), target in zip(resolved, found)]


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
        self._overrides = {}  # key -> value set directly; the body never runs
        self._dirty = set()  # keys whose memoised value is stale
        self._dependents = {}  # dep key -> set of keys that read it; tracks _deps
        self._layers = []  # stack of open diddle scopes

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

    def dirty(self):
        """Every cell whose memoised value is stale, as keys."""
        return tuple(self._dirty)

    def is_dirty(self, key):
        """Whether this cell will recompute the next time it is asked for."""
        return key in self._dirty

    def clear(self):
        """Forget every cell. Mainly for building graphs in isolation."""
        self._deps.clear()
        self._known.clear()
        self._values.clear()
        self._overrides.clear()
        self._dirty.clear()
        self._dependents.clear()
        self._layers.clear()

    # -- building and evaluating -------------------------------------------

    def expand(self, key):
        """This cell's dependencies, without running its body."""
        if key in self._overrides:
            # A set value shadows the body, so the cell depends on nothing.
            return frozenset()
        if key not in self._deps or key in self._dirty:
            # A dirty cell is re-expanded: a changed value can reach an edge's
            # arguments or guard, and so change the shape of the graph.
            self._record(key, self._run_inputs(key, evaluate_all=False)[0])
        return self._deps[key]

    def evaluate(self, key):
        """This cell's value, evaluating its dependencies first."""
        if key in self._overrides:
            return self._overrides[key]
        if key in self._values and key not in self._dirty:
            return self._values[key]
        deps, ivs = self._run_inputs(key, evaluate_all=True)
        self._record(key, deps)
        obj, node, *_ = key
        self._touch(key)
        self._dirty.discard(key)
        self._values[key] = node.compiled.impl(obj, key, ivs)
        return self._values[key]

    def _record(self, key, deps):
        self._touch(key)
        self._set_deps(key, deps)
        self._known.add(key)
        self._known.update(deps)

    def _set_deps(self, key, deps):
        """Point this cell at `deps`, or drop the entry when `deps` is _MISSING.

        The sole writer of `_deps`, so the reverse index in `_dependents` is
        kept in step here -- one cell's worth of work -- rather than rebuilt
        from the whole graph every time a value is set.
        """
        was = self._deps.get(key, _MISSING)
        old = () if was is _MISSING else was
        new = () if deps is _MISSING else deps
        for dep in old:
            if dep not in new:
                readers = self._dependents.get(dep)
                if readers is not None:
                    readers.discard(key)
                    if not readers:
                        del self._dependents[dep]
        for dep in new:
            if dep not in old:
                self._dependents.setdefault(dep, set()).add(key)
        if deps is _MISSING:
            self._deps.pop(key, None)
        else:
            self._deps[key] = deps

    def _run_inputs(self, key, evaluate_all):
        """Walk a cell's inputs in order, resolving each dependency.

        Returns (dependency keys, ivs). A dependency's *value* is only computed
        when evaluate_all is set, or when a later input reads it to work out
        which cell it refers to.
        """
        obj, node, *args = key
        compiled = node.compiled
        ivs: list[object] = [None] * len(compiled.inputs)
        deps = []
        for inp in compiled.inputs:
            if isinstance(inp, Value):
                ivs[inp.index] = args[inp.index]
                continue
            if isinstance(inp, Local):
                # A hoisted intermediate: a value, never a dependency. Evaluated
                # during expansion only if a later input's shape reads it.
                if evaluate_all or inp.index in compiled.needed:
                    ivs[inp.index] = inp.expr(obj, key, ivs)
                continue
            # An edge names zero or more cells: one call site for a plain call,
            # one per element for a map. Resolving is always done -- that is
            # what expansion is -- but the values behind it only when wanted.
            calls = inp.resolve(obj, key, ivs)
            wanted = evaluate_all or inp.index in compiled.needed
            values = []
            for call, target in _targets(inp, calls):
                if target is None:
                    # Not a node on this object after all: an ordinary call,
                    # which is a value rather than a cell.
                    if wanted:
                        values.append(
                            getattr(call.receiver, call.target)(
                                *call.positional, **call.keywords
                            )
                        )
                    continue
                dep = make_key(call.receiver, target, call.positional, call.keywords)
                deps.append(dep)
                if wanted:
                    values.append(self.evaluate(dep))
            if not wanted:
                continue
            if inp.collects:
                ivs[inp.index] = values
            elif values:
                # A guarded-off call site names nothing and leaves its slot
                # alone; the body cannot reach it either.
                ivs[inp.index] = values[0]
        return frozenset(deps), ivs

    # -- setting values ----------------------------------------------------

    def set_value(self, key, value):
        """Give this cell a value directly, so its body never runs.

        Everything downstream of it is marked dirty and recomputed on demand.
        """
        self._touch(key)
        self._overrides[key] = value
        self._known.add(key)
        self._dirty.discard(key)
        self._dirty_from(key)

    def clear_value(self, key):
        """Drop a set value, so the cell computes again.

        Whatever the cell had memoised before it was set is still correct --
        `evaluate` returns an override before ever writing `_values`, so a set
        value can never overwrite a computed one -- but the cells downstream
        saw the override, so they are dirtied.
        """
        self._touch(key)
        self._overrides.pop(key, None)
        self._dirty_from(key)

    def _dirty_from(self, key):
        """Mark everything that depends on this cell, transitively, as dirty.

        Walks only the dependent cone, off the `_dependents` index, so the cost
        of setting a value is independent of the size of the rest of the graph.
        """
        pending = list(self._dependents.get(key, ()))
        while pending:
            dependent = pending.pop()
            if dependent in self._dirty or dependent in self._overrides:
                # A cell with a value of its own cannot go stale, and nothing
                # behind it can hear about this change either.
                continue
            self._touch(dependent)
            self._dirty.add(dependent)
            pending.extend(self._dependents.get(dependent, ()))

    # -- diddle scopes -----------------------------------------------------

    @contextlib.contextmanager
    def diddle(self, *entries):
        """Set values temporarily, restoring the graph exactly on exit.

        Each entry is a bound node followed by the arguments `set_value` takes,
        so diddle((md.spot, 110.0)) and diddle((sheet.fib, 5.0, (3,))) are
        shorthand for the corresponding calls inside the block.
        """
        self._layers.append({})
        try:
            for target, value, *rest in entries:
                self.set_value(make_key(target.__self__, target.__func__, *rest), value)
            yield
        finally:
            self._restore(self._layers.pop())

    def _touch(self, key):
        """Snapshot a cell's state into the innermost diddle, before changing it.

        First write wins, so what is kept is always the state as the scope
        began -- which is what exiting has to put back.
        """
        if self._layers and key not in self._layers[-1]:
            self._layers[-1][key] = (
                self._values.get(key, _MISSING),
                self._deps.get(key, _MISSING),
                key in self._dirty,
                self._overrides.get(key, _MISSING),
            )

    def _restore(self, saved):
        """Put back everything a diddle scope displaced.

        One mechanism covers all of it: values the scope invalidated come back,
        values it computed are dropped, and set values revert to whatever the
        enclosing scope had. Nothing is recomputed.
        """
        for key, (value, deps, was_dirty, override) in saved.items():
            _restore_entry(self._values, key, value)
            self._set_deps(key, deps)  # reverts the reverse index too
            _restore_entry(self._overrides, key, override)
            if was_dirty:
                self._dirty.add(key)
            else:
                self._dirty.discard(key)


def _restore_entry(store, key, saved):
    if saved is _MISSING:
        store.pop(key, None)
    else:
        store[key] = saved


DEFAULT = Graph()
