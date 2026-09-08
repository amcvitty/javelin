- Observable nodes: subscribe to a cell and be called back when it becomes
  dirty, so a UI can refresh just the cells on screen that changed. Dirty
  marking already traverses the graph transitively (`Graph._dirty_from`); this
  exposes that traversal. Open questions:
  - subscribe / unsubscribe on a bound node
  - whether a diddle notifies -- its exit un-dirties cells wholesale, so a
    subscriber would have to hear about that too
  - whether callbacks fire during the traversal or are batched at the end of
    set_value
- Visualise and debug the graph, specifically in notebook
- show_graph()
- show_node()

# Gromit and the Beacon Namespace -- DONE

Built: see the `ns` package, `example_namespace.py`, and the README sections
"Depending on other objects" and "Stored nodes and the namespace". The example
below runs as written.

Still open here:

- `ns` lookups are not themselves graph cells, so adding an object under a name
  a node already looked up and failed on will not dirty anything.
- The store holds one row per object with no versioning or history.
- `lookup_or_new` takes the class on trust: looking a stored object up with a
  different class than it was written with is not checked.


Single objects are interesting, but limited. Real applications have multiple different objects encapsulating
different bits of functionality.

We will add an in-memory namespace, connected to an object-oriented document store, that lets you define
well-named objects. Gromit's graph lets you access those objects by name, and depend on methods on other objects.

To work in the namespace, our objects will inherit from McObject. McObjects have a name field (This field is not a node) and a "ns", which is their namespace. McObjects can only be created by ns.new or ns.lookup_or_new.

When creating an object, you can specify its values with keyword args in the new() or lookup_or_new() function. In either case it will set_value on whatever was there (either the default in the function, or whatever is loaded from the database)

This example should work:

```python
import datetime
import ns  # this is from our project


class GlobalParameters(McObject):
    """Object that holds global environmental parameters"""

    @node
    def Today(self):
        """Today's date"""
        return datetime.date.today()


class EquityMarket(McObject):
    """Represents an equity market"""

    @node(node.Stored)
    def StockPrice(self):
        """Current stock price"""
        return 25.0

    @node(node.Stored)
    def ImpliedVolatility(self):
        """Current implied volatility - assumed the same for all expirations and strikes"""
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
        """Option premium"""
        # Not in the OCR'd source, but the example below calls it. Placeholder
        # for a real pricer.
        print("In Premium")
        return max(self.EquityObj().StockPrice() - self.Strike(), 0.0)


# create a global parameters object with a well-defined name, so that we can
# access it from nodes in the graph
params = ns.lookup_or_new("/GlobalParameters", GlobalParameters)
print("Today date = ", params.Today().strftime("%d%b%Y"))

# create equity market objects for one ticker; explicitly define some of the
# inputs when it's created, which overwrite the defaults in the class
# definition. Also has an explicit name, so that option objects can refer to it.
eq_mkt = ns.lookup_or_new("/Equities/ABC", EquityMarket, StockPrice=20.0)
print("Stock price =", eq_mkt.StockPrice())
print("Implied Vol =", eq_mkt.ImpliedVolatility())

# create an equity option object. No need to give it an explicit name, since
# nothing refers to it in this example -- though you could name it, or ask it
# for its "identity", which is a unique name instruments can calculate that's a
# hash of their contract terms.
opt = ns.new(EquityOption, Ticker="ABC", Strike=20.0)
print("Equity market object referred to by the option =", opt.EquityObj())
prem = opt.Premium()  # prints "In Premium" -- first time it's calculated
print("Option premium =", prem)
prem = opt.Premium()  # "In Premium" is not printed again: the value is cached
```

Inherited from McObject

- Default GUID name for object
- Get name
- `__str__()` function giving "<class:name>"
- `store()` function to persist the object to the database. All @node methods that are marked as `node.Stored` will be persisted.

There is a global object namespace in the ns python package that allows us to lookup other objects, and it's linked to the database - i.e. if the object has not yet been loaded, it will be pulled from database. All objects are by default in that namespace, and inherit a link to that namespace as a parameter.

The database will for now be a sqlite database storing the objects with their name as the key. The value will be a JSON representation of the stored nodes - a simple map of method name to value. Anything with node.Stored must be zero-arg cells in the graph.

One addition made while building it: the row also carries the class, as
`module:qualname`. A map of values alone cannot say what to rebuild. Values are
JSON scalars, with dates tagged as `{"__type__": "date", ...}` since
`ExpirationDate` is a stored date; anything else raises.
