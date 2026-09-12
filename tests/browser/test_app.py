"""The terminal application itself, driven headless.

Only what needs a terminal to be sure of: that the three regions mount, that
the tables are filled from `render`, and that opening the browser runs no
body. What is *in* each row is `test_render`'s business.

Skipped where the optional extra is not installed, which is the point of it
being optional.
"""

import asyncio

import pytest

import graph
import ns
from graph import node
from ns import McObject

pytest.importorskip("textual", reason="the tui extra is not installed")

from textual.widgets import DataTable

from browser import show_node
from browser.app import CellBrowser


@pytest.fixture
def book():
    class Leg(McObject):
        @node(node.Stored)
        def size(self):
            return 2.0

        @node
        def pv(self):
            return self.size() * 50.0

    class Book(McObject):
        @node(node.Stored)
        def leg_paths(self):
            return []

        @node
        def pv(self, hedged):
            floor = 0.0
            legs = [self.ns[path].pv() for path in self.leg_paths()]
            return sum(legs, floor)

    path = ns.lookup_or_new("/inst/EQ/Option/ACME-C1", Leg, size=2.0).name
    return ns.lookup_or_new("/book/EQD/exotics/london", Book, leg_paths=[path])


def drive(app, check):
    """Run `check` against a mounted app, headless."""

    async def main():
        async with app.run_test() as pilot:
            await pilot.pause()
            check(app)

    asyncio.run(main())


class TestTheApp:
    def test_both_tables_mount_and_are_filled(self, book):
        cell = graph.cell(book.pv.key(True))
        ns.DEFAULT["/inst/EQ/Option/ACME-C1"].pv()

        def check(app):
            inputs = app.query_one("#inputs", DataTable)
            outputs = app.query_one("#outputs", DataTable)
            assert [str(column.label) for column in inputs.columns.values()] == [
                "slot",
                "kind",
                "identity",
                "value",
                "guard",
                "reads",
            ]
            assert inputs.row_count == len(cell.slots)
            assert [str(column.label) for column in outputs.columns.values()] == [
                "cell",
                "value",
            ]

        drive(CellBrowser(cell), check)

    def test_opening_the_browser_runs_no_body(self, book):
        cell = graph.cell(book.pv.key(True))

        drive(CellBrowser(cell), lambda app: None)

        assert graph.cell(book.pv.key(True)).value.state is graph.ValueState.UNCOMPUTED
        assert ns.DEFAULT["/inst/EQ/Option/ACME-C1"].pv.is_dirty() is False
        assert graph.cell(book.pv.key(True)).expanded is False

    def test_the_subtitle_names_the_cell(self, book):
        app = CellBrowser(graph.cell(book.pv.key(True)))

        assert app.sub_title == "Book.pv(True)"


class TestShowNode:
    """The entry point takes a bound node, its arguments, and a graph."""

    def test_it_needs_a_bound_node(self, book):
        with pytest.raises(TypeError, match="bound node"):
            show_node(type(book).pv, True)

    def test_it_accepts_an_explicit_graph(self, book):
        """Built into the cell rather than reaching for the default graph, so a
        test can hand in an isolated one."""
        isolated = graph.Graph()
        shown = []

        def check(app):
            shown.append(app.cell)

        app = CellBrowser(graph.Cell(book.pv.key(True), isolated))
        drive(app, check)

        assert shown[0].graph is isolated
