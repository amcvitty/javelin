"""A Black-Scholes option pricer built on the graph, run end to end.

Market data and instruments are ``McObject``s in the namespace, so pricing is
an ordinary graph computation: dependencies are static, setting spot dirties
only what is downstream of it, and a delta is a ``diddle`` away.
"""

import graph
import ns
from analytics import DiscountCurve, EuropeanOption, Market, PricingEnv
from analytics import blackscholes as bs

# Shared market data, one object each, at their /mkt names. The option finds
# them by name -- /mkt/EQ/ACME/Market from its own ticker, /mkt/IR/USD/Curve,
# /mkt/ENV/Default.
mkt = ns.lookup_or_new("/mkt/EQ/ACME/Market", Market, spot=100.0, vol=0.2)
ns.lookup_or_new("/mkt/IR/USD/Curve", DiscountCurve, rate=0.03)
ns.lookup_or_new("/mkt/ENV/Default", PricingEnv)

# Two call legs sharing that market data.
a = ns.lookup_or_new("/inst/EQ/Option/ACME-C95", EuropeanOption, strike=95.0)
b = ns.lookup_or_new("/inst/EQ/Option/ACME-C105", EuropeanOption, strike=105.0)


def book_pv():
    """No /prod class yet (GEN-21): the book is a sum of its legs here."""
    return a.pv() + b.pv()


print("Book PV =", round(book_pv(), 4))
print("  leg A (C95)  =", round(a.pv(), 4))
print("  leg B (C105) =", round(b.pv(), 4))

# pv's dependencies are known without pricing anything: forward / d1 / d2 on the
# option, today on the env, and discount_factor keyed by the tenor.
print()
print("deps(a.pv):")
for obj, method, *args in sorted(
    graph.deps(a.pv), key=lambda k: (k[0].name, k[1].__name__)
):
    shown = f"({', '.join(map(str, args))})" if args else ""
    print(f"    {obj.name}.{method.__name__}{shown}")

# Delta by diddle: bump spot up and down, reprice, let each scope restore.
s0 = mkt.spot()
h = 1e-4 * s0
with graph.diddle((mkt.spot, s0 + h)):
    up = book_pv()
with graph.diddle((mkt.spot, s0 - h)):
    down = book_pv()
delta = (up - down) / (2 * h)
analytic = bs.call_delta(a.d1()) + bs.call_delta(b.d1())
print()
print(f"Book delta by diddle = {delta:.6f}")
print(f"Book delta, N(d1)    = {analytic:.6f}")

# Leaving the diddles restored the graph -- nothing is left dirty.
print("Dirty cells after the diddles:", graph.dirty())

# Setting spot for real dirties both legs, and nothing else.
print()
print("Setting spot 100 -> 110 on the shared market...")
mkt.spot.set_value(110.0)
print("  a.pv dirty =", a.pv.is_dirty(), " b.pv dirty =", b.pv.is_dirty())
print("  a.strike dirty =", a.strike.is_dirty())
print("  Book PV =", round(book_pv(), 4))
mkt.spot.clear_value()

# Persist a leg and read it back into a fresh namespace.
print()
a.store()
print("Stored", a.name, "->", a.stored_values())
ns.clear()
graph.clear()
reloaded = ns.DEFAULT["/inst/EQ/Option/ACME-C95"]
ns.lookup_or_new("/mkt/EQ/ACME/Market", Market, spot=100.0, vol=0.2)
ns.lookup_or_new("/mkt/IR/USD/Curve", DiscountCurve, rate=0.03)
ns.lookup_or_new("/mkt/ENV/Default", PricingEnv)
print("Reloaded", reloaded.name, "-> PV =", round(reloaded.pv(), 4))
