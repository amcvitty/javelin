"""Walking a cell's inputs backwards into a plain, drawable data structure.

`build_graph` is the only function here that touches the engine. It reads
`Cell.slots` and, where a slot is not already resolved, calls
`Cell.expand_slot` -- the cost the engine's own `blocked_by` accounting
already warned about, and no more. It never calls `Cell.evaluate`: a node's
own body is not run to draw its picture.

A `Value` or `Local` input never becomes a node or an edge of its own --
`Cell.slots` says a terminal's value comes free with the key and a local's
source is free to read, so both are folded into an annotation on the cell
that owns them (`GraphData.nodes[...].annotations`).

A `MapEdge` that names any cells at all is always collapsed into a
`GroupEntry`, whatever its size -- there is no threshold below which it is
shown inline, matching the decision to replace a fan-out cap with
click-to-expand entirely. Its members are still walked in full up front, so
expanding one in the browser later needs no further computation, only their
`NodeEntry.group` marks them hidden until then.

An overridden cell is drawn as a leaf: `Graph.expand` already treats a set
value as shadowing the body and reads nothing behind it, and `cell.slots`
does not know that -- it describes the body's structure whether or not the
body still runs -- so this module checks the value's state itself before
walking a cell's slots at all.

A cell reached twice is one node: the first visit assigns its id, and a
later one reuses it without re-walking its edges, whether the second visit
is an ordinary shared dependency (a diamond) or a genuine cycle -- a key
still open on the current traversal path. The two are told apart so a cycle
can be flagged rather than silently merged: an unexpected cycle is a bug in
the engine's invariants, and is worth a visibly distinct edge rather than an
infinite recursion.
"""

import itertools
from dataclasses import dataclass, field

from graph import UNRESOLVED, Cell, InputKind, ValueState

#: A terminal whose value the key does not carry, which `None` would look like.
_MISSING = object()


@dataclass(frozen=True)
class NodeEntry:
    """One reachable cell, as drawn: its label, its worth, and its owner.

    `group` is the id of the `GroupEntry` this node is hidden inside, or
    `None` if it is visible as soon as the picture is shown -- reached from
    the root without crossing a collapsed `MapEdge`.
    """

    id: str
    label: str
    value_state: str
    value: str
    annotations: tuple[str, ...]
    group: str | None


@dataclass(frozen=True)
class GroupEntry:
    """One collapsed `MapEdge`'s fan-out: every element it named, pre-built.

    `group` nests one collapsed group inside another, the same way a
    `NodeEntry`'s does -- a `MapEdge` reached only through another group's
    members is itself hidden until the outer one is revealed.
    """

    id: str
    guard: str | None
    group: str | None
    members: tuple[str, ...]


@dataclass(frozen=True)
class EdgeEntry:
    """One `Edge` input, resolved: what it named, or why it named nothing.

    `to_type` is `"cell"` for an edge naming one node (`to_id` is its id,
    `cycle` set if that id is an open ancestor rather than a fresh visit),
    `"group"` for a collapsed `MapEdge` (`to_id` is the `GroupEntry`'s id),
    or `"guarded_off"` for an edge that named no cells at all -- a blocked
    call site or a map over nothing -- which carries no `to_id`.
    """

    from_: str
    slot_index: int
    kind: str
    guard: str | None
    to_type: str
    to_id: str | None
    cycle: bool = False


@dataclass(frozen=True)
class GraphData:
    """The whole picture: one root, and everything reachable behind it."""

    root: str
    nodes: dict[str, NodeEntry] = field(default_factory=dict)
    groups: dict[str, GroupEntry] = field(default_factory=dict)
    edges: tuple[EdgeEntry, ...] = ()


def _object_name(obj):
    """What to call an object on screen: its own name, or its class."""
    name = getattr(obj, "name", None)
    return name if isinstance(name, str) else type(obj).__name__


def _label(cell):
    """A cell in this repo's own vocabulary: object, method and arguments."""
    args = ", ".join(repr(arg) for arg in cell.args)
    return f"{_object_name(cell.obj)}.{cell.method_name}({args})"


def _value_text(cell_value):
    """A value's repr, or "" when there is no value yet to have one."""
    if cell_value.state is ValueState.UNCOMPUTED:
        return ""
    return repr(cell_value.value)


