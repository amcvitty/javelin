"""The shakeout slice: the browser against the real pricing graph (GEN-46).

The toy graph in `test_render.py` exercises the display's shapes in isolation.
This exercises the same code against the real `analytics` objects, where a
receiver is reached by evaluating a namespace lookup, a hoisted local feeds a
node call, and a collection is itself a stored node -- none of which the toy
graph, by design, ever made the engine actually do.
"""

import graph
import ns
from analytics.instrument import EuropeanOption
from analytics.market import DiscountCurve, Market, PricingEnv
from example_pricing_browser import POSITIONS, build
from tui.graph_browser import render
from tui.graph_browser.navigation import Navigation


def rows_by_slot(cell, **kwargs):
    return {row.slot: row for row in render.input_rows(cell, **kwargs)}


def make_option(strike=100.0, ticker="ACME", *, spot=None):
    """The shared `/mkt` objects plus one option on them, freshly bootstrapped.

    `spot` is left at the `Market` default unless a test needs a particular
    one -- most of these tests only care that the edge exists, not its value.
    """
    ns.lookup_or_new("/mkt/ENV/Default", PricingEnv)
    ns.lookup_or_new("/mkt/IR/USD/Curve", DiscountCurve)
    market_kwargs = {} if spot is None else {"spot": spot}
    market = ns.lookup_or_new(f"/mkt/EQ/{ticker}/Market", Market, **market_kwargs)
    option = ns.lookup_or_new(
        f"/inst/EQ/Option/{ticker}-C{strike:g}",
        EuropeanOption,
        ticker=ticker,
        strike=strike,
    )
    return market, option


class TestCrossObjectEdges:
    """An option reaches its market through the namespace: the receiver of
    `spot()` is another object entirely, found by evaluating an edge."""

    def test_an_unevaluated_market_edge_is_not_statically_resolvable(self):
        _, option = make_option()
        cell = graph.cell(option.forward.key())

        # `self.market()` is statically resolvable on its own -- it takes no
        # arguments, so the same cell is named whatever the object holds.
        # `self.market().spot()` is the real cross-object edge: its receiver
        # is *another object entirely*, found only by evaluating `market()`.
        spot_slot = next(
            slot for slot in cell.slots if slot.target == "spot" and slot.reads
        )

        assert spot_slot.cells is graph.UNRESOLVED
        assert spot_slot.statically_resolvable is False

    def test_it_names_the_slot_blocking_a_dependent_slot(self):
        _, option = make_option()
        cell = graph.cell(option.forward.key())
        market_slot = next(slot for slot in cell.slots if slot.target == "market")
        spot_slot = next(
            slot for slot in cell.slots if slot.target == "spot" and slot.reads
        )

        row = rows_by_slot(cell)[str(spot_slot.index)]

        assert row.value == "not yet resolved"
        assert row.identity == "spot()"
        assert str(market_slot.index) in row.reads.split(", ")

    def test_drilling_resolves_it_and_lands_on_the_real_market_object(self):
        market, option = make_option(spot=123.0)
        nav = Navigation(graph.cell(option.forward.key()))
        index = next(
            slot.index
            for slot in nav.focus.slots
            if slot.target == "spot" and slot.reads
        )

        result = nav.drill_slot(index)

        assert result.ok
        assert nav.focus == market.spot.key()


class TestSameObjectIdentity:
    """`pv()` calls `d1()` and `d2()` on itself -- the option is already the
    object on screen, so the row says `self.d1()`, not the option's path."""

    def test_a_same_object_call_edge_is_named_self(self):
        _, option = make_option()
        cell = graph.cell(option.pv.key())
        index = next(slot.index for slot in cell.slots if slot.target == "d1")

        cell.expand_slot(index)

        row = rows_by_slot(cell)[str(index)]
        assert row.identity == "self.d1()"


class TestHoistedLocal:
    """`tenor` is a derived intermediate hoisted above `pv`'s body, feeding
    `discount_factor`'s argument."""

    def test_tenor_occupies_its_own_slot(self):
        _, option = make_option()
        cell = graph.cell(option.pv.key())

        local = next(
            row for row in render.input_rows(cell) if row.kind == "hoisted local"
        )

        assert local.identity.startswith("tenor")

    def test_slots_that_depend_on_tenor_list_it_in_their_reads(self):
        _, option = make_option()
        cell = graph.cell(option.pv.key())
        local_index = next(
            slot.index for slot in cell.slots if str(slot.kind) == "hoisted local"
        )

        df_slot = next(
            slot
            for slot in cell.slots
            if slot.kind is not graph.InputKind.LOCAL
            and slot.kind is not graph.InputKind.TERMINAL
            and local_index in slot.reads
        )

        assert local_index in df_slot.reads


