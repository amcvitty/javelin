"""What one cell looks like on screen, worked out without a terminal.

Three shapes, one per region of the display: a header card of label/value
pairs, a row per input slot, and a row per known output. Each is plain data,
so what is shown can be tested without a terminal attached and the terminal
library stays on the other side of this module.

Nothing here evaluates anything. Reading a cell's value, its slots and its
outputs is what the engine already knows; the statically resolvable slots come
back filled in because working them out is free, and every other slot reports
itself unresolved and waits to be asked. A body runs only when something calls
`expand_slot`, and nothing here does.

Two questions the display has to keep apart, because the engine does:

*unresolved* -- nothing has looked yet, and looking may cost an evaluation.
*resolved to no cells* -- something looked, and there is genuinely nothing
there: a guard blocked the call site, or a map edge ran over an empty
collection. Both come back as an empty tuple of cells, and the value column
says which.
"""

from dataclasses import dataclass

from graph import UNRESOLVED, Cell, InputKind, ValueState

#: How much room the identity column has before it is truncated.
IDENTITY_WIDTH = 44

#: How much room a value has. A slot's value can be a whole collection -- a
#: book's list of position paths is one string per member -- and one row must
#: not be able to push the rest of the table off the screen.
VALUE_WIDTH = 36

#: How many of a map edge's elements are shown before the rest are summarised.
#: A book of a thousand positions is one slot, and one slot must not be able
#: to fill the display.
MAP_ROW_CAP = 12

#: The input table's columns, in order.
INPUT_COLUMNS = ("slot", "kind", "identity", "value", "guard", "reads")

#: The output table's columns. Its own schema: an output is a cell, not a slot,
#: so it has no kind, no guard and no read set.
OUTPUT_COLUMNS = ("cell", "value")

_ELLIPSIS = "..."

#: A terminal whose value the key does not carry, which `None` would look like.
_MISSING = object()


def truncate_left(text, width=IDENTITY_WIDTH):
    """Shorten from the left, keeping the tail.

    Namespace paths share their heads and differ at their tails:
    `/mkt/EQ/ACME/Market` and `/mkt/EQ/WIDGET/Market` are told apart by what
    comes last. Cutting the front is what keeps two markets on different
    underlyings distinguishable.
    """
    if len(text) <= width:
        return text
    return _ELLIPSIS + text[len(text) - width + len(_ELLIPSIS) :]


def truncate_right(text, width):
    """Shorten from the right, keeping the head.

    The other half of the rule. Source text and values are discriminated by
    what comes *first* -- `legs = [...]` is named by `legs`, and a long list is
    recognised by its first few elements -- so they lose their tails. Only a
    cell identity, whose namespace path shares its head with its neighbours,
    is cut the other way round.
    """
    if len(text) <= width:
        return text
    return text[: width - len(_ELLIPSIS)] + _ELLIPSIS


def object_name(obj):
    """What to call an object on screen.

    A namespace object knows its own name, which is the useful thing to show.
    Anything else is named by its class -- never by its `repr`, which would
    put a memory address in front of a reader as though it meant something.
    """
    name = getattr(obj, "name", None)
    return name if isinstance(name, str) else type(obj).__name__


def arguments(cell):
    """A cell's arguments as written in a call, or an empty string for none."""
    return ", ".join(repr(arg) for arg in cell.args)


def cell_label(cell, *, relative_to=None):
    """One cell, in this repo's own vocabulary: object, method and arguments.

    Not `Cell.__str__`, which names the class. On screen the object is the
    interesting half -- two positions of the same class are the same string
    otherwise.

    `relative_to` is the object of the cell currently on screen. A row naming
    a cell on that same object is named `self.method(...)` rather than
    repeating the path a reader is already looking at -- the identity column
    only has to earn its width when the receiver is somewhere else.
    """
    same_object = relative_to is not None and cell.obj is relative_to
    receiver = "self" if same_object else object_name(cell.obj)
    return f"{receiver}.{cell.method_name}({arguments(cell)})"


def value_text(cell_value, width=VALUE_WIDTH):
    """A value narrow enough for a table cell, still carrying its state.

    The state is what makes a value safe to show, so it is never what gets
    cut: the value itself is shortened and the qualifier kept, rather than
    truncating `CellValue`'s own text and losing `(dirty)` off the end of it.
    """
    if cell_value.state is ValueState.UNCOMPUTED:
        return str(cell_value.state)
    shown = truncate_right(repr(cell_value.value), width)
    if cell_value.state is ValueState.CLEAN:
        return shown
    return f"{shown} ({cell_value.state})"


def value_type(cell_value):
    """The type of a value, or blank when there is no value to take it of."""
    if cell_value.state is ValueState.UNCOMPUTED:
        return ""
    return type(cell_value.value).__name__


def header_card(cell):
    """The header card as label/value pairs, in display order.

    The value carries its own state -- `CellValue.__str__` writes all four
    distinguishably -- so a dirty number can never be shown as a current one.
    """
    return (
        ("cell", cell_label(cell)),
        ("object", object_name(cell.obj)),
        ("class", cell.cls.__name__),
        ("method", cell.method_name),
        ("arguments", arguments(cell)),
        ("value", str(cell.value)),
        ("type", value_type(cell.value)),
    )


