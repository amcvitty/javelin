"""The /mkt objects: Market, DiscountCurve, PricingEnv."""

import datetime
import math

import pytest

import graph
import ns
from analytics import DiscountCurve, Market, PricingEnv


class TestMarket:
    def test_stored_defaults(self):
        m = ns.new(Market)
        assert m.spot() == 100.0
        assert m.vol() == 0.2
        assert set(graph.stored_nodes(Market)) == {"spot", "vol"}

    def test_keyword_values_override_the_defaults(self):
        m = ns.lookup_or_new("/mkt/EQ/ACME/Market", Market, spot=123.0, vol=0.31)
        assert (m.spot(), m.vol()) == (123.0, 0.31)

    def test_a_stored_cell_has_no_dependencies(self):
        m = ns.new(Market, spot=100.0)
        assert graph.deps(m.spot) == frozenset()


class TestDiscountCurve:
    def test_discount_factor_is_exp_minus_rt(self):
        c = ns.new(DiscountCurve, rate=0.05)
        assert c.discount_factor(2.0) == pytest.approx(math.exp(-0.05 * 2.0))

    def test_discount_factor_is_a_cell_keyed_by_t(self):
        c = ns.new(DiscountCurve, rate=0.05)
        c.discount_factor(1.0)
        c.discount_factor(2.0)
        keyed = {
            args[0]
            for obj, fn, *args in graph.all_nodes()
            if fn.__name__ == "discount_factor" and args
        }
        assert keyed == {1.0, 2.0}

    def test_discount_factor_depends_on_rate_only(self):
        c = ns.new(DiscountCurve, rate=0.05)
        assert graph.deps(c.discount_factor, 1.0) == {(c, DiscountCurve.rate)}

    def test_setting_the_rate_dirties_the_factor(self):
        c = ns.new(DiscountCurve, rate=0.05)
        c.discount_factor(1.0)
        c.rate.set_value(0.06)
        assert c.discount_factor.is_dirty(args=(1.0,))
        assert c.discount_factor(1.0) == pytest.approx(math.exp(-0.06))


class TestPricingEnv:
    def test_today_default(self):
        e = ns.new(PricingEnv)
        assert e.today() == datetime.date(2026, 1, 1)

    def test_today_is_stored(self):
        assert graph.stored_nodes(PricingEnv) == ("today",)


class TestPersistence:
    def test_round_trips_through_the_store(self):
        m = ns.lookup_or_new("/mkt/EQ/ACME/Market", Market, spot=111.0, vol=0.22)
        c = ns.lookup_or_new("/mkt/IR/USD/Curve", DiscountCurve, rate=0.04)
        e = ns.lookup_or_new("/mkt/ENV/Default", PricingEnv)
        e.today.set_value(datetime.date(2026, 6, 30))
        for obj in (m, c, e):
            obj.store()

        ns.clear()
        graph.clear()

        m2 = ns.DEFAULT["/mkt/EQ/ACME/Market"]
        c2 = ns.DEFAULT["/mkt/IR/USD/Curve"]
        e2 = ns.DEFAULT["/mkt/ENV/Default"]
        assert (m2.spot(), m2.vol()) == (111.0, 0.22)
        assert c2.rate() == 0.04
        assert e2.today() == datetime.date(2026, 6, 30)
        # Loaded stored cells are set values, so no body runs behind them.
        assert graph.deps(m2.spot) == frozenset()
