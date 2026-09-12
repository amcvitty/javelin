"""What one cell looks like on screen.

Every test here goes through `tui.graph_browser.render`, which the terminal
library knows nothing about: what is shown can be checked without a terminal, and the
rendering logic is the part worth checking.

The recurring question is whether the display keeps apart what the engine
keeps apart -- a slot nothing has looked at from one that looked and found
nothing, a stale value from a current one.
"""

import pytest

import graph
import ns
from graph import node
from ns import McObject
from tests.helpers import make_dynamic_node
from tui.graph_browser import render


def make_market():
    class Market(McObject):
        @node(node.Stored)
        def spot(self):
            return 100.0

    return Market


def make_book():
    """A book whose `pv` has one input of every kind the table can draw."""
    Market = make_market()

    class Leg(McObject):
        @node(node.Stored)
        def market_path(self):
            return "/mkt/EQ/ACME/Market"

        @node(node.Stored)
        def size(self):
            return 1.0

        @node
        def market(self):
            return self.ns[self.market_path()]

        @node
        def pv(self):
            return self.size() * self.market().spot()

    class Book(McObject):
        @node(node.Stored)
        def leg_paths(self):
            return []

        @node
        def hedge(self):
            return -1.0

        @node
        def pv(self, hedged):
            floor = 0.0
            legs = [self.ns[path].pv() for path in self.leg_paths()]
            return sum(legs, floor) + (self.hedge() if hedged else floor)

    return Market, Leg, Book


@pytest.fixture
def book():
    """A two-leg book, nothing evaluated yet."""
    Market, Leg, Book = make_book()
    ns.lookup_or_new("/mkt/EQ/ACME/Market", Market, spot=100.0)
    paths = [
        ns.lookup_or_new(f"/inst/EQ/Option/ACME-C{n}", Leg, size=float(n)).name
        for n in (1, 2)
    ]
    return ns.lookup_or_new("/book/EQD/exotics/london", Book, leg_paths=paths)


def rows_by_slot(cell, **kwargs):
    """The input rows, keyed by the slot index they show."""
    return {row.slot: row for row in render.input_rows(cell, **kwargs)}


class TestTruncation:
    """Long namespace paths lose their heads, not their tails."""

    def test_a_short_identity_is_left_alone(self):
        assert render.truncate_left("/mkt/EQ/ACME/Market.spot()", 44) == (
            "/mkt/EQ/ACME/Market.spot()"
        )

    def test_a_long_identity_keeps_its_tail(self):
        long = "/mkt/EQ/SOMEVERYLONGUNDERLYINGNAME/Market.spot()"

        shown = render.truncate_left(long, 20)

        assert len(shown) == 20
        assert shown.endswith("Market.spot()")
        assert shown.startswith("...")

    def test_two_markets_on_different_underlyings_stay_distinguishable(self):
        """The discriminating part of a path is at the end of it."""
        a = "/mkt/EQ/AAAAAAAAAAAAAAAAAAAA/ACME/Market.spot()"
        b = "/mkt/EQ/AAAAAAAAAAAAAAAAAAAA/WIDGET/Market.spot()"

        assert render.truncate_left(a, 24) != render.truncate_left(b, 24)

    def test_source_text_keeps_its_head_instead(self):
        """A local is named by what comes first, so it is cut the other way."""
        shown = render.truncate_right("legs = [self.ns[p].pv() for p in paths]", 16)

        assert len(shown) == 16
        assert shown.startswith("legs = ")
        assert shown.endswith("...")


class TestValues:
    """A value is shortened; the state that qualifies it never is."""

    def test_a_long_value_is_shortened(self):
        long = graph.CellValue(graph.ValueState.CLEAN, ["/inst/EQ/Option/ACME"] * 10)

        shown = render.value_text(long, width=20)

        assert len(shown) == 20
        assert shown.endswith("...")

    def test_shortening_a_value_keeps_its_state(self):
        """Truncating `CellValue`'s own text would drop `(dirty)` off the end
        of it, and a stale value would read as a current one."""
        stale = graph.CellValue(graph.ValueState.DIRTY, ["/inst/EQ/Option/ACME"] * 10)

        shown = render.value_text(stale, width=20)

        assert shown.endswith("(dirty)")

    def test_an_uncomputed_value_says_so_rather_than_showing_none(self):
        assert render.value_text(graph.CellValue(graph.ValueState.UNCOMPUTED)) == (
            "uncomputed"
        )


