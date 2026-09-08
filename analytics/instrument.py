"""Instruments: the ``/inst`` layer.

A ``EuropeanOption`` is priced by Black-Scholes off the shared ``/mkt`` objects
it reaches through the namespace, so setting spot on the ``Market`` dirties
exactly the option cells downstream of spot and nothing else.

Call only. A put is one guard away in ``pv`` -- ``# TODO`` below -- and is left
out so the analytic delta (``N(d1)``) the greeks test checks against stays
unambiguous.
"""

import datetime
import math

from graph import node
from ns import McObject

from . import blackscholes

_YEAR_DAYS = 365.0  # ACT/365. Day-count conventions proper are out of scope.


def _year_fraction(today, expiry):
    """ACT/365 time from ``today`` to ``expiry``, in years.

    Takes the two dates already resolved -- the bodies call it as
    ``_year_fraction(self.env().today(), self.expiry())`` so that ``today`` and
    ``expiry`` stay real graph edges, while the ``.days / 365`` arithmetic
    lives in one place. Where the result feeds a node-call argument the
    rewriter still hoists the assignment into a ``Local`` (GEN-18).
    """
    return (expiry - today).days / _YEAR_DAYS


class EuropeanOption(McObject):
    """A European call on one equity, named ``/inst/EQ/Option/<name>``."""

    # -- contract terms (persisted) --------------------------------------

    @node(node.Stored)
    def ticker(self):
        """Ticker of the underlying equity."""
        return "ACME"

    @node(node.Stored)
    def strike(self):
        """Strike price."""
        return 100.0

    @node(node.Stored)
    def expiry(self):
        """Expiration date."""
        return datetime.date(2027, 1, 1)

    @node(node.Stored)
    def option_type(self):
        """``"Call"`` or ``"Put"``. Only ``"Call"`` is priced for now."""
        return "Call"

    # -- market data this option reads ---------------------------------

    @node
    def market(self):
        """The shared market data for this option's underlying."""
        return self.ns["/mkt/EQ/" + self.ticker() + "/Market"]

    @node
    def curve(self):
        """The discount curve. USD only for now -- GEN-24 for multi-currency."""
        return self.ns["/mkt/IR/USD/Curve"]

    @node
    def env(self):
        """The shared pricing environment."""
        return self.ns["/mkt/ENV/Default"]

    # -- pricing --------------------------------------------------------

    @node
    def forward(self):
        """Forward price of the underlying at expiry, no dividends."""
        tenor = _year_fraction(self.env().today(), self.expiry())
        return self.market().spot() * math.exp(self.curve().rate() * tenor)

    @node
    def d1(self):
        """Black-Scholes ``d1``."""
        tenor = _year_fraction(self.env().today(), self.expiry())
        return blackscholes.d1(
            self.forward(), self.strike(), self.market().vol(), tenor
        )

    @node
    def d2(self):
        """Black-Scholes ``d2``."""
        tenor = _year_fraction(self.env().today(), self.expiry())
        return blackscholes.d2(self.d1(), self.market().vol(), tenor)

    @node
    def pv(self):
        """Present value of one unit of the option.

        ``tenor`` here is a hoisted ``Local`` (GEN-18): its right-hand side
        reads only edges, and it feeds the node-call argument
        ``curve().discount_factor(tenor)``.
        """
        # TODO: branch on option_type() for puts once there is a put payoff.
        tenor = _year_fraction(self.env().today(), self.expiry())
        df = self.curve().discount_factor(tenor)
        return blackscholes.call_price_from_d(
            self.forward(), self.strike(), df, self.d1(), self.d2()
        )
