"""The terminal application: walking the graph, one cell at a time.

The one module in this package that imports the terminal library. What to
show is `render`'s job and where to go is `navigation`'s; this module wires
key presses to navigation actions and places the result on screen.

Opening the browser runs no body, and neither does moving around in it.
Drilling into an unresolved row resolves it -- the cost `expand_slot` warned
about, and no more -- but a node's own body only ever runs because a reader
pressed one of the evaluate keys, never as a side effect of looking or moving.
"""

import traceback
from dataclasses import dataclass, replace
from typing import ClassVar

from textual.app import App, ComposeResult
from textual.containers import VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import DataTable, Footer, Header, Static

from .navigation import Navigation
from .render import (
    INPUT_COLUMNS,
    OUTPUT_COLUMNS,
    InputRow,
    OutputRow,
    cell_label,
    header_card,
    input_rows,
    output_rows,
)

#: What marks a row or the header card as the site of a caught exception.
_ERROR_MARK = "⚠"


@dataclass(frozen=True)
class _Marker:
    """Where in the browser an exception was caught.

    `focus` is the key of the cell that was on screen when the action was
    tried -- scoped to it, rather than kept flat, because two different cells
    can share a slot index and a mark left on one must never bleed onto the
    other. `site` says which part of the display to mark: an input row, an
    output row, or the header card, distinguished from a plain tuple so a
    caller cannot mismatch `slot_index` and `target` between the two kinds of
    row by getting the arity wrong.
    """

    focus: tuple
    site: str
    slot_index: int | None = None
    sub_index: int | None = None
    target: tuple | None = None


class Card(Static):
    """The header card: what the focused cell is, and what it is currently worth.

    `cell` is public rather than the usual private attribute -- `show` is
    nothing but a setter that also asks for a redraw, so there is no
    invariant an accessor would be protecting.
    """

    def __init__(self, cell):
        super().__init__(id="card")
        self.cell = cell
        self.errored = False

    def show(self, cell, *, errored=False):
        """Point the card at a new cell and redraw."""
        self.cell = cell
        self.errored = errored
        self.refresh()

    def render(self):
        pairs = header_card(self.cell)
        width = max(len(label) for label, _ in pairs)
        lines = [f"[dim]{label.rjust(width)}[/dim]  {value}" for label, value in pairs]
        if self.errored:
            lines.append(
                f"[bold red]{_ERROR_MARK} evaluating this cell raised -- "
                "press t for the traceback[/bold red]"
            )
        return "\n".join(lines)


class TracebackScreen(ModalScreen):
    """The full traceback behind the last caught exception.

    Its own screen rather than a wider notification, so the status line can
    stay one line long without hiding the detail entirely -- it is a key
    press away instead. Dismissed by any key, since there is nothing on it to
    interact with.
    """

    CSS = """
    TracebackScreen {
        align: center middle;
    }
    #traceback {
        width: 90%;
        height: 90%;
        border: round $error;
        padding: 1 2;
        background: $surface;
        overflow-y: auto;
    }
    """

    def __init__(self, text: str):
        super().__init__()
        self._text = text

    def compose(self) -> ComposeResult:
        yield Static(self._text, id="traceback")

    def on_key(self, event) -> None:
        self.dismiss()


class Breadcrumb(Static):
    """The path taken to the focused cell, and how deep it runs.

    Read straight off `Navigation` rather than kept in step by hand, so it can
    never disagree with the focus it describes.
    """

    def show(self, nav: Navigation):
        """Redraw for the given navigation state."""
        crumbs = " > ".join(cell_label(cell) for cell in nav.breadcrumb)
        self.update(f"depth {nav.depth}  {crumbs}")