class TestHeaderCard:
    """Cell, object, class, method, arguments, value, type."""

    def test_the_card_names_the_cell_by_object_method_and_arguments(self, book):
        card = dict(render.header_card(graph.cell(book.pv.key(True))))

        assert card["cell"] == "/book/EQD/exotics/london.pv(True)"
        assert card["object"] == "/book/EQD/exotics/london"
        assert card["class"] == "Book"
        assert card["method"] == "pv"
        assert card["arguments"] == "True"

    def test_the_card_has_every_field(self, book):
        labels = [
            label for label, _ in render.header_card(graph.cell(book.pv.key(True)))
        ]

        assert labels == [
            "cell",
            "object",
            "class",
            "method",
            "arguments",
            "value",
            "type",
        ]

    def test_an_object_with_no_name_is_shown_by_its_class(self):
        """Never by its repr: a memory address tells a reader nothing."""

        class Sheet:
            @node
            def a(self):
                return 1

        card = dict(render.header_card(graph.cell(Sheet().a.key())))

        assert card["object"] == "Sheet"
        assert "0x" not in card["cell"]

    def test_an_uncomputed_cell_has_no_type(self, book):
        card = dict(render.header_card(graph.cell(book.pv.key(True))))

        assert card["value"] == "uncomputed"
        assert card["type"] == ""

    def test_the_four_value_states_render_distinguishably(self, book):
        leg = ns.DEFAULT["/inst/EQ/Option/ACME-C1"]
        shown = {}

        shown["uncomputed"] = dict(render.header_card(graph.cell(leg.pv.key())))
        leg.pv()
        shown["clean"] = dict(render.header_card(graph.cell(leg.pv.key())))
        ns.DEFAULT["/mkt/EQ/ACME/Market"].spot.set_value(110.0)
        shown["dirty"] = dict(render.header_card(graph.cell(leg.pv.key())))
        leg.pv.set_value(1.0)
        shown["overridden"] = dict(render.header_card(graph.cell(leg.pv.key())))

        values = [card["value"] for card in shown.values()]
        assert len(set(values)) == 4
        assert shown["uncomputed"]["value"] == "uncomputed"
        assert "dirty" in shown["dirty"]["value"]
        assert "overridden" in shown["overridden"]["value"]
        assert shown["clean"]["value"] == "100.0"
        assert shown["clean"]["type"] == "float"


class TestInputTable:
    """One table, every slot, in `ivs` order."""

    def test_every_slot_appears_in_slot_order_with_no_gaps(self, book):
        cell = graph.cell(book.pv.key(True))

        rows = render.input_rows(cell)

        assert [row.slot for row in rows] == [str(slot.index) for slot in cell.slots]

    def test_a_row_has_all_six_columns(self, book):
        row = render.input_rows(graph.cell(book.pv.key(True)))[0]

        assert render.INPUT_COLUMNS == (
            "slot",
            "kind",
            "identity",
            "value",
            "guard",
            "reads",
        )
        for column in render.INPUT_COLUMNS:
            assert hasattr(row, column)

    def test_a_terminal_shows_its_name_and_the_value_from_the_key(self, book):
        cell = graph.cell(book.pv.key(True))

        terminal = next(
            row for row in render.input_rows(cell) if row.kind == "terminal"
        )

        assert terminal.identity == "hedged"
        assert terminal.value == "True"

    def test_a_hoisted_local_shows_its_assignment(self, book):
        cell = graph.cell(book.pv.key(True))

        local = next(
            row for row in render.input_rows(cell) if row.kind == "hoisted local"
        )

        assert local.identity == "floor = 0.0"

    def test_a_guard_is_shown_in_its_own_column(self, book):
        cell = graph.cell(book.pv.key(True))

        guarded = [row for row in render.input_rows(cell) if row.guard]

        assert guarded
        assert all("if" not in row.identity for row in guarded)
        assert any(row.guard == "hedged" for row in guarded)

    def test_read_sets_are_shown_as_slot_indices(self, book):
        cell = graph.cell(book.pv.key(True))
        rows = rows_by_slot(cell)

        map_row = next(row for row in rows.values() if row.kind == "map edge")

        assert map_row.reads
        assert all(part.strip().isdigit() for part in map_row.reads.split(","))


