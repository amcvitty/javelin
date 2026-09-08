"""Greeks by diddle -- the artefact GEN-19 exists to produce.

Bump spot inside a ``diddle`` scope, reprice, let the scope exit restore. One
test shows the bump is **correct** (exactly the cells downstream of spot
recompute, nothing else) and **cheap** (leaving the scope recomputes nothing).
"""

import graph
import ns
from analytics import DiscountCurve, EuropeanOption, Market, PricingEnv
from analytics import blackscholes as bs
from tests.helpers import spy_bodies

MARKET_CLASSES = (Market, DiscountCurve, PricingEnv, EuropeanOption)


def _book():
    """Two call legs, different strikes, sharing one Market / Curve / Env."""
    mkt = ns.lookup_or_new("/mkt/EQ/ACME/Market", Market, spot=100.0, vol=0.2)
    ns.lookup_or_new("/mkt/IR/USD/Curve", DiscountCurve, rate=0.03)
    ns.lookup_or_new("/mkt/ENV/Default", PricingEnv)
    a = ns.lookup_or_new("/inst/EQ/Option/ACME-C95", EuropeanOption, strike=95.0)
    b = ns.lookup_or_new("/inst/EQ/Option/ACME-C105", EuropeanOption, strike=105.0)
    return mkt, a, b


def test_delta_by_diddle_is_correct_and_cheap():
    mkt, a, b = _book()

    # No product class yet (GEN-21): the book PV is a sum in the test body.
    def book_pv():
        return a.pv() + b.pv()

    book_pv()  # warm every cell so the diddle has caches to displace

    s0 = mkt.spot()
    h = 1e-4 * s0

    evaluated: list = []
    with spy_bodies(evaluated, *MARKET_CLASSES):
        with graph.diddle((mkt.spot, s0 + h)):
            up = book_pv()

        # Correct: the bump recomputed exactly the spot-downstream cells on
        # each leg, and nothing on the shared market data. `tenor` is a Local,
        # not a cell, so it is legitimately absent.
        assert set(evaluated) == {
            ("/inst/EQ/Option/ACME-C95", "forward"),
            ("/inst/EQ/Option/ACME-C95", "d1"),
            ("/inst/EQ/Option/ACME-C95", "d2"),
            ("/inst/EQ/Option/ACME-C95", "pv"),
            ("/inst/EQ/Option/ACME-C105", "forward"),
            ("/inst/EQ/Option/ACME-C105", "d1"),
            ("/inst/EQ/Option/ACME-C105", "d2"),
            ("/inst/EQ/Option/ACME-C105", "pv"),
        }
        for clean in [
            ("/mkt/EQ/ACME/Market", "vol"),
            ("/mkt/IR/USD/Curve", "rate"),
            ("/mkt/IR/USD/Curve", "discount_factor"),
            ("/mkt/ENV/Default", "today"),
            ("/inst/EQ/Option/ACME-C95", "strike"),
            ("/inst/EQ/Option/ACME-C105", "strike"),
        ]:
            assert clean not in evaluated

        with graph.diddle((mkt.spot, s0 - h)):
            down = book_pv()

        evaluated.clear()
        # Cheap: leaving the second scope restored; asking again runs nothing.
        assert book_pv() == a.pv() + b.pv()
        assert evaluated == []

    delta = (up - down) / (2 * h)

    # Cross-check against the closed form: a call's spot delta is N(d1).
    analytic = bs.call_delta(a.d1()) + bs.call_delta(b.d1())
    assert abs(delta - analytic) < 1e-6


def test_diddle_exit_restores_the_pre_bump_value():
    mkt, a, b = _book()
    before = a.pv() + b.pv()

    with graph.diddle((mkt.spot, mkt.spot() + 5.0)):
        assert a.pv() + b.pv() > before

    assert a.pv() + b.pv() == before
    assert graph.dirty() == ()
