"""The terminal application: one cell, three regions, no navigation yet.

The only module that imports the terminal library. What to show is
`render`'s job and is plain data by the time it arrives here; this module
places it on screen.

Opening the browser runs no body. The header card, the input table and the
output table are all read off what the engine already knows, so a cell that
has never been evaluated opens as readily as one that has -- it just says
`uncomputed` and shows its slots unresolved.
"""

from typing import ClassVar

from textual.app import App, ComposeResult
from textual.containers import VerticalScroll
from textual.widgets import DataTable, Footer, Header, Static

from .render import (
    INPUT_COLUMNS,
    OUTPUT_COLUMNS,
    header_card,
    input_rows,
    output_rows,
)


class Card(Static):
    """The header card: what this cell is, and what it is currently worth."""

    def __init__(self, cell):
        super().__init__(id="card")
        self._cell = cell

    def render(self):
        pairs = header_card(self._cell)
        width = max(len(label) for label, _ in pairs)
        return "\n".join(
            f"[dim]{label.rjust(width)}[/dim]  {value}" for label, value in pairs
        )


class CellBrowser(App):
    """A browser showing one cell of one graph."""

    CSS = """
    #card { padding: 1 2; }
    .heading { padding: 0 2; color: $accent; text-style: bold; }
    DataTable { height: auto; margin: 0 2 1 2; }
    """

    BINDINGS: ClassVar = [("q", "quit", "Quit")]

    def __init__(self, cell):
        super().__init__()
        self.cell = cell
        self.title = "cell browser"
        self.sub_title = str(cell)

    def compose(self) -> ComposeResult:
        yield Header()
        with VerticalScroll():
            yield Card(self.cell)
            yield Static("inputs", classes="heading")
            yield DataTable(id="inputs", cursor_type="row")
            # Not labelled "known outputs": a cell can always be added, so a
            # partial list is the only one there could be.
            yield Static("outputs", classes="heading")
            yield DataTable(id="outputs", cursor_type="row")
        yield Footer()

    def on_mount(self):
        self._fill("#inputs", INPUT_COLUMNS, input_rows(self.cell))
        self._fill("#outputs", OUTPUT_COLUMNS, output_rows(self.cell))

    def _fill(self, selector, columns, rows):
        table = self.query_one(selector, DataTable)
        table.add_columns(*columns)
        for row in rows:
            table.add_row(*(getattr(row, column) for column in columns))