class TestSameObjectIdentity:
    """A row naming a cell on the object already on screen says `self`, not
    its path -- the path is what a reader is already looking at."""

    def test_a_same_object_edge_is_named_self(self, book):
        cell = graph.cell(book.pv.key(True))
        index = next(slot.index for slot in cell.slots if slot.target == "hedge")

        cell.expand_slot(index)

        row = rows_by_slot(cell)[str(index)]
        assert row.identity == "self.hedge()"

    def test_a_cross_object_edge_still_shows_the_full_path(self, book):
        """The map edge's legs are on a different object -- the one case this
        rule must not touch, or two objects would look like one."""
        cell = graph.cell(book.pv.key(True))
        index = next(slot.index for slot in cell.slots if str(slot.kind) == "map edge")

        cell.expand_slot(index)

        rows = [
            row for row in render.input_rows(cell) if row.slot.startswith(f"{index}.")
        ]
        assert rows[0].identity.endswith("ACME-C1.pv()")
        assert not rows[0].identity.startswith("self.")

    def test_an_output_on_the_same_object_is_named_self(self, book):
        cell = graph.cell(book.pv.key(True))
        index = next(slot.index for slot in cell.slots if slot.target == "hedge")
        cell.expand_slot(index)  # book.pv reads book.hedge, once resolved

        outputs = render.output_rows(graph.cell(book.hedge.key()))

        assert any(row.cell == "self.pv(True)" for row in outputs)


class TestResolution:
    """An unresolved slot says the call it would make; a resolved one says
    which cell it named."""

    def test_an_unresolved_edge_is_named_by_the_method_it_calls(self, book):
        """There is no cell to name it after yet, and a map edge's call site is
        a whole comprehension -- the target method is what stays legible."""
        cell = graph.cell(book.pv.key(True))

        map_row = next(row for row in render.input_rows(cell) if row.kind == "map edge")

        assert map_row.value == "not yet resolved"
        assert map_row.identity == "pv()"

    def test_a_resolved_edge_sharpens_into_the_full_cell_identity(self, book):
        cell = graph.cell(book.pv.key(True))
        index = next(slot.index for slot in cell.slots if str(slot.kind) == "map edge")

        cell.expand_slot(index)

        rows = [
            row for row in render.input_rows(cell) if row.slot.startswith(f"{index}.")
        ]
        assert rows
        assert rows[0].identity.endswith("ACME-C1.pv()")
        assert rows[0].value == "uncomputed"

    def test_a_blocked_call_site_is_not_shown_as_unresolved(self, book):
        """The guard is false, so the call site names no cells at all -- a
        different answer from nobody having looked."""
        cell = graph.cell(book.pv.key(False))
        index = next(slot.index for slot in cell.slots if slot.guard_source)

        assert cell.expand_slot(index) == ()

        row = rows_by_slot(cell)[str(index)]
        assert row.value == "not reached"
        assert row.value != "not yet resolved"

    def test_an_empty_map_edge_says_so(self):
        *_, Book = make_book()
        book = ns.lookup_or_new("/book/EQD/exotics/empty", Book, leg_paths=[])
        cell = graph.cell(book.pv.key(True))
        index = next(slot.index for slot in cell.slots if str(slot.kind) == "map edge")

        cell.expand_slot(index)

        assert rows_by_slot(cell)[str(index)].value == "no elements"


