"""EuropeanOption: the graph shape and the price."""

import datetime
import math

import pytest

import graph
import ns
from analytics import DiscountCurve, EuropeanOption, Market, PricingEnv
from analytics import blackscholes as bs
from analytics.instrument import _year_fraction
from tests.helpers import spy_bodies


@pytest.fixture
def market_data():
    """One shared Market / DiscountCurve / PricingEnv, at their /mkt names."""
    mkt = ns.lookup_or_new("/mkt/EQ/ACME/Market", Market, spot=100.0, vol=0.2)
    cur = ns.lookup_or_new("/mkt/IR/USD/Curve", DiscountCurve, rate=0.03)
    env = ns.lookup_or_new("/mkt/ENV/Default", PricingEnv)
    return mkt, cur, env


def _hand_price(spot, strike, rate, vol, tenor):
    forward = spot * math.exp(rate * tenor)
    d1 = bs.d1(forward, strike, vol, tenor)
    d2 = bs.d2(d1, vol, tenor)
    return bs.call_price_from_d(forward, strike, math.exp(-rate * tenor), d1, d2)


class TestPrice:
    def test_pv_matches_black_scholes(self, market_data):
        _, _, env = market_data
        opt = ns.lookup_or_new("/inst/EQ/Option/ACME-C95", EuropeanOption, strike=95.0)
        tenor = _year_fraction(env.today(), opt.expiry())
        assert opt.pv() == pytest.approx(_hand_price(100.0, 95.0, 0.03, 0.2, tenor))

    def test_two_options_share_one_market_object(self, market_data):
        a = ns.lookup_or_new("/inst/EQ/Option/A", EuropeanOption, strike=95.0)
        b = ns.lookup_or_new("/inst/EQ/Option/B", EuropeanOption, strike=105.0)
        assert a.market() is b.market() is market_data[0]


class TestGraphShape:
    def test_pv_dependencies(self, market_data):
        _, _, env = market_data
        opt = ns.lookup_or_new("/inst/EQ/Option/A", EuropeanOption, strike=95.0)
        tenor = _year_fraction(env.today(), opt.expiry())
        deps = {(obj.name, fn.__name__, *args) for obj, fn, *args in graph.deps(opt.pv)}
        assert deps == {
            ("/inst/EQ/Option/A", "forward"),
            ("/inst/EQ/Option/A", "d1"),
            ("/inst/EQ/Option/A", "d2"),
            ("/inst/EQ/Option/A", "strike"),
            ("/inst/EQ/Option/A", "curve"),
            ("/inst/EQ/Option/A", "env"),
            ("/inst/EQ/Option/A", "expiry"),
            ("/mkt/ENV/Default", "today"),
            ("/mkt/IR/USD/Curve", "discount_factor", tenor),
        }

    def test_tenor_is_a_hoisted_local(self, market_data):
        locals_ = [
            inp
            for inp in graph.inputs(EuropeanOption.pv)
            if isinstance(inp, graph.Local)
        ]
        assert any(inp.name == "tenor" for inp in locals_)

        body = graph.code(EuropeanOption.pv)
        assert "tenor =" not in body  # the assignment was lifted out
        assert "ivs[" in body  # ...and the body reads the slot

    def test_expanding_pv_runs_no_pricing_body(self, market_data):
        opt = ns.lookup_or_new("/inst/EQ/Option/A", EuropeanOption, strike=95.0)
        ran: list = []
        with spy_bodies(ran, EuropeanOption, PricingEnv):
            graph.deps(opt.pv)
        ran_names = {name for _, name in ran}

        # The pricing chain stays cold...
        assert ran_names & {"forward", "d1", "d2", "pv"} == set()
        # ...but expansion *does* run expiry and today, because the tenor they
        # feed decides which discount_factor cell pv depends on (the `needed`
        # mechanism -- see README "When an edge's shape depends on a value").
        assert {"expiry", "today"} <= ran_names


class TestCrossObjectDirtying:
    def test_setting_spot_dirties_the_option(self, market_data):
        mkt = market_data[0]
        opt = ns.lookup_or_new("/inst/EQ/Option/A", EuropeanOption, strike=95.0)
        first = opt.pv()

        mkt.spot.set_value(110.0)

        assert opt.pv.is_dirty()
        assert not opt.strike.is_dirty()
        assert opt.pv() > first  # a call is worth more with spot higher

    def test_setting_today_dirties_the_option(self, market_data):
        # `tenor` runs through the `_year_fraction` helper, but the dates it is
        # given -- self.env().today() and self.expiry() -- stay real edges, so
        # rolling the valuation date must still reprice.
        _, _, env = market_data
        opt = ns.lookup_or_new("/inst/EQ/Option/A", EuropeanOption, strike=95.0)
        first = opt.pv()

        env.today.set_value(datetime.date(2026, 7, 1))

        assert opt.forward.is_dirty()
        assert opt.pv.is_dirty()
        assert opt.pv() < first  # less time value with expiry nearer
