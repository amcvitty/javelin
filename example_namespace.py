"""Objects that refer to each other by name, and persist.

The example from TODO.md, run end to end.
"""

import datetime

import graph
import ns
from graph import node
from ns import McObject


class GlobalParameters(McObject):
    """Object that holds global environmental parameters"""

    @node
    def Today(self):
        """Today's date"""
        # A local date on purpose: the point is that the whole graph shares one
        # idea of "today", which is then set or diddled rather than read live.
        return datetime.date.today()  # noqa: DTZ011


class EquityMarket(McObject):
    """Represents an equity market"""

    @node(node.Stored)
    def StockPrice(self):
        """Current stock price"""
        return 25.0

    @node(node.Stored)
    def ImpliedVolatility(self):
        """Current implied volatility - the same for all expirations and strikes"""
        return 0.3


class EquityOption(McObject):
    """Represents an equity option instrument"""

    @node(node.Stored)
    def Ticker(self):
        """Ticker of the underlying equity"""
        return "ABC"

    @node(node.Stored)
    def ExpirationDate(self):
        """Option expiration date"""
        return self.ns["/GlobalParameters"].Today() + datetime.timedelta(365)

    @node(node.Stored)
    def Strike(self):
        """Strike price of the option"""
        return self.EquityObj().StockPrice()  # defaults to at-the-money spot

    @node(node.Stored)
    def OptionType(self):
        """Call or Put"""
        return "Call"

    @node
    def EquityObj(self):
        """Reference to the equity object for the appropriate ticker"""
        return self.ns["/Equities/" + self.Ticker()]

    @node
    def Premium(self):
        """Option premium. A placeholder, not a real pricer."""
        print("In Premium")
        return max(self.EquityObj().StockPrice() - self.Strike(), 0.0)


# create a global parameters object with a well-defined name, so that we can
# access it from nodes in the graph
params = ns.lookup_or_new("/GlobalParameters", GlobalParameters)
print("Today date =", params.Today().strftime("%d%b%Y"))

# create equity market objects for one ticker; explicitly define some of the
# inputs when it's created, which overwrite the defaults in the class
# definition. Also has an explicit name, so that option objects can refer to it.
eq_mkt = ns.lookup_or_new("/Equities/ABC", EquityMarket, StockPrice=20.0)
print("Stock price =", eq_mkt.StockPrice())
print("Implied Vol =", eq_mkt.ImpliedVolatility())

# create an equity option object. No need to give it an explicit name, since
# nothing refers to it in this example.
opt = ns.new(EquityOption, Ticker="ABC", Strike=20.0)
print("Equity market object referred to by the option =", opt.EquityObj())
prem = opt.Premium()  # prints "In Premium" -- first time it's calculated
print("Option premium =", prem)
prem = opt.Premium()  # "In Premium" is not printed again: the value is cached
print("Option premium =", prem)

# the option's premium depends on the market object's stock price, across the
# namespace, so setting it there recomputes the premium here
print()
print("Setting the stock price on the market object...")
eq_mkt.StockPrice.set_value(30.0)
print("Premium is dirty =", opt.Premium.is_dirty())
print("Option premium =", opt.Premium())  # prints "In Premium" again

# and the dependency is in the graph, reaching across to the other object
print()
print("Premium depends on:")
for obj, method, *args in sorted(
    graph.deps(opt.Premium), key=lambda key: key[1].__name__
):
    print(f"    {obj}.{method.__name__}{args or ''}")

# persist the option, then reload it into a namespace that has forgotten it
print()
opt.store()
print("Stored", opt.name, "->", opt.stored_values())

ns.clear()
graph.clear()
reloaded = ns.DEFAULT[opt.name]
print("Reloaded", reloaded.name)
print("Strike =", reloaded.Strike(), "OptionType =", reloaded.OptionType())
print("Its stored cells have values, so no body runs:")
print("    deps(Strike) =", graph.deps(reloaded.Strike))