class CellBrowser(App):
    """A browser for one graph, walked one cell at a time."""

    CSS = """
    #card { padding: 1 2; }
    #breadcrumb { padding: 0 2; color: $text-muted; }
    .heading { padding: 0 2; color: $accent; text-style: bold; }
    DataTable { height: auto; margin: 0 2 1 2; }
    """

    BINDINGS: ClassVar = [
        ("r", "resolve", "Resolve"),
        ("e", "evaluate_row", "Evaluate row"),
        ("E", "evaluate_focus", "Evaluate cell"),
        ("backspace", "navigate_back", "Back"),
        ("t", "show_traceback", "Traceback"),
        ("q", "quit", "Quit"),
    ]

    def __init__(self, cell):
        super().__init__()
        self.nav = Navigation(cell)
        self.title = "cell browser"
        self.sub_title = str(cell)
        self._input_rows: tuple[InputRow, ...] = ()
        self._output_rows: tuple[OutputRow, ...] = ()
        #: `_Marker` -> message, for whichever row or cell a caught exception
        #: marked. Scoped to the cell that was focused when the action was
        #: tried, so revisiting it later still shows the mark.
        self._errors: dict[_Marker, str] = {}
        #: The full traceback behind the most recently caught exception.
        self._traceback: str | None = None

    @property
    def cell(self):
        """The cell currently focused."""
        return self.nav.focus

    def compose(self) -> ComposeResult:
        yield Header()
        with VerticalScroll():
            yield Card(self.nav.focus)
            yield Breadcrumb(id="breadcrumb")
            yield Static("inputs", classes="heading")
            yield DataTable(id="inputs", cursor_type="row")
            # Not labelled "known outputs": a cell can always be added, so a
            # partial list is the only one there could be.
            yield Static("outputs", classes="heading")
            yield DataTable(id="outputs", cursor_type="row")
        yield Footer()

    def on_mount(self):
        self.query_one("#inputs", DataTable).add_columns(*INPUT_COLUMNS)
        self.query_one("#outputs", DataTable).add_columns(*OUTPUT_COLUMNS)
        self._refresh()

    def on_data_table_row_selected(self, event):
        """Enter on a row drills into it -- the table's own key, not ours.

        Resolution can raise -- a guard or receiver expression that does, or
        a comprehension the engine rejects for mixing cells and plain values
        -- so this goes through `_attempt` exactly as an evaluate action does.
        """
        if event.data_table.id == "inputs":
            row = self._input_rows[event.cursor_row]
            ok, result = self._attempt(
                self._input_marker(row),
                lambda: self.nav.drill_slot(row.slot_index, row.sub_index),
            )
        else:
            row = self._output_rows[event.cursor_row]
            ok, result = self._attempt(
                self._output_marker(row), lambda: self.nav.drill_output(row.target)
            )
        if ok:
            self._after(result)

    def action_resolve(self):
        row = self._highlighted_input()
        if row is None:
            return
        ok, _ = self._attempt(
            self._input_marker(row), lambda: self.nav.resolve_slot(row.slot_index)
        )
        if ok:
            self._refresh()

    def action_evaluate_row(self):
        input_row = self._highlighted_input()
        if input_row is not None:
            ok, result = self._attempt(
                self._input_marker(input_row),
                lambda: self.nav.evaluate_slot(
                    input_row.slot_index, input_row.sub_index
                ),
            )
            if ok:
                self._after(result)
            return
        output_row = self._highlighted_output()
        if output_row is not None:
            ok, _ = self._attempt(
                self._output_marker(output_row),
                lambda: self.nav.evaluate_output(output_row.target),
            )
            if ok:
                self._refresh()

    def action_evaluate_focus(self):
        ok, _ = self._attempt(self._focus_marker(), self.nav.evaluate_focus)
        if ok:
            self._refresh()

    def action_navigate_back(self):
        self.nav.back()
        self._refresh()

    def action_show_traceback(self):
        """Show the full traceback behind the last caught exception.

        The raw Python traceback, mostly internal engine frames in
        input-resolution order rather than anything the reader wrote --
        `GEN-39` will give it a graph path instead, but until then this is
        what there is, and it stays a key press away rather than crowding the
        status line.
        """
        if self._traceback is None:
            self.notify("nothing has raised yet", severity="information")
            return
        self.push_screen(TracebackScreen(self._traceback))

    def _highlighted_input(self) -> InputRow | None:
        """The input row the cursor is on, or `None` if that isn't where it is."""
        return self._highlighted("inputs", self._input_rows)

    def _highlighted_output(self) -> OutputRow | None:
        """The output row the cursor is on, or `None` if that isn't where it is."""
        return self._highlighted("outputs", self._output_rows)

    def _highlighted(self, table_id, rows):
        """The row of `rows` the cursor is on, if the focused table is `table_id`."""
        table = self.focused
        if not isinstance(table, DataTable) or table.id != table_id:
            return None
        if table.cursor_row is None or table.cursor_row >= len(rows):
            return None
        return rows[table.cursor_row]

    def _after(self, result):
        """Redraw on success; otherwise tell the reader why nothing moved."""
        if result.ok:
            self._refresh()
        else:
            self.notify(result.reason, severity="warning")

    def _input_marker(self, row: InputRow) -> _Marker:
        """The `_errors` key for an input row of the cell currently focused."""
        return _Marker(self.nav.focus.key, "input", row.slot_index, row.sub_index)

    def _output_marker(self, row: OutputRow) -> _Marker:
        """The `_errors` key for an output row of the cell currently focused."""
        return _Marker(self.nav.focus.key, "output", target=row.target.key)

    def _focus_marker(self) -> _Marker:
        """The `_errors` key for the cell currently focused, itself."""
        return _Marker(self.nav.focus.key, "focus")

    def _attempt(self, marker, fn):
        """Run `fn`, catching whatever a raising body, guard or receiver throws.

        A cell that raises is the whole reason a reader reaches for this
        browser; letting the exception through would unwind the session and
        take the reader's place in the tree with it. Caught here instead: the
        row or cell responsible is marked, the type and message go out as a
        transient notification, and the full traceback is kept for `t` to
        show, so nothing is lost even once the notification fades.

        Returns `(True, fn()'s result)` on success, clearing any mark
        `marker` carried from an earlier attempt -- but only once something
        has actually been resolved or evaluated there: an `ActionResult`
        that came back `ok=False` (a row not yet resolved, say) fixed
        nothing, and must not scrub a mark left by an earlier exception.
        Returns `(False, None)` if `fn` raised.
        """
        try:
            result = fn()
        except Exception as exc:  # noqa: BLE001 -- the boundary itself
            message = f"{type(exc).__name__}: {exc}"
            self._errors[marker] = message
            self._traceback = traceback.format_exc()
            self.notify(message, severity="error")
            # Redrawn here, not left to the caller: a caller only refreshes
            # after success, but the mark just recorded has to reach the
            # table even though nothing else about the screen has moved.
            self._refresh()
            return False, None
        if getattr(result, "ok", True):
            self._errors.pop(marker, None)
        return True, result

    def _refresh(self):
        cell = self.nav.focus
        self.sub_title = str(cell)
        self.query_one(Card).show(cell, errored=self._focus_marker() in self._errors)
        self.query_one(Breadcrumb).show(self.nav)
        self._input_rows = self._marked(input_rows(cell), self._input_marker)
        self._output_rows = self._marked(output_rows(cell), self._output_marker)
        self._set_rows("#inputs", INPUT_COLUMNS, self._input_rows)
        self._set_rows("#outputs", OUTPUT_COLUMNS, self._output_rows)

    def _marked(self, rows, marker_of):
        """Flag whichever of `rows` last raised, input or output alike.

        `marker_of` is `_input_marker` or `_output_marker` -- the one
        difference between marking the two tables, so this is the only place
        that difference has to be spelled out.
        """
        return tuple(
            replace(row, value=f"{_ERROR_MARK} {row.value}")
            if marker_of(row) in self._errors
            else row
            for row in rows
        )

    def _set_rows(self, selector, columns, rows):
        """Repopulate a table, keeping the cursor where the reader left it.

        `clear` resets the cursor to the top row -- fine when the focus has
        actually moved, but resolving or evaluating a row leaves the reader
        looking at the same cell, and a row exploding into several (a map
        edge, once resolved) should not scroll them back to row zero.
        """
        table = self.query_one(selector, DataTable)
        cursor_row = table.cursor_row
        table.clear()
        for row in rows:
            table.add_row(*(getattr(row, column) for column in columns))
        if rows:
            table.move_cursor(row=min(cursor_row, len(rows) - 1))
