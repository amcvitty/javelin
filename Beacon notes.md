Check - member variables not working, replace with no-arg member functions. e.g.
Options.strike() and serialise these things.

seff - side effect free functions.

- parses and swaps access to ivs

```
class Demo(gromit.Object):
  @seff
  def fibonacci(self, n):
    return 1 if n < 2 else \
        self.fibonacci(n-1) + \
        self.fibonacci(n-2)
```

rewritten to code + a set of input values that are evaluated before the function is called. This allows for a dependency graph to be built and for the function to be evaluated in a side-effect free manner.

def fibonacci(**node, **ivs):
return 1 if **ivs[0] < 2 \
 else **ivs[1] + \_\_ivs[2]

ivs[0] = n # i.e. argument
ivs[1] = fibonacci(n-1) if not (n < 2) #
ivs[2] = fibonacci(n-2) if not (n < 2)

amount of memory as well um so if you if you how this decorator basically works
is a little bit under the hood it will rewrite that function into something that takes a node which is what it's evaluating and a list of input values
and so the code transformation looks kind of like that that uh you've replaced
every method reference like u s of Fibonacci of n minus one with simply an
index into an input value array and at the bottom you see what the graph U what the SEF paror infers about what the
inputs are um input number zero is just the argument one is Fibonacci of n minus
one and we also have conditionals so there are certain inputs that will not
be evaluated so if you think about setting up a dependency graph like this if you evaluate the inputs before you
enter the function you would never stop right because you would keep building the graph or you go on to Infinity so

Impliciations for exceptions https://www.youtube.com/watch?v=lTOP_shhVBQ 18:30

Actual cache is

- terminals
  - constant values, includes object instances
  - key is implicitly the value
- non-terminals
  - represents a seff invocation
  - key is (object, method, args\*)
  - inputs
    - values - leaf SEFF invocation references
    - edges - intermediate SEFF invocations. These change the shape of the graph. "compute which cell you're depending on"

    "Market" interace is a class tha aggregates teh information you carea bout at the level of an individual asset. (for eq, sotck price and impl vol. )

• Parser infers dependencies starting at known
roots (self and arguments)

- Method invocations: self.Spot()
- Compose: self.Ccy().YieldCurve()
- Mappings: [p.Price() for p in self.Positions()]
- Conditionals: self.X() if self.A() else self.B()
- Namespace refs: self.ns['/EnvPricing']
- Expressions: self.fibonacci(n-1)

```python
class FXEuropeanOption (Object) :
  @seff (STORED)
  def PairName (self): return 'EURUSD'
  @seff (STORED)
  def ExpDate (self):
  date
    _rules = self.Pair ().ExpiryDateRules ()
    today = self.ns['/PricingEnv'].CalcDate ()
    return date_rules.adjust (today, '3m')
  @seff (STORED)
  def Strike(self):
    fwd_curve = self.Pair().ForwardCurve()
    return fwd_curve[self.ExpDate ()]

  @seff
  def SpotPrice (self):
    vol = self.Pair ().VolForStrikeExp (
      self.Strike (), self.ExpDate () )
    rd = self.UnderCcy ().DF (
      self.ExpDate ())
    rf = self.OverCcy ().DF (
      self.ExpDate ())
    return opt_price (self.OptType () ,
      self.Pair ().Spot (),
      self.ExpTime (), vol, rd, rf)
```

# Bindings - Imperative scenarios

```python
P = o.Price()
with gromit.do_bind():
    o.Pair().Spot.bind(o.Pair().Spot() + le - 4)
    P_up = o.Price()

p = p.Price()
with gromit.do_bind():
    p.ns["/EnvPricing"].bind
    p1 = p.Price()
    dates(rel="-1b")
```

# Filter graph

```python
spot._deps = gromit. filter(
  p.Price,
  method_is = FXCcyPair.Spot)
p0 = p.Price ()
p1s = []
for dep in spot_deps:
  with gromit.do_bind() :
    dep.bind (dep () +1e-4)
    pls.append (p.Price ()
```
