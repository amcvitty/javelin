"""The graph itself: which cells exist, what they depend on, what they are worth.

A cell is one invocation of a node on an object, keyed `(object, method, *args)`.
Terminals are the argument values themselves; everything else is a cell.

Dependencies are held here rather than on the methods that define them, so the
graph can be explored without evaluating anything. One record per cell holds
them, an entry per `ivs` slot, and it may be partial: a slot resolved on its own
is worth keeping, and `UNRESOLVED` is what stops a partial record reading as a
complete one.

A cell's value can also be set directly, which shadows its body and marks
everything downstream of it dirty. Doing that inside `diddle()` makes the change
temporary: the scope remembers what it displaced and puts it back on exit.
"""

import contextlib
import enum
from dataclasses import dataclass

from .ir import Edge, Local, Value

_MISSING = object()


class _Unresolved:
    """The answer to "which cells?" before anyone has gone and looked.

    A singleton rather than None, which a caller would read as "no cells". The
    difference is real: a guard that blocks its call site and a map edge over an
    empty collection genuinely name nothing, and unexplored territory is not the
    same thing.
    """

    __slots__ = ()

    def __repr__(self):
        return "not yet resolved"


#: What a slot's cells are until something resolves them.
UNRESOLVED = _Unresolved()


class ValueState(enum.Enum):
    """What a cell's value is worth right now.

    Four states, and the difference between them matters every time a value
    is shown: `DIRTY` still has a number, but that number is out of date.
    """

    UNCOMPUTED = "uncomputed"  # no value at all; the body has never run
    CLEAN = "clean"  # memoised, and nothing it reads has changed since
    DIRTY = "dirty"  # memoised, but stale: it recomputes when next asked
    OVERRIDDEN = "overridden"  # set directly, so the body never runs

    def __str__(self):
        return self.value


@dataclass(frozen=True)
class CellValue:
    """A cell's value together with the state that qualifies it.

    The two travel as one so that neither can be shown without the other: a
    stale value read on its own would look exactly like a current one.
    `value` means nothing when the state is `UNCOMPUTED`.
    """

    state: ValueState
    value: object = None

    def __str__(self):
        if self.state is ValueState.UNCOMPUTED:
            return str(self.state)
        if self.state is ValueState.CLEAN:
            return repr(self.value)
        return f"{self.value!r} ({self.state})"


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
            f"{edge}: {type(odd.receiver).__name__}.{odd.target} is not "
            "a node, but other elements' are; every element of a comprehension "
            "must resolve the same way"
        )
    return [(call, target) for (call, _), target in zip(resolved, found)]


def _fill(edge, ivs, values):
    """Put an edge's values into its slot: a list for a map, one for a call.

    A guarded-off call site names nothing and leaves its slot alone; the body
    cannot reach it either.
    """
    if edge.collects:
        ivs[edge.index] = values
    elif values:
        ivs[edge.index] = values[0]


def _closure(inputs, index):
    """Every slot that has to be filled in before `index` can be resolved.

    Wider than the input's own `reads`, which the compiler closes through the
    hoisted locals it reaches and no further: an edge in a read set is there to
    be resolved for its cell, not opened up. But filling that edge's slot in
    means resolving it in turn, and so reading whatever *it* reads -- so this
    walk follows edges as well, which `reads` alone does not.
    """
    reached = set()
    pending = list(inputs[index].reads)
    while pending:
        slot = pending.pop()
        if slot not in reached:
            reached.add(slot)
            pending.extend(inputs[slot].reads)
    return reached


def make_key(obj, node, args=(), kwargs=None):
    """The (object, method, *args) key for a cell.

    Canonicalises how the arguments were passed, so that fib(3) and fib(n=3)
    name the same cell.
    """
    bound = node.compiled.signature.bind(*args, **(kwargs or {}))
    bound.apply_defaults()
    return (obj, node, *bound.arguments.values())


def _union(record):
    """Every cell a record names, once each, whatever slot named it."""
    return frozenset().union(*(named for named in record if named is not UNRESOLVED))


