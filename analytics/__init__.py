"""Pricing analytics on top of the namespace.

``analytics`` builds quant objects -- market data and instruments -- as
``McObject``s in the namespace, so a pricer is an ordinary graph computation:
dependencies are static, setting spot dirties only what is downstream of it, and
a greek is a ``diddle`` away.

Layering is one way, ``analytics -> ns -> graph``; nothing lower imports this
package. The object naming scheme (``/mkt``, ``/inst``, ``/trade``, ``/book``,
and the later ``/prod``) is in ``CONTEXT.md`` and
``docs/adr/0001-namespace-taxonomy.md``.
"""

from . import blackscholes
from .book import Book, Trade
from .instrument import EuropeanOption
from .market import DiscountCurve, Market, PricingEnv

__all__ = [
    "Book",
    "DiscountCurve",
    "EuropeanOption",
    "Market",
    "PricingEnv",
    "Trade",
    "blackscholes",
]
