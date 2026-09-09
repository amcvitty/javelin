"""Books and trades: the ``/trade`` and ``/book`` layers, priced by fan-out.

A book's ``pv`` is one comprehension over its member paths, so the whole point
of these tests is that every member is a *real* dependency: the book knows what
it is made of without being priced, it goes stale when a member does, and a
greek by diddle reaches through it.
"""

import pytest

import graph
import ns
from analytics import Book, DiscountCurve, EuropeanOption, Market, PricingEnv, Trade
from analytics import blackscholes as bs
from graph import node
from tests.helpers import spy_bodies

MARKET_CLASSES = (Market, DiscountCurve, PricingEnv, EuropeanOption, Trade, Book)


def _book(quantities=(10.0, -4.0)):
    """One book of two trades on two options sharing one Market / Curve / Env."""
    mkt = ns.lookup_or_new("/mkt/EQ/ACME/Market", Market, spot=100.0, vol=0.2)
    ns.lookup_or_new("/mkt/IR/USD/Curve", DiscountCurve, rate=0.03)
    ns.lookup_or_new("/mkt/ENV/Default", PricingEnv)
    ns.lookup_or_new("/inst/EQ/Option/ACME-C95", EuropeanOption, strike=95.0)
    ns.lookup_or_new("/inst/EQ/Option/ACME-C105", EuropeanOption, strike=105.0)

    paths = []
    for i, (strike, quantity) in enumerate(zip((95.0, 105.0), quantities)):
        path = f"/trade/EQD/2026/T-{i}"
        ns.lookup_or_new(
            path,
            Trade,
            instrument_path=f"/inst/EQ/Option/ACME-C{strike:.0f}",
            quantity=quantity,
        )
        paths.append(path)
    book = ns.lookup_or_new("/book/EQD/exotics/london", Book, trade_paths=paths)
    return mkt, book, paths


class TestBookPv:
    def test_book_pv_is_the_signed_sum_of_its_trades(self):
        _, book, paths = _book()
        trades = [ns.DEFAULT[path] for path in paths]

        assert book.pv() == pytest.approx(sum(t.pv() for t in trades))

    def test_a_sold_trade_contributes_negatively(self):
        _, book, paths = _book(quantities=(1.0, -1.0))
        long, short = (ns.DEFAULT[path] for path in paths)

        assert short.pv() == -short.instrument().pv()
        assert book.pv() == pytest.approx(long.pv() + short.pv())

    def test_an_empty_book_is_worth_nothing(self):
        ns.lookup_or_new("/mkt/ENV/Default", PricingEnv)
        book = ns.lookup_or_new("/book/EQD/exotics/empty", Book, trade_paths=[])

        assert book.pv() == 0
        assert graph.deps(book.pv) == {(book, Book.trade_paths)}


class TestBookDeps:
    def test_every_member_is_a_dependency(self):
        _, book, paths = _book()
        trades = [ns.DEFAULT[path] for path in paths]

        assert graph.deps(book.pv) == {
            (book, Book.trade_paths),
            *((trade, Trade.pv) for trade in trades),
        }

    def test_a_member_going_stale_dirties_the_book(self):
        mkt, book, _ = _book()
        book.pv()
        assert not book.pv.is_dirty()

        mkt.spot.set_value(110.0)

        assert book.pv.is_dirty()

    def test_changing_membership_dirties_the_book(self):
        _, book, paths = _book()
        before = book.pv()

        book.trade_paths.set_value(paths[:1])

        assert book.pv.is_dirty()
        assert book.pv() != before
        assert graph.deps(book.pv) == {
            (book, Book.trade_paths),
            (ns.DEFAULT[paths[0]], Trade.pv),
        }

    def test_the_same_trade_twice_is_one_cell_but_counted_twice(self):
        _, book, paths = _book()
        one = ns.DEFAULT[paths[0]]
        book.trade_paths.set_value([paths[0], paths[0]])

        # A frozenset of dependencies cannot hold the trade twice, but the
        # book is still worth two of it.
        assert graph.deps(book.pv) == {(book, Book.trade_paths), (one, Trade.pv)}
        assert book.pv() == pytest.approx(2 * one.pv())


class TestGreeksThroughABook:
    def test_book_delta_by_diddle_matches_the_closed_form(self):
        mkt, book, paths = _book(quantities=(10.0, -4.0))
        trades = [ns.DEFAULT[path] for path in paths]
        book.pv()  # warm every cell so the diddle has caches to displace

        s0 = mkt.spot()
        h = 1e-4 * s0
        with graph.diddle((mkt.spot, s0 + h)):
            up = book.pv()
        with graph.diddle((mkt.spot, s0 - h)):
            down = book.pv()
        delta = (up - down) / (2 * h)

        analytic = sum(
            trade.quantity() * bs.call_delta(trade.instrument().d1())
            for trade in trades
        )
        assert delta == pytest.approx(analytic, abs=1e-6)

    def test_leaving_the_scope_restores_the_book(self):
        mkt, book, _ = _book()
        before = book.pv()

        with graph.diddle((mkt.spot, mkt.spot() + 5.0)):
            assert book.pv() != before

        evaluated: list = []
        with spy_bodies(evaluated, *MARKET_CLASSES):
            assert book.pv() == before
            assert evaluated == []
        assert graph.dirty() == ()


class TestExpansionCost:
    def test_expanding_a_book_does_not_price_it(self):
        """Expansion needs the member *list* -- that is what says how many cells
        there are -- but not the members' values. So a book can be asked what it
        depends on without pricing a single trade."""
        _, book, _ = _book()

        evaluated: list = []
        with spy_bodies(evaluated, *MARKET_CLASSES):
            found = graph.deps(book.pv)

        assert len(found) == 3  # the member list, and one cell per trade
        assert evaluated == []

    def test_expansion_evaluates_the_collection_itself(self):
        """The one thing it must run: whatever produces the members. Here the
        list is a stored value, so use a book whose membership has a body."""

        ran: list = []

        class Derived(Book):
            @node
            def trade_paths(self):
                ran.append("trade_paths")
                return ["/trade/EQD/2026/T-0"]

        _book()
        book = ns.lookup_or_new("/book/EQD/exotics/derived", Derived)

        graph.deps(book.pv)

        assert ran == ["trade_paths"]