class _Expansions:
    """What every cell's expansion knows, navigable back to readers.

    One record per cell: an entry per `ivs` slot, holding either the cells that
    slot names -- keys, in order, duplicates kept, as a map edge produced them
    -- or `UNRESOLVED` where nothing has looked yet. Records are written a slot
    at a time as well as all at once, so most of them are partial most of the
    time; `UNRESOLVED` is what keeps a partial record honest about it.

    `inputs(key)` is the union of the resolved entries; `outputs(key)` is every
    cell with a resolved slot naming it. Only `record`, `reset`, `restore` and
    `discard` write, and each puts both directions right, so the forward and
    reverse views cannot drift out of step -- which is the whole reason this is
    one object rather than a map and an index beside it.
    """

    def __init__(self):
        self._records = {}  # key -> list, one entry per ivs slot
        self._forward = {}  # key -> frozenset of every cell its record names
        self._reverse = {}  # key -> set of keys with a resolved slot naming it

    def __contains__(self, key):
        return key in self._records

    def record_of(self, key, width):
        """This cell's record, `width` long and all `UNRESOLVED` if it has none."""
        record = self._records.get(key)
        return tuple(record) if record is not None else (UNRESOLVED,) * width

    def expanded(self, key):
        """Whether every one of this cell's slots has been resolved."""
        record = self._records.get(key)
        return record is not None and not any(named is UNRESOLVED for named in record)

    def inputs(self, key):
        """Every cell this one is known to read, or an empty frozenset."""
        return self._forward.get(key, frozenset())

    def outputs(self, key):
        """The keys with a resolved slot naming `key`. Live -- do not mutate."""
        return self._reverse.get(key, frozenset())

    def record(self, key, width, named):
        """Record what some of `key`'s slots name, as {slot index: cells}.

        A record is created even when `named` is empty, so that a node with no
        inputs at all counts as expanded rather than being walked again.
        """
        record = self._records.get(key)
        if record is None:
            record = self._records[key] = [UNRESOLVED] * width
        for index, cells in named.items():
            record[index] = cells
        self._point(key, _union(record))

    def reset(self, key, indices):
        """Put some of `key`'s slots back to `UNRESOLVED`."""
        record = self._records.get(key)
        if record is None:
            return
        for index in indices:
            record[index] = UNRESOLVED
        self._point(key, _union(record))

    def discard(self, key):
        """Forget `key`'s record. Cells that name *it* are left alone."""
        self._records.pop(key, None)
        self._point(key, frozenset())
        self._forward.pop(key, None)

    def save(self, key):
        """A copy of `key`'s record, for a diddle scope to put back."""
        record = self._records.get(key)
        return list(record) if record is not None else _MISSING

    def restore(self, key, saved):
        """Put a saved record back, reverse index and all."""
        if saved is _MISSING:
            self.discard(key)
        else:
            self._records[key] = list(saved)
            self._point(key, _union(saved))

    def clear(self):
        self._records.clear()
        self._forward.clear()
        self._reverse.clear()

    def _point(self, key, targets):
        """Point `key` at `targets`, adjusting the reverse view to match."""
        old = self._forward.get(key, frozenset())
        for gone in old - targets:
            readers = self._reverse[gone]
            readers.discard(key)
            if not readers:
                del self._reverse[gone]
        for added in targets - old:
            self._reverse.setdefault(added, set()).add(key)
        self._forward[key] = targets


