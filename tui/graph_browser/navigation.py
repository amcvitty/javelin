"""Walking the graph: a focused cell, a back-stack, and a depth.

None of this exists in the graph. A focused cell, the path taken to reach it,
and how deep that path runs are concepts that exist only because a human is
looking at a terminal -- the graph describes cells and knows nothing about who
is reading them. So this module imports no terminal library and knows nothing
of tables or key bindings either; it is plain state, testable directly.

Drilling and resolving never run a node's own body. `expand_slot` may still
evaluate whatever an edge's guard or a map's collection reads -- the cost its
`blocked_by` warned about -- but the cell being navigated to is never the one
evaluated. Only `evaluate` is deliberate about running bodies, and nothing
here calls it except the two methods named for it.

The back-stack is a history, not a set: revisiting a cell already on it is
ordinary, and going back at the root does nothing rather than erroring.
"""

from dataclasses import dataclass

from graph import UNRESOLVED, Cell, InputKind

from .render import unresolved_reason

#: Why a slot of this kind has no cell behind it -- it was never an edge, so
#: there was never anything to resolve.
_NOT_AN_EDGE = {
    InputKind.TERMINAL: "a terminal has no cell behind it",
    InputKind.LOCAL: "a hoisted local has no cell behind it",
}

#: Why drilling into an unresolved or capped map-edge row does not navigate:
#: it may now name several cells, and one keystroke cannot pick among them.
_PICK_AN_ELEMENT = "a map edge -- drill into one of its elements"

#: Why evaluating a row that has not been resolved does not run anything:
#: evaluation is deliberate and is never a side effect of looking.
_NOT_YET_RESOLVED = "not yet resolved"


@dataclass(frozen=True)
class ActionResult:
    """What came of trying to act on a row.

    `ok` is the whole answer a caller needs to act on -- whether to move on or
    stay put. `reason` is only for a human, filled in when there was nothing
    to act on.
    """

    ok: bool
    reason: str = ""


class Navigation:
    """Where a human is in the graph, and the path taken to get there.

    `focus` is the cell currently on screen. `depth` and `breadcrumb` fall out
    of the back-stack rather than being tracked alongside it, so they can
    never drift out of step with the path actually taken.
    """

    def __init__(self, root: Cell):
        self.focus = root
        self._stack: list[Cell] = []

    @property
    def depth(self) -> int:
        """How many cells below the root the current focus sits."""
        return len(self._stack)

    @property
    def breadcrumb(self) -> tuple[Cell, ...]:
        """The path taken to the current focus, root first."""
        return (*self._stack, self.focus)

    def back(self) -> None:
        """Return to the previous cell. Does nothing at the root."""
        if self._stack:
            self.focus = self._stack.pop()

    def resolve_slot(self, index: int) -> None:
        """Fill in one of the focused cell's slots, leaving focus where it is."""
        self.focus.expand_slot(index)

    def drill_slot(self, index: int, sub: int | None = None) -> ActionResult:
        """Navigate to the cell one of the focused cell's slots names.

        Resolves the slot first if nothing has looked yet -- one keystroke for
        one intention. A slot with no single cell to land on does not
        navigate: a terminal or hoisted local never had one, a blocked call
        site or an empty map resolved to none, and an unresolved or capped map
        edge may now name several, which one keystroke cannot choose among.
        """
        slot = self.focus.slots[index]
        not_an_edge = _NOT_AN_EDGE.get(slot.kind)
        if not_an_edge is not None:
            return ActionResult(False, not_an_edge)
        cells = slot.cells
        if cells is UNRESOLVED:
            cells = self.focus.expand_slot(index)
        if not isinstance(cells, tuple) or not cells:
            return ActionResult(False, unresolved_reason(slot))
        if slot.kind is InputKind.MAP_EDGE and sub is None:
            return ActionResult(False, _PICK_AN_ELEMENT)
        self._navigate(cells[sub if sub is not None else 0])
        return ActionResult(True)

    def drill_output(self, cell: Cell) -> ActionResult:
        """Navigate to a cell already known to read the focused one.

        Always succeeds: an output is a cell, resolved by definition, so
        drilling into one works exactly as drilling into an input does.
        """
        self._navigate(cell)
        return ActionResult(True)

    def evaluate_slot(self, index: int, sub: int | None = None) -> ActionResult:
        """Run the body of the cell one of the focused cell's slots names.

        Unlike drilling, this never resolves first: evaluation is deliberate,
        so a row nothing has looked at yet is left exactly as unresolved as it
        was, rather than being resolved as a side effect of trying.
        """
        slot = self.focus.slots[index]
        not_an_edge = _NOT_AN_EDGE.get(slot.kind)
        if not_an_edge is not None:
            return ActionResult(False, not_an_edge)
        cells = slot.cells
        if cells is UNRESOLVED:
            return ActionResult(False, _NOT_YET_RESOLVED)
        if not isinstance(cells, tuple) or not cells:
            return ActionResult(False, unresolved_reason(slot))
        if slot.kind is InputKind.MAP_EDGE and sub is None:
            return ActionResult(False, _PICK_AN_ELEMENT)
        cells[sub if sub is not None else 0].evaluate()
        return ActionResult(True)

    def evaluate_output(self, cell: Cell) -> None:
        """Run the body of a cell already known to read the focused one.

        No `ActionResult`, unlike `evaluate_slot`: an output is a cell
        already, the same way `drill_output` needs no resolving-first check,
        so there is no refusal for a caller to act on.
        """
        cell.evaluate()

    def evaluate_focus(self) -> None:
        """Run the focused cell's own body, filling in its value and type.

        No `ActionResult` either, for the same reason: the focus is always a
        cell, never a row that might have nothing behind it.
        """
        self.focus.evaluate()

    def _navigate(self, cell: Cell) -> None:
        self._stack.append(self.focus)
        self.focus = cell
