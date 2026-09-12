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
from tests.helpers import make_book, make_dynamic_node, make_raising

pytest.importorskip("textual", reason="the tui extra is not installed")

from textual.widgets import DataTable, TextArea

from tui.graph_browser import show_node
from tui.graph_browser.app import Card, CellBrowser, TracebackScreen
from tui.graph_browser.render import SOURCE_UNAVAILABLE


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
    press(app, [], check=check)


def press(app, keys, *, row=None, table_id="#inputs", check=None):
    """Run `app` headless, focus a table row, press some keys, and return `app`.

    What each key means to `Navigation` is `test_navigation.py`'s business;
    this only has to show that the binding reaches it. `check`, if given, runs
    against the still-mounted app -- querying its widgets only works before
    the app has torn down.
    """

    async def main():
        async with app.run_test() as pilot:
            await pilot.pause()
            if row is not None:
                table = pilot.app.query_one(table_id, DataTable)
                table.focus()
                table.move_cursor(row=row)
                await pilot.pause()
            for key in keys:
                await pilot.press(key)
            await pilot.pause()
            if check is not None:
                check(app)

    asyncio.run(main())
    return app


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


class TestSourcePanes:
    """Two read-only, Python-highlighted panes: original and compiled."""

    def test_both_panes_mount_and_are_filled(self, book):
        cell = graph.cell(book.pv.key(True))

        def check(app):
            original = app.query_one("#original", TextArea)
            compiled = app.query_one("#compiled", TextArea)
            assert original.language == "python"
            assert original.read_only is True
            assert "def pv(self, hedged):" in original.text
            assert compiled.language == "python"
            assert compiled.read_only is True
            assert compiled.text == graph.code(cell.node)

        drive(CellBrowser(cell), check)

    def test_a_cell_with_no_original_source_shows_the_placeholder_in_that_pane_only(
        self,
    ):
        Dynamic = make_dynamic_node()
        cell = graph.cell(Dynamic().value.key())

        def check(app):
            assert app.query_one("#original", TextArea).text == SOURCE_UNAVAILABLE
            assert app.query_one("#compiled", TextArea).text != SOURCE_UNAVAILABLE

        drive(CellBrowser(cell), check)

    def test_drilling_into_a_different_cell_refreshes_both_panes(self):
        book, _ = make_book()
        cell = graph.cell(book.total.key(True))

        def check(app):
            assert "def rate(self):" in app.query_one("#original", TextArea).text
            assert app.query_one("#compiled", TextArea).text == graph.code(book.rate)

        press(CellBrowser(cell), ["enter"], row=1, check=check)  # rate(): one cell

    def test_navigating_back_refreshes_both_panes_too(self):
        book, _ = make_book()
        cell = graph.cell(book.total.key(True))

        def check(app):
            original = app.query_one("#original", TextArea).text
            assert "def total(self, live):" in original

        press(CellBrowser(cell), ["enter", "backspace"], row=1, check=check)


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


class TestKeyBindingsReachNavigation:
    """What each key does is `test_navigation.py`'s business -- only that the
    binding reaches `Navigation`, and that the tables reflect it, is checked
    here."""

    def test_enter_drills_into_the_highlighted_input_row(self):
        book, _ = make_book()
        cell = graph.cell(book.total.key(True))

        app = press(CellBrowser(cell), ["enter"], row=1)  # rate(): one cell

        assert app.nav.depth == 1
        assert app.nav.focus == book.rate.key()

    def test_backspace_goes_back(self):
        book, _ = make_book()
        cell = graph.cell(book.total.key(True))

        app = press(CellBrowser(cell), ["enter", "backspace"], row=1)

        assert app.nav.depth == 0
        assert app.nav.focus == cell

    def test_r_resolves_a_row_without_moving_the_focus(self):
        book, _ = make_book()
        cell = graph.cell(book.total.key(True))
        assert cell.slots[4].cells is graph.UNRESOLVED

        app = press(CellBrowser(cell), ["r"], row=4)  # the map edge

        assert app.nav.depth == 0
        assert app.nav.focus == cell
        assert cell.slots[4].cells is not graph.UNRESOLVED

    def test_e_evaluates_the_highlighted_rows_cell(self):
        book, _ = make_book()
        cell = graph.cell(book.total.key(True))

        app = press(CellBrowser(cell), ["e"], row=1)  # rate()

        assert graph.cell(book.rate.key()).value.state is graph.ValueState.CLEAN
        assert app.nav.depth == 0

    def test_evaluating_a_row_keeps_the_cursor_on_it(self):
        """Repopulating the table must not scroll the reader back to row zero."""
        book, _ = make_book()
        cell = graph.cell(book.total.key(True))
        seen = {}

        def check(app):
            seen["cursor_row"] = app.query_one("#inputs", DataTable).cursor_row

        press(CellBrowser(cell), ["e"], row=1, check=check)  # rate()

        assert seen["cursor_row"] == 1

    def test_resolving_a_map_edge_keeps_the_cursor_at_the_same_row_index(self):
        """A row exploding into several after resolving is not a reason to
        scroll the reader back to the top of the table."""
        book, _ = make_book()
        cell = graph.cell(book.total.key(True))
        seen = {}

        def check(app):
            seen["cursor_row"] = app.query_one("#inputs", DataTable).cursor_row

        press(CellBrowser(cell), ["r"], row=4, check=check)  # the map edge

        assert seen["cursor_row"] == 4

    def test_capital_e_evaluates_the_focused_cell(self):
        book, _ = make_book()
        cell = graph.cell(book.total.key(True))

        app = press(CellBrowser(cell), ["E"])

        assert app.nav.focus.value.state is graph.ValueState.CLEAN

    def test_the_tables_repopulate_from_the_new_focus_after_drilling(self):
        book, _ = make_book()
        cell = graph.cell(book.total.key(True))
        seen = {}

        def check(app):
            seen["row_count"] = app.query_one("#inputs", DataTable).row_count
            seen["sub_title"] = app.sub_title

        press(CellBrowser(cell), ["enter"], row=1, check=check)  # -> rate()

        rate_cell = graph.cell(book.rate.key())
        assert seen["row_count"] == len(rate_cell.slots)
        assert seen["sub_title"] == str(rate_cell)