class Graph:
    """A set of cells and their memoised values.

    Independent instances share compiled nodes -- compilation happens once per
    class -- but nothing else, so each evaluates from scratch.
    """

    def __init__(self):
        self._expansions = _Expansions()  # per-slot records, and their reverse
        self._known = set()  # every key referenced, expanded or not
        self._values = {}  # key -> memoised result
        self._overrides = {}  # key -> value set directly; the body never runs
        self._dirty = set()  # keys whose memoised value is stale
        self._layers = []  # stack of open diddle scopes

    # -- exploring ---------------------------------------------------------

    def all_nodes(self):
        """Every known cell, as (object, method, *args) keys."""
        return tuple(self._known)

    def outputs(self, key):
        """The cells known to read this one, as keys.

        Exactly the cells with a *resolved slot* naming this one, so a slot
        expanded on its own counts and one nothing has looked at does not. That
        partiality is the honest answer: until something asks, the graph has
        not been told.
        """
        return frozenset(self._expansions.outputs(key))

    def value(self, key):
        """This cell's value as it stands, and the state that qualifies it.

        Computes nothing: a cell that has never run reports `UNCOMPUTED`
        rather than being evaluated to answer.
        """
        if key in self._overrides:
            return CellValue(ValueState.OVERRIDDEN, self._overrides[key])
        if key not in self._values:
            return CellValue(ValueState.UNCOMPUTED)
        dirty = key in self._dirty
        return CellValue(
            ValueState.DIRTY if dirty else ValueState.CLEAN, self._values[key]
        )

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
        self._expansions.clear()
        self._known.clear()
        self._values.clear()
        self._overrides.clear()
        self._dirty.clear()
        self._layers.clear()

    # -- building and evaluating -------------------------------------------

    def slots(self, key):
        """What each of this cell's slots names, one entry per `ivs` slot.

        `UNRESOLVED` where nothing has looked yet -- except that a statically
        resolvable slot is filled in on the way past. Working out what such a
        slot names evaluates nothing, so asking and answering are the same act,
        and a cell is never left saying it does not know something free.
        """
        compiled = key[1].compiled
        record = self._expansions.record_of(key, len(compiled.inputs))
        blank = [i for i in compiled.static if record[i] is UNRESOLVED]
        if blank:
            self._write(key, self._resolve(key, blank))
            record = self._expansions.record_of(key, len(compiled.inputs))
        return record

    def expand(self, key):
        """This cell's dependencies, without running its body.

        One pass over the inputs, filling one `ivs` between them and recording
        every slot -- which is `expand_slot` over every slot in effect, but not
        in fact: taken a slot at a time, overlapping closures would be filled in
        again and again.
        """
        if key in self._overrides:
            # A set value shadows the body, so the cell depends on nothing.
            return frozenset()
        if not self._expansions.expanded(key):
            self._write(key, self._run_inputs(key, evaluate_all=False)[0])
        return self._expansions.inputs(key)

    def expand_slot(self, key, index):
        """The cells one of this cell's inputs names, as keys.

        `expand` takes every slot a cell has at once, and evaluates whatever
        all of them read between them. This takes one slot, walking only that
        slot's own closure -- so a slot reaching no edge is answered without
        running a body at all, and one that does costs only its own.

        The answer is a tuple rather than a set: a map edge names one cell per
        element, in the collection's order, duplicates kept. An input that is
        not an edge names no cells, and a call site its guard blocks names none
        either -- resolved to nothing, which is not the same as unresolved.

        Recorded, so the next asker finds it resolved. The record is partial
        until every slot has been asked for, which `UNRESOLVED` says plainly.
        """
        record = self.slots(key)
        if record[index] is UNRESOLVED:
            self._write(key, self._resolve(key, [index]))
            record = self._expansions.record_of(key, len(record))
        return record[index]

    def _resolve(self, key, indices):
        """What each of `indices` names, filling one `ivs` between them all."""
        inputs = key[1].compiled.inputs
        wanted = set().union(*(_closure(inputs, index) for index in indices))
        ivs = self._fill_closure(key, wanted)
        return {index: self._slot_cells(inputs[index], key, ivs) for index in indices}

    def _slot_cells(self, inp, key, ivs):
        """The cells one already-fillable slot names, without its value."""
        if not isinstance(inp, Edge):
            # A terminal or a hoisted local is a value, never a cell.
            return ()
        deps, _ = self._edge_cells(inp, key, ivs, wanted=False)
        return tuple(deps)

    def evaluate(self, key):
        """This cell's value, evaluating its dependencies first."""
        if key in self._overrides:
            return self._overrides[key]
        if key in self._values and key not in self._dirty:
            return self._values[key]
        named, ivs = self._run_inputs(key, evaluate_all=True)
        self._write(key, named)
        obj, node, *_ = key
        self._touch(key)
        self._dirty.discard(key)
        self._values[key] = node.compiled.impl(obj, key, ivs)
        return self._values[key]

    def _write(self, key, named):
        """Put `{slot index: the cells it names}` into a cell's record.

        The one way a record is written. Snapshots it for any open diddle scope
        before changing it, and puts every cell the new entries mention on the
        map -- a cell one slot has been expanded on is a cell the graph knows
        about, which is what lets dirty propagation reach it.
        """
        self._touch(key)
        self._expansions.record(key, len(key[1].compiled.inputs), named)
        self._known.add(key)
        for cells in named.values():
            self._known.update(cells)

    def _run_inputs(self, key, evaluate_all):
        """Walk a cell's inputs in order, resolving each dependency.

        Returns ({slot index: the cells it names}, ivs) -- every slot, so the
        record it writes is complete. A dependency's *value* is only computed
        when evaluate_all is set, or when a later input reads it to work out
        which cell it refers to.
        """
        compiled = key[1].compiled
        ivs: list[object] = [None] * len(compiled.inputs)
        named = {}
        for inp in compiled.inputs:
            wanted = evaluate_all or inp.index in compiled.needed
            named[inp.index] = tuple(self._fill_slot(inp, key, ivs, wanted))
        return named, ivs

    def _fill_closure(self, key, wanted):
        """An `ivs` array with the slots in `wanted` filled in, and no others.

        A slot can only read slots before it, so one pass in slot order
        suffices: whatever a slot reads is already there when it is reached.
        """
        ivs: list[object] = [None] * len(key[1].compiled.inputs)
        for inp in key[1].compiled.inputs:
            if inp.index in wanted:
                self._fill_slot(inp, key, ivs, True)
        return ivs

    def _fill_slot(self, inp, key, ivs, wanted):
        """Put one input's value into its slot, and return the cells it names.

        The one place that knows what each kind of input takes to produce, so
        that expanding a cell and expanding one slot differ only in which slots
        they ask for, rather than each carrying its own copy of the cascade.
        """
        obj, _, *args = key
        if isinstance(inp, Value):
            # An argument's value comes free with the key, so it is always put
            # in place: there is nothing to save by leaving it out.
            ivs[inp.index] = args[inp.index]
            return ()
        if isinstance(inp, Local):
            # A hoisted intermediate: a value, never a dependency. Evaluated
            # during expansion only if a later input's shape reads it.
            if wanted:
                ivs[inp.index] = inp.expr(obj, key, ivs)
            return ()
        deps, values = self._edge_cells(inp, key, ivs, wanted)
        if wanted:
            _fill(inp, ivs, values)
        return deps

    def _edge_cells(self, edge, key, ivs, wanted):
        """The cells one edge names, and their values if `wanted`.

        An edge names zero or more cells: one call site for a plain call, one
        per element for a map. Which cells is always worked out -- that is what
        expansion is -- but the values behind them only when something asks.
        """
        obj = key[0]
        deps, values = [], []
        for call, target in _targets(edge, edge.resolve(obj, key, ivs)):
            if target is None:
                # Not a node on this object after all: an ordinary call, which
                # is a value rather than a cell.
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
        return deps, values

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

        Walks only the dependent cone, following the reverse index back from
        readers to readers, so the cost is independent of the size of the rest
        of the graph.

        A dirtied cell also forgets the slots a value could have moved: a
        changed value can reach an edge's arguments or its guard, and so change
        which cell that slot names. The statically resolvable slots are left
        alone -- they read only terminals and hoisted locals, so nothing that
        dirties the cell can change what they name, and resetting them would
        throw away answers that are still correct.
        """
        pending = list(self._expansions.outputs(key))
        while pending:
            dependent = pending.pop()
            if dependent in self._dirty or dependent in self._overrides:
                # A cell with a value of its own cannot go stale, and nothing
                # behind it can hear about this change either.
                continue
            self._touch(dependent)
            self._dirty.add(dependent)
            pending.extend(self._expansions.outputs(dependent))
            self._expansions.reset(dependent, dependent[1].compiled.not_static)

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
                self._expansions.save(key),
                key in self._dirty,
                self._overrides.get(key, _MISSING),
            )

    def _restore(self, saved):
        """Put back everything a diddle scope displaced.

        One mechanism covers all of it: values the scope invalidated come back,
        values it computed are dropped, and set values revert to whatever the
        enclosing scope had. Nothing is recomputed.
        """
        for key, (value, record, was_dirty, override) in saved.items():
            _restore_entry(self._values, key, value)
            self._expansions.restore(key, record)  # reverse edges and all
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
