"""Black-Scholes maths, as plain functions.

No ``@node``, no import of ``graph`` or ``ns``: a node body calls these the way
it calls ``datetime.date.today()``, and the rewriter leaves them untouched.
Keeping the formulae here also means they can be checked without building a
graph.

European call, no carry beyond the risk-free rate (``q = 0``). The pieces are
deliberately separate so a node can expose ``d1`` and ``d2`` as their own cells:

    forward -> d1 -> d2 -> price
"""

import math
from statistics import NormalDist

_STD_NORMAL = NormalDist(0.0, 1.0)


def norm_cdf(x: float) -> float:
    """``N(x)``, the standard normal cumulative distribution."""
    return _STD_NORMAL.cdf(x)


def norm_pdf(x: float) -> float:
    """``phi(x)``, the standard normal density."""
    return _STD_NORMAL.pdf(x)


def d1(forward: float, strike: float, vol: float, tenor: float) -> float:
    """``(ln(F / K) + 0.5 * sigma**2 * T) / (sigma * sqrt(T))``."""
    vol_root_t = vol * math.sqrt(tenor)
    return (math.log(forward / strike) + 0.5 * vol_root_t * vol_root_t) / vol_root_t


def d2(d1_: float, vol: float, tenor: float) -> float:
    """``d1 - sigma * sqrt(T)``."""
    return d1_ - vol * math.sqrt(tenor)


def call_price_from_d(
    forward: float,
    strike: float,
    discount_factor: float,
    d1_: float,
    d2_: float,
) -> float:
    """``DF * (F * N(d1) - K * N(d2))`` -- the undiscounted-forward form."""
    return discount_factor * (forward * norm_cdf(d1_) - strike * norm_cdf(d2_))


def call_delta(d1_: float) -> float:
    """``dPrice / dSpot`` for a European call: ``N(d1)``.

    With ``F = S * exp(r * T)`` and ``DF = exp(-r * T)`` the forward-form price
    collapses to ``S * N(d1) - K * exp(-r * T) * N(d2)``, whose spot derivative
    is exactly ``N(d1)``.
    """
    return norm_cdf(d1_)