class TestAThrowingCellDoesNotEjectYouFromTheBrowser:
    """A raising body, guard, or receiver is reported, not unwound into."""

    def test_evaluating_the_focus_reports_the_error_without_crashing(self):
        Boom, _, _ = make_raising()
        cell = graph.cell(Boom().broken.key())

        app = press(CellBrowser(cell), ["E"])

        assert app.nav.focus == cell
        assert app.nav.depth == 0
        assert cell.value.state is graph.ValueState.UNCOMPUTED
        assert app._traceback is not None
        assert "ValueError: boom" in app._traceback

    def test_the_status_bar_names_the_exception_type_and_message(self):
        Boom, _, _ = make_raising()
        cell = graph.cell(Boom().broken.key())

        app = press(CellBrowser(cell), ["E"])

        messages = [notification.message for notification in app._notifications]
        assert "ValueError: boom" in messages

    def test_the_header_card_is_marked_and_stays_marked(self):
        Boom, _, _ = make_raising()
        cell = graph.cell(Boom().broken.key())
        seen = {}

        def check(app):
            seen["errored"] = app.query_one(Card).errored

        press(CellBrowser(cell), ["E"], check=check)

        assert seen["errored"] is True

    def test_a_key_shows_the_full_traceback(self):
        Boom, _, _ = make_raising()
        cell = graph.cell(Boom().broken.key())
        seen = {}

        def check(app):
            seen["screen"] = app.screen

        press(CellBrowser(cell), ["E", "t"], check=check)

        assert isinstance(seen["screen"], TracebackScreen)
        assert "ValueError: boom" in seen["screen"]._text

    def test_pressing_the_traceback_key_before_any_error_does_not_crash(self):
        Boom, _, _ = make_raising()
        cell = graph.cell(Boom().broken.key())

        app = press(CellBrowser(cell), ["t"])

        assert app.nav.focus == cell

    def test_a_raising_guard_is_caught_during_resolution(self):
        """Not just a raising body -- a guard evaluated while resolving is
        covered the same way."""
        _, _, Guarded = make_raising()
        cell = graph.cell(Guarded().maybe.key())

        app = press(CellBrowser(cell), ["r"], row=1)  # dep(), guarded by check()

        assert app.nav.focus == cell
        assert app.nav.depth == 0
        assert app._traceback is not None
        assert "RuntimeError: guard boom" in app._traceback

    def test_a_rejected_comprehension_is_caught_during_resolution(self):
        """A map edge naming cells for some elements and plain values for
        others is rejected by the engine itself -- also caught, not unwound
        into."""
        _, Bad, _ = make_raising()
        cell = graph.cell(Bad().total.key())

        app = press(CellBrowser(cell), ["r"], row=1)  # the map edge over pv()

        assert app.nav.focus == cell
        assert app.nav.depth == 0
        assert app._traceback is not None
        assert "is not a node" in app._traceback

    def test_the_raising_row_is_marked_in_the_input_table(self):
        _, _, Guarded = make_raising()
        cell = graph.cell(Guarded().maybe.key())
        seen = {}

        def check(app):
            table = app.query_one("#inputs", DataTable)
            seen["value"] = table.get_cell_at((1, 3))  # slot 1's value column

        press(CellBrowser(cell), ["r"], row=1, check=check)

        assert "⚠" in str(seen["value"])

    def test_the_mark_survives_a_later_action_that_still_does_not_fix_it(self):
        """An `ActionResult` that comes back `ok=False` without raising --
        the row is still unresolved, say -- has not fixed anything, so it
        must not silently clear a mark an earlier exception left behind."""
        _, _, Guarded = make_raising()
        cell = graph.cell(Guarded().maybe.key())
        seen = {}

        def check(app):
            table = app.query_one("#inputs", DataTable)
            seen["value"] = table.get_cell_at((1, 3))  # slot 1's value column

        # "r" raises (the guard); "e" on the still-unresolved row fails with
        # an ActionResult rather than raising, and must not clear the mark.
        press(CellBrowser(cell), ["r", "e"], row=1, check=check)

        assert "⚠" in str(seen["value"])

    def test_navigation_still_works_after_an_error(self):
        """A row raising during resolution does not stop other rows of the
        same cell from being navigated normally afterwards."""
        _, _, Guarded = make_raising()
        guarded = Guarded()
        cell = graph.cell(guarded.maybe.key())

        app = press(
            CellBrowser(cell), ["r", "up", "enter"], row=1
        )  # raise on row 1, then drill row 0

        assert app.nav.depth == 1
        assert app.nav.focus == guarded.check.key()