class TestRealMapEdge:
    """A book's positions are themselves a stored node -- the collection has
    to be evaluated before the map can be resolved at all."""

    def test_the_book_fans_out_to_one_row_per_position_in_order(self):
        book = build()
        member_order = book.position_paths()
        cell = graph.cell(book.pv.key())
        index = next(slot.index for slot in cell.slots if str(slot.kind) == "map edge")

        cell.expand_slot(index)

        rows = [
            row for row in render.input_rows(cell) if row.slot.startswith(f"{index}.")
        ]
        # capped, with a remainder row for the rest
        assert len(rows) == render.MAP_ROW_CAP + 1
        assert rows[-1].identity == f"... {POSITIONS - render.MAP_ROW_CAP} more"
        # each shown row names the position at the same index in the book's
        # own membership list, so the fan-out preserves the book's order.
        shown_paths = [row.identity for row in rows[:-1]]
        expected_paths = [
            render.truncate_left(f"{path}.pv()")
            for path in member_order[: render.MAP_ROW_CAP]
        ]
        assert shown_paths == expected_paths

    def test_the_cap_behaves_correctly_for_a_book_larger_than_it(self):
        book = build()
        cell = graph.cell(book.pv.key())
        index = next(slot.index for slot in cell.slots if str(slot.kind) == "map edge")
        cell.expand_slot(index)

        rows = [
            row for row in render.input_rows(cell) if row.slot.startswith(f"{index}.")
        ]

        assert len(rows) - 1 == render.MAP_ROW_CAP
        assert "more" in rows[-1].identity


class TestLongNamespacePaths:
    def test_a_long_identity_in_the_real_graph_is_truncated_from_the_left(self):
        book = build()
        cell = graph.cell(book.pv.key())
        index = next(slot.index for slot in cell.slots if str(slot.kind) == "map edge")
        cell.expand_slot(index)

        rows = [
            row for row in render.input_rows(cell) if row.slot.startswith(f"{index}.")
        ]
        long_row = next(row for row in rows if "pv()" in row.identity)

        assert len(long_row.identity) <= render.IDENTITY_WIDTH
        assert long_row.identity.startswith("...")
        assert long_row.identity.endswith("pv()")

    def test_two_markets_on_different_underlyings_stay_distinguishable(self):
        book = build()
        cell = graph.cell(book.pv.key())
        cell.expand_slot(
            next(slot.index for slot in cell.slots if str(slot.kind) == "map edge")
        )

        rows = render.input_rows(cell)
        identities = {row.identity for row in rows if row.identity}

        assert len(identities) == len({render.truncate_left(i) for i in identities})


class TestOverriddenAndDirtyValues:
    """Setting spot on a shared market dirties both legs and nothing else."""

    def test_setting_spot_dirties_downstream_and_leaves_unrelated_cells_clean(self):
        build()
        acme = ns.DEFAULT["/mkt/EQ/ACME/Market"]
        curve = ns.DEFAULT["/mkt/IR/USD/Curve"]
        leg_a = ns.DEFAULT["/inst/EQ/Option/ACME-C90"]
        leg_b = ns.DEFAULT["/inst/EQ/Option/ACME-C91"]
        leg_a.pv()
        leg_b.pv()
        curve.discount_factor(1.0)  # unrelated to spot -- must stay clean

        acme.spot.set_value(111.0)

        dirty_a = dict(render.header_card(graph.cell(leg_a.pv.key())))
        dirty_b = dict(render.header_card(graph.cell(leg_b.pv.key())))
        clean = dict(render.header_card(graph.cell(curve.discount_factor.key(1.0))))
        assert "dirty" in dirty_a["value"]
        assert "dirty" in dirty_b["value"]
        assert "dirty" not in clean["value"]

    def test_a_diddle_scope_shows_overridden_then_restores_on_exit(self):
        build()
        acme = ns.DEFAULT["/mkt/EQ/ACME/Market"]
        leg = ns.DEFAULT["/inst/EQ/Option/ACME-C90"]
        clean_value = leg.pv()

        with graph.diddle((acme.spot, 999.0)):
            spot_during = dict(render.header_card(graph.cell(acme.spot.key())))
            assert spot_during["value"] == "999.0 (overridden)"
            bumped_value = leg.pv()
            during = dict(render.header_card(graph.cell(leg.pv.key())))
            assert during["value"] == repr(bumped_value)
            assert bumped_value != clean_value

        spot_after = dict(render.header_card(graph.cell(acme.spot.key())))
        assert spot_after["value"] == "105.0 (overridden)"
        after = dict(render.header_card(graph.cell(leg.pv.key())))
        assert after["value"] == repr(clean_value)


class TestLookingCostsNothing:
    def test_building_and_rendering_the_real_graph_evaluates_only_what_build_asked_for(
        self,
    ):
        book = build()

        cell = graph.cell(book.pv.key())
        render.header_card(cell)
        render.input_rows(cell)
        render.output_rows(cell)

        # build() leaves the widget leg dirty on purpose (a dirty cell in the
        # graph, deliberately outside the book) -- rendering must not clear it.
        assert ns.DEFAULT["/inst/EQ/Option/WIDGETCO-C100"].pv.is_dirty() is True
        assert graph.cell(book.pv.key()).value.state is graph.ValueState.CLEAN