def _terminal_values(cell):
    """Each parameter's value, by name, taken straight from the key.

    Costs nothing: a terminal's value comes free with the key. Bound through
    the node's own signature so that defaults appear for arguments the call
    left out -- the same trick `tui/graph_browser/render.py` uses.
    """
    bound = cell.node.compiled.signature.bind(*cell.args)
    bound.apply_defaults()
    return bound.arguments


def _annotations(cell):
    """A `Value`/`Local` slot per entry, in slot order, as shown text.

    Reading `cell.slots` here evaluates nothing -- the engine resolves the
    statically resolvable slots for free on the way past -- so this is safe
    to call for every cell, overridden or not.
    """
    terminals = _terminal_values(cell)
    annotations = []
    for slot in cell.slots:
        if slot.kind is InputKind.TERMINAL:
            value = terminals.get(slot.source, _MISSING)
            if value is not _MISSING:
                annotations.append(f"{slot.source}={value!r}")
        elif slot.kind is InputKind.LOCAL:
            annotations.append(slot.source)
    return tuple(annotations)


def build_graph(root: Cell) -> GraphData:
    """The transitive dependency graph rooted at `root`, as plain data."""
    ids: dict[tuple, str] = {}
    nodes: dict[str, NodeEntry] = {}
    groups: dict[str, GroupEntry] = {}
    edges: list[EdgeEntry] = []
    done: set[tuple] = set()
    path: set[tuple] = set()
    group_ids = (f"g{n}" for n in itertools.count())

    def node_id_for(cell, group):
        key = cell.key
        if key in ids:
            return ids[key]
        node_id = f"n{len(ids)}"
        ids[key] = node_id
        nodes[node_id] = NodeEntry(
            id=node_id,
            label=_label(cell),
            value_state=str(cell.value.state),
            value=_value_text(cell.value),
            annotations=_annotations(cell),
            group=group,
        )
        return node_id

    def visit(cell, group):
        node_id = node_id_for(cell, group)
        key = cell.key
        if key in path or key in done:
            # Already open (a cycle, flagged by the caller) or already fully
            # walked (a diamond) -- either way its edges are not walked again.
            return node_id
        if cell.value.state is ValueState.OVERRIDDEN:
            # An override shadows the body: `Graph.expand` says this cell
            # depends on nothing, and `cell.slots` does not know that.
            done.add(key)
            return node_id
        path.add(key)
        for slot in cell.slots:
            if slot.kind in (InputKind.TERMINAL, InputKind.LOCAL):
                continue  # folded into the node's own annotations already
            cells = (
                slot.cells
                if slot.cells is not UNRESOLVED
                else cell.expand_slot(slot.index)
            )
            kind = str(slot.kind)
            if not cells:
                edges.append(
                    EdgeEntry(
                        from_=node_id,
                        slot_index=slot.index,
                        kind=kind,
                        guard=slot.guard_source,
                        to_type="guarded_off",
                        to_id=None,
                    )
                )
            elif slot.kind is InputKind.MAP_EDGE:
                group_id = next(group_ids)
                member_ids = tuple(visit(member, group_id) for member in cells)
                groups[group_id] = GroupEntry(
                    id=group_id,
                    guard=slot.guard_source,
                    group=group,
                    members=member_ids,
                )
                edges.append(
                    EdgeEntry(
                        from_=node_id,
                        slot_index=slot.index,
                        kind=kind,
                        guard=slot.guard_source,
                        to_type="group",
                        to_id=group_id,
                    )
                )
            else:
                target = cells[0]
                cycle = target.key in path
                target_id = (
                    node_id_for(target, group) if cycle else visit(target, group)
                )
                edges.append(
                    EdgeEntry(
                        from_=node_id,
                        slot_index=slot.index,
                        kind=kind,
                        guard=slot.guard_source,
                        to_type="cell",
                        to_id=target_id,
                        cycle=cycle,
                    )
                )
        path.discard(key)
        done.add(key)
        return node_id

    root_id = visit(root, None)
    return GraphData(root=root_id, nodes=nodes, groups=groups, edges=tuple(edges))