@dataclass(frozen=True)
class InputRow:
    """One row of the input table: one slot, or one element of a map edge.

    `slot` is the slot's index, sub-indexed as `4.0`, `4.1` for the elements a
    map edge named, so an element is always visibly part of its slot.

    `slot_index` and `sub_index` are not columns -- nothing displays them --
    but they are how navigation finds its way back to the slot and, for a map
    edge, the element this row names. `sub_index` is `None` for a row that
    names no single element: a non-map edge, a terminal, a local, or the "N
    more" row a capped map edge leaves behind.
    """

    slot: str
    kind: str
    identity: str
    value: str
    guard: str
    reads: str
    slot_index: int
    sub_index: int | None = None


def _reads(slot):
    """A slot's read set, in slot order so it reads like slot indices."""
    return ", ".join(str(index) for index in sorted(slot.reads))


def _terminal_values(cell):
    """Each parameter's value, by name, taken straight from the key.

    A terminal needs no computing -- the key already carries its value -- so
    showing it costs nothing. Bound through the node's own signature so that
    defaults appear for arguments the call left out.
    """
    bound = cell.node.compiled.signature.bind(*cell.args)
    bound.apply_defaults()
    return bound.arguments


def _row(slot, identity, value, *, sub=None, nav_sub=None):
    """One input row, with the slot index sub-indexed if this is an element.

    `value` arrives ready to show -- `value_text` for a cell's value, a plain
    word for a slot that has no cell to have one.

    `nav_sub` is the element index navigation should use, when it differs from
    `sub`'s display purpose -- the "N more" row is labelled with the count it
    stands for but names no element of its own, so it leaves `nav_sub` at its
    default of `None` rather than passing the count.
    """
    index = str(slot.index) if sub is None else f"{slot.index}.{sub}"
    return InputRow(
        slot=index,
        kind=str(slot.kind),
        identity=identity,
        value=value,
        guard=slot.guard_source or "",
        reads=_reads(slot),
        slot_index=slot.index,
        sub_index=nav_sub,
    )


def unresolved_reason(slot):
    """Why an edge that resolved to no cells named nothing.

    Distinguishing these on screen is the whole reason the engine keeps
    "resolved to none" apart from "not yet resolved". Shared with navigation,
    so a row's value column and a failed drill's reason say the same thing.
    """
    if slot.kind is InputKind.MAP_EDGE:
        return "no elements"
    return "not reached"


def _target_call(slot):
    """How to name an edge with no cell to name it after.

    The method it calls, which is the most of the answer that is known before
    the edge is resolved -- and is recognisable, which a map edge's own call
    site is not: that is a whole comprehension, and truncating it would throw
    away the end a reader needs.
    """
    return f"{slot.target}()"


def _edge_rows(slot, width, cap, relative_to):
    """The rows one edge contributes: unresolved, empty, one cell, or many."""
    if slot.cells is UNRESOLVED:
        return (_row(slot, _target_call(slot), str(UNRESOLVED)),)
    if not slot.cells:
        return (_row(slot, _target_call(slot), unresolved_reason(slot)),)
    if slot.kind is not InputKind.MAP_EDGE:
        cell = slot.cells[0]
        label = cell_label(cell, relative_to=relative_to)
        return (_row(slot, truncate_left(label, width), value_text(cell.value)),)

    rows = [
        _row(
            slot,
            truncate_left(cell_label(cell, relative_to=relative_to), width),
            value_text(cell.value),
            sub=sub,
            nav_sub=sub,
        )
        for sub, cell in enumerate(slot.cells[:cap])
    ]
    remainder = len(slot.cells) - cap
    if remainder > 0:
        rows.append(_row(slot, f"... {remainder} more", "", sub=cap))
    return tuple(rows)


def input_rows(cell, *, width=IDENTITY_WIDTH, cap=MAP_ROW_CAP):
    """A row per slot in `ivs` order, with a map edge's elements fanned out.

    Every slot appears, whatever fills it: the table is the `ivs` array, and a
    gap in it would be a lie about what the body reads. A slot that names no
    cells -- a terminal, a hoisted local -- shows the slot as written.
    """
    terminals = _terminal_values(cell)
    rows = []
    for slot in cell.slots:
        if slot.kind is InputKind.TERMINAL:
            value = terminals.get(slot.source, _MISSING)
            shown = (
                "" if value is _MISSING else truncate_right(repr(value), VALUE_WIDTH)
            )
            rows.append(_row(slot, truncate_right(slot.source, width), shown))
        elif slot.kind is InputKind.LOCAL:
            # A local's value would mean running its expression, and looking
            # is meant to be free. Its name is at the front of its source, so
            # this is the one identity that keeps its head.
            rows.append(_row(slot, truncate_right(slot.source, width), ""))
        else:
            rows.extend(_edge_rows(slot, width, cap, cell.obj))
    return tuple(rows)


@dataclass(frozen=True)
class OutputRow:
    """One cell known to read this one.

    `target` is not a column -- nothing displays it -- but it is the cell
    navigation drills into: an output is a cell already, with nothing to
    resolve first.
    """

    cell: str
    value: str
    target: Cell


def output_rows(cell, *, width=IDENTITY_WIDTH):
    """A row per cell known to read this one, in a stable order.

    Partial by nature, and deliberately not labelled as such: a cell can
    always be added, so "the ones known so far" is the only output list that
    could ever exist, and saying so on every screen would say nothing.
    """
    entries = sorted(
        (
            (cell_label(output, relative_to=cell.obj), value_text(output.value), output)
            for output in cell.outputs
        ),
        key=lambda entry: entry[:2],
    )
    return tuple(
        OutputRow(cell=truncate_left(label, width), value=value, target=target)
        for label, value, target in entries
    )
