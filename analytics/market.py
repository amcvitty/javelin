"""Shared market data: the ``/mkt`` layer of the namespace.

One ``Market`` per underlying (spot and vol), one ``DiscountCurve`` per
currency, one ``PricingEnv`` for the valuation date the whole graph agrees on.
See ``CONTEXT.md`` and ``docs/adr/0001-namespace-taxonomy.md``.

Everything here is flat on purpose: a real term structure and vol surface are
GEN-22. An instrument calls these objects the same way either way.
"""

import datetime
import math

from graph import node
from ns import McObject


class Market(McObject):
    """Per-underlying market data, named ``/mkt/EQ/<ticker>/Market``."""

    @node(node.Stored)
    def spot(self):
        """Current spot price of the underlying."""
        return 100.0

    @node(node.Stored)
    def vol(self):
        """Flat Black-Scholes volatility -- one number for every strike and
        expiry. A real vol surface is GEN-22."""
        return 0.2


class DiscountCurve(McObject):
    """A discount curve, named ``/mkt/IR/<ccy>/Curve``.

    Flat: one continuously-compounded rate, so
    ``discount_factor(t) = exp(-rate * t)``. Term-structure interpolation is
    GEN-22.
    """

    @node(node.Stored)
    def rate(self):
        """The flat continuously-compounded rate."""
        return 0.03

    @node
    def discount_factor(self, t):
        """The value today of 1 unit paid at time ``t`` (years): ``exp(-r t)``."""
        return math.exp(-self.rate() * t)


class PricingEnv(McObject):
    """The shared valuation context, named ``/mkt/ENV/Default``."""

    @node(node.Stored)
    def today(self):
        """The one valuation date the whole graph agrees on.

        Stored rather than read from the wall clock, so a run is reproducible
        and the date can be set or diddled like any other cell.
        """
        return datetime.date(2026, 1, 1)
