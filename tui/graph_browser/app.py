"""The terminal application: walking the graph, one cell at a time.

The one module in this package that imports the terminal library. What to
show is `render`'s job and where to go is `navigation`'s; this module wires
key presses to navigation actions and places the result on screen.

Opening the browser runs no body, and neither does moving around in it.
Drilling into an unresolved row resolves it -- the cost `expand_slot` warned
about, and no more -- but a node's own body only ever runs because a reader
pressed one of the evaluate keys, never as a side effect of looking or moving.
"""

from typing import ClassVar

from textual.app import App, ComposeResult
from textual.containers import VerticalScroll
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


class Card(Static):
    """The header card: what the focused cell is, and what it is currently worth.

    `cell` is public rather than the usual private attribute -- `show` is
    nothing but a setter that also asks for a redraw, so there is no
    invariant an accessor would be protecting.
    """

    def __init__(self, cell):
        super().__init__(id="card")
        self.cell = cell

    def show(self, cell):
        """Point the card at a new cell and redraw."""
        self.cell = cell
        self.refresh()

    def render(self):
        pairs = header_card(self.cell)
        width = max(len(label) for label, _ in pairs)
        return "\n".join(
            f"[dim]{label.rjust(width)}[/dim]  {value}" for label, value in pairs
        )


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
        ("q", "quit", "Quit"),
    ]

    def __init__(self, cell):
        super().__init__()
        self.nav = Navigation(cell)
        self.title = "cell browser"
        self.sub_title = str(cell)
        self._input_rows: tuple[InputRow, ...] = ()
        self._output_rows: tuple[OutputRow, ...] = ()

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
        """Enter on a row drills into it -- the table's own key, not ours."""
        if event.data_table.id == "inputs":
            row = self._input_rows[event.cursor_row]
            result = self.nav.drill_slot(row.slot_index, row.sub_index)
        else:
            row = self._output_rows[event.cursor_row]
            result = self.nav.drill_output(row.target)
        self._after(result)

    def action_resolve(self):
        row = self._highlighted_input()
        if row is None:
            return
        self.nav.resolve_slot(row.slot_index)
        self._refresh()

    def action_evaluate_row(self):
        input_row = self._highlighted_input()
        if input_row is not None:
            self._after(
                self.nav.evaluate_slot(input_row.slot_index, input_row.sub_index)
            )
            return
        output_row = self._highlighted_output()
        if output_row is not None:
            self.nav.evaluate_output(output_row.target)
            self._refresh()

    def action_evaluate_focus(self):
        self.nav.evaluate_focus()
        self._refresh()

    def action_navigate_back(self):
        self.nav.back()
        self._refresh()

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

    def _refresh(self):
        cell = self.nav.focus
        self.sub_title = str(cell)
        self.query_one(Card).show(cell)
        self.query_one(Breadcrumb).show(self.nav)
        self._input_rows = input_rows(cell)
        self._output_rows = output_rows(cell)
        self._set_rows("#inputs", INPUT_COLUMNS, self._input_rows)
        self._set_rows("#outputs", OUTPUT_COLUMNS, self._output_rows)

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