class TestMapFanOut:
    """A map edge is one row unresolved and one row per element after."""

    def test_each_element_gets_a_sub_indexed_row(self, book):
        cell = graph.cell(book.pv.key(True))
        index = next(slot.index for slot in cell.slots if str(slot.kind) == "map edge")
        cell.expand_slot(index)

        slots = [row.slot for row in render.input_rows(cell)]

        assert f"{index}.0" in slots
        assert f"{index}.1" in slots

    def test_the_remainder_is_capped_with_a_count(self):
        Market, Leg, Book = make_book()
        ns.lookup_or_new("/mkt/EQ/ACME/Market", Market, spot=100.0)
        paths = [
            ns.lookup_or_new(f"/inst/EQ/Option/ACME-{n}", Leg, size=1.0).name
            for n in range(10)
        ]
        book = ns.lookup_or_new("/book/EQD/exotics/big", Book, leg_paths=paths)
        cell = graph.cell(book.pv.key(True))
        index = next(slot.index for slot in cell.slots if str(slot.kind) == "map edge")
        cell.expand_slot(index)

        rows = [
            row
            for row in render.input_rows(cell, cap=3)
            if row.slot.startswith(f"{index}.")
        ]

        assert len(rows) == 4
        assert rows[-1].identity == "... 7 more"

    def test_an_exact_fit_has_no_remainder_row(self, book):
        cell = graph.cell(book.pv.key(True))
        index = next(slot.index for slot in cell.slots if str(slot.kind) == "map edge")
        cell.expand_slot(index)

        rows = [
            row
            for row in render.input_rows(cell, cap=2)
            if row.slot.startswith(f"{index}.")
        ]

        assert len(rows) == 2
        assert "more" not in rows[-1].identity


class TestOutputTable:
    """Its own schema: an output is a cell, not a slot."""

    def test_the_output_schema_has_no_kind_guard_or_read_set(self):
        assert render.OUTPUT_COLUMNS == ("cell", "value")

    def test_the_cells_that_read_this_one_are_listed(self, book):
        market = ns.DEFAULT["/mkt/EQ/ACME/Market"]
        leg = ns.DEFAULT["/inst/EQ/Option/ACME-C1"]
        leg.pv()

        rows = render.output_rows(graph.cell(market.spot.key()))

        assert [row.cell for row in rows] == ["/inst/EQ/Option/ACME-C1.pv()"]
        assert rows[0].value == "100.0"

    def test_a_cell_nothing_has_looked_at_has_no_outputs(self, book):
        assert render.output_rows(graph.cell(book.pv.key(True))) == ()


class TestSourcePanes:
    """The original and compiled source, or a placeholder when neither reads."""

    def test_original_source_is_written_as_the_author_wrote_it(self):
        class Sheet:
            @node
            def fib(self, n):
                return n if n < 2 else self.fib(n - 1) + self.fib(n - 2)

        cell = graph.cell(Sheet().fib.key(5))

        assert "self.fib(n - 1)" in render.original_source(cell)

    def test_compiled_source_is_the_rewritten_ivs_body(self):
        class Sheet:
            @node
            def fib(self, n):
                return n if n < 2 else self.fib(n - 1) + self.fib(n - 2)

        cell = graph.cell(Sheet().fib.key(5))

        assert render.compiled_source(cell) == (
            "def fib(self, node, ivs):\n"
            "    return ivs[0] if ivs[0] < 2 else ivs[1] + ivs[2]"
        )

    def test_original_source_shows_the_placeholder_when_unavailable(self):
        Dynamic = make_dynamic_node()
        cell = graph.cell(Dynamic().value.key())

        assert render.original_source(cell) == render.SOURCE_UNAVAILABLE

    def test_compiled_source_is_unaffected_by_the_same_failure(self):
        """A node whose original source is gone still compiled fine, so
        code() has nothing to fall back on -- both panes fail independently."""
        Dynamic = make_dynamic_node()
        cell = graph.cell(Dynamic().value.key())

        assert render.compiled_source(cell) != render.SOURCE_UNAVAILABLE


class TestLookingCostsNothing:
    """Opening the browser runs no body."""

    def test_rendering_every_region_evaluates_nothing(self, book):
        cell = graph.cell(book.pv.key(True))

        render.header_card(cell)
        render.input_rows(cell)
        render.output_rows(cell)
        render.original_source(cell)
        render.compiled_source(cell)

        assert graph.cell(book.pv.key(True)).value.state.value == "uncomputed"
        assert graph.dirty() == ()
