# beacon-clone

An Excel-style calculation engine in Python. A method decorated with `@node` is
a cell in a spreadsheet: it has a value, and the engine knows what that value
depends on **before** computing any of it.

This is a reimplementation of the "grommit" dependency graph from
Beacon/Clearwater, worked out from their public description. `graph` is the
engine; `ns` puts named objects on top of it, so cells on one object can depend
on cells on another and be persisted.

```python
class Sheet:
    @node
    def fib(self, n):
        return n if n < 2 else self.fib(n - 1) + self.fib(n - 2)


sheet = Sheet()
graph.deps(sheet.fib, 6)  # {(sheet, fib, 5), (sheet, fib, 4)} -- nothing ran
sheet.fib(6)  # 8, evaluating fib(1) first and each cell once
```

## The one idea that matters

**Dependencies are found statically, without running anything.** Everything in
the codebase exists to preserve that property. If you are changing this project,
this is the invariant to protect.

Naively you cannot do this: `self.fib(n - 1)` names a different cell for every
`n`, and you cannot know which without evaluating `n - 1`. And you cannot simply
evaluate all of a function's inputs before entering it, because `fib` would
expand forever.

The resolution is a source rewrite. At class-creation time each node's body is
rewritten into a pure function of an input-value array, `ivs`, and each thing
that fills a slot in that array is recorded separately:

What you wrote:

```python
@node
def fib(self, n):
    return n if n < 2 else self.fib(n - 1) + self.fib(n - 2)
```

What gets compiled — a body that reads only `ivs`, plus one input spec per slot
(`graph.code(Sheet.fib)` and `graph.inputs(Sheet.fib)` print exactly this):

```text
def fib(self, node, ivs):
    return ivs[0] if ivs[0] < 2 else ivs[1] + ivs[2]

ivs[0] = n                              <- Value, a terminal (the argument)
ivs[1] = self.fib(n - 1) if not n < 2   <- Edge, guarded
ivs[2] = self.fib(n - 2) if not n < 2   <- Edge, guarded
```

Two things fall out of this:

1. To find dependencies, walk the inputs and evaluate only their **argument
   expressions** and **guards** — never the body. `deps(sheet.fib, 6)` computes
   `n - 1` and `n - 2` and stops.
2. The **guard** (`if not n < 2`) is what makes recursion terminate. For
   `fib(1)` the guard is false, so neither edge is a dependency at all, and
   expansion bottoms out.

Evaluation then follows the graph rather than the call stack: a body cannot run
until its `ivs` are filled, and each slot is a memoised cell, so `fib(5)` runs
the bodies in the order `1, 0, 2, 3, 4, 5`.

## Vocabulary

Every term this project uses is defined in [CONTEXT.md](CONTEXT.md) — the engine
ones (node, cell, key, `ivs`, `Edge`, guard, `reads`, `needed`, diddle, ...)
under "Language — engine", the pricing and namespace ones under "Language —
analytics". The rest of this README explains how the engine works and assumes
those words; it does not redefine them.

## When an edge's shape depends on a value

Usually resolving dependencies needs no values at all. Sometimes it needs a few:

```python
@node
def pick(self, n):
    return self.fib(n) if n > self.threshold() else 0
```

Deciding whether `self.fib(n)` is a dependency requires knowing
`self.threshold()`. So `threshold` must be evaluated during expansion, while
`fib` must not be. Each input records the slots resolving *it* reads — the
`self.fib(n)` edge reads `{0, 1}`, the parameter and `threshold` — and
`CompiledNode.needed` is the union over the edges, which is what expansion
evaluates. `deps(pick, 5)` is `{threshold, fib(5)}`; `deps(pick, 1)` is
`{threshold}`.

A read set is closed transitively through hoisted locals: reading a local's slot
means evaluating it, which means reading whatever it reads. Edges are not
followed — an edge in a read set is resolved for its cell, not opened up. The
union is taken over the edges alone, so a local that nothing shape-forming
reads stays out of `needed` and is left to evaluation.

Keeping the sets per input, rather than only their union, is what lets a single
call site be expanded on its own — its own closure is usually far smaller than
everything `needed` covers:

```python
cell = graph.cell(book.total.key(True))
cell.slots[3].cells  # resolved already: its closure reaches no edge
cell.slots[4].blocked_by  # {3} — this one would cost an evaluation
cell.expand_slot(4)  # pay for that one slot, and nothing else
```

`expand_slot` records nothing. Only `expand`, which takes every slot at once,
writes to the dependency map — so a cell can never be left looking as though it
had fewer dependencies than it has.

This is the "edges change the shape of the graph" case: computing which cell you
depend on is itself a graph computation.

## Setting values

A cell can be given a value directly. Its body then never runs, and everything
downstream of it is marked dirty and recomputed on demand — nothing else is.

```python
p.pv()  # 20.0
p.spot.set_value(110.0)
p.pv()  # 40.0, recomputing only payoff and pv
p.spot.clear_value()  # back to 20.0
```

`set_value(value, args=())` takes the value first; `args` names *which* cell for
a node that takes parameters, so `sheet.fib.set_value(2.0, args=(0,))` sets
`fib(0)` alone.

Dirtying walks dependency edges backwards. The graph only stores forward edges,
so `_deps` is inverted in a single pass each time a value is set. That costs
O(edges) per set but keeps the graph's mutable state small, which matters for
the next part. The walk **stops at a cell that has its own override**: such a
cell's value cannot change, so nothing behind it is stale.

An overridden cell reports no dependencies — its body will never run, so it
depends on nothing. Its dependents still list it, and clearing the override
brings its real dependencies back.

### Diddle scopes

`diddle()` makes overrides temporary:

```python
with diddle((md.spot, 110.0), (call.strike, 95.0)):
    note.pv()  # sees the overrides
note.pv()  # pre-diddle value, straight from the restored cache
```

Each entry is a bound node followed by the arguments `set_value` takes, so
`(sheet.fib, 5.0, (3,))` is the parameterised form; entries are exactly
shorthand for calling `set_value` inside the block.

**Leaving a diddle restores; it does not recompute.** A scope is a snapshot
dictionary, not a redo log. Before any mutation touches a key — an override
being set, a dirty flag raised, a value memoised — `_touch` records that key's
value, deps, dirty flag and override into the innermost open scope, first write
wins. Exit writes those four fields back, deleting where the snapshot says the
key was absent.

One mechanism therefore covers everything exit has to undo: values the diddle
invalidated come back, values computed *under* the diddle are dropped, and
overrides revert to whatever the enclosing scope had. That last one is why
nesting needs no special case — an inner scope restores exactly the state the
outer scope had produced, so the outer scope's own snapshots stay valid.

Because dependency edges are snapshotted alongside values, a diddle that changes
the *shape* of the graph (through `needed`, above) is restored too, not just the
numbers in it.

The mutating methods on a bound node — `set_value`, `clear_value`, `is_dirty` —
act on the default graph, as `__call__` does. Drive another `Graph` through
`set_value(key, value)` and `diddle(...)` on the instance itself.

## Depending on other objects

A cell key is `(object, method, *args)`, so cells on different objects were
never a problem — what was missing was a way for an *edge* to name an object
other than `self`. `Edge.receiver` is that: a compiled lambda returning the
object to call `target` on.

```python
@node
def Strike(self):
    return self.EquityObj().StockPrice()
```

```text
ivs[0] = self.EquityObj()               <- Edge, receiver self
ivs[1] = self.EquityObj().StockPrice()  <- Edge, receiver ivs[0]
needed = {0}
```

Resolving *which object* is the same problem as resolving an edge's arguments,
and uses the same machinery: the receiver expression is rewritten to read `ivs`,
and the inputs it reads go into the edge's `reads` — and so into `needed`, so
expansion evaluates them. Finding `Strike`'s dependencies runs `EquityObj` — it
has to, that is what names the cell — but not `StockPrice`.

**Which calls become edges.** Any call whose receiver expression reads `self`.
The receiver is resolved during expansion and then, if the attribute is a node,
the input is a dependency; if it is not, it is an ordinary call:

| Written | Becomes |
|---|---|
| `self.fib(n - 1)` | edge, receiver `self` |
| `self.helper()`, where `helper` is not a node | left in the body |
| `self.Market().spot()` | edge on the other object |
| `self.ns['/Equities/ABC'].spot()` | edge on the looked-up object |
| `self.Ticker().upper()` | edge's receiver is a cell; `.upper()` is a plain call |
| `datetime.date.today()` | untouched |

Because the receiver is an input like any other, it inherits the guard at its
call site: inside an `if` that does not hold, neither the receiver nor the cell
it names is a dependency.

`self.ns` is the one member variable a node may read. It is permitted by name in
`rewriter.PERMITTED_MEMBER` — `graph` does not import the `ns` package, so the
layering is unchanged.

## Stored nodes and the namespace

The `ns` package puts objects in a namespace and persists them.

```python
class EquityMarket(McObject):
    @node(node.Stored)
    def StockPrice(self):
        return 25.0


mkt = ns.lookup_or_new("/Equities/ABC", EquityMarket, StockPrice=20.0)
mkt.store()
```

- `@node(node.Stored)` marks a node as the object's persisted state. A stored
  node **takes no parameters**: what is persisted is a cell, and only a zero-arg
  node has one cell per object.
- A `Namespace` is an **identity map** — one instance per name. A cell key holds
  the object itself, so two instances for one name would fork the graph.
- Keyword arguments to `new`/`lookup_or_new` are `set_value` calls, applied over
  the class default or over what was loaded.
- `store()` evaluates every stored node and writes the row: name, class, and a
  JSON map of values. Loading sets those cells, so a reloaded object's bodies
  never run and its stored cells have no dependencies.

See [example_namespace.py](example_namespace.py) for the whole thing running.

## Worked example: an option pricer

The `analytics` package puts a real Black-Scholes pricer on top of all of this.
Market data and instruments are `McObject`s in the namespace, so pricing is an
ordinary graph computation and a greek is a `diddle`.

```python
mkt = ns.lookup_or_new("/mkt/EQ/ACME/Market", Market, spot=100.0, vol=0.2)
ns.lookup_or_new("/mkt/IR/USD/Curve", DiscountCurve, rate=0.03)
ns.lookup_or_new("/mkt/ENV/Default", PricingEnv)
a = ns.lookup_or_new("/inst/EQ/Option/ACME-C95", EuropeanOption, strike=95.0)
b = ns.lookup_or_new("/inst/EQ/Option/ACME-C105", EuropeanOption, strike=105.0)
```

`a.pv()` is Black-Scholes: `forward → d1 → d2 → price`, with the option reaching
`spot` and `vol` off the shared `Market`, `rate` off the `DiscountCurve`, and
the valuation date off the `PricingEnv` — all by name. `tenor` (year fraction
to expiry) is a hoisted `Local`: it reads only edges and feeds the node-call
argument `curve().discount_factor(tenor)`, the pattern the engine was taught in
["Intermediate locals"](#intermediate-locals).

The point is the greek. Bump spot inside a `diddle`, reprice, let the scope
restore:

```python
s0, h = mkt.spot(), 1e-4 * mkt.spot()
with graph.diddle((mkt.spot, s0 + h)):
    up = a.pv() + b.pv()
with graph.diddle((mkt.spot, s0 - h)):
    down = a.pv() + b.pv()
delta = (up - down) / (2 * h)  # == N(d1_a) + N(d1_b), to 1e-6
```

`tests/test_greeks_by_diddle.py` asserts the two things that matter: entering
the bump recomputes **exactly** `{forward, d1, d2, pv}` on each leg and nothing
on the shared market data, and leaving the scope recomputes **nothing**.

The pricer is flat where flatness costs nothing to prove: one `rate`, one
`vol`. A term structure and a vol surface, a `/prod` composition layer, and the
`/trade` transaction layer are tracked as follow-ups.
See [CONTEXT.md](CONTEXT.md) and
[docs/adr/0001-namespace-taxonomy.md](docs/adr/0001-namespace-taxonomy.md) for
the object naming scheme, and [example_pricer.py](example_pricer.py) for the
whole thing running.

## Looking at a cell: the graph browser

Everything the engine knows about one cell can be put on screen without
running any of it:

```python
from tui.graph_browser import show_node

show_node(book.pv, True)
```

A header card says what the cell is and what it is currently worth, a table
lists every `ivs` slot -- its kind, the cell it names, that cell's value, the
guard it sits under and the slots resolving it reads -- and a second table
lists the cells known to read it. A slot nothing has looked at says `not yet
resolved` rather than guessing, which is a different answer from a call site
its guard blocks; a map edge fans out to a row per element once resolved.

The terminal library is an optional extra, so installing the engine still
acquires nothing:

```
uv sync --extra tui
python -m tui.graph_browser   # the demo in example_browser.py
```

`tui.graph_browser` imports `graph`; `graph` never imports `tui`, and its own
tests pass in an install without the extra.

## Layout

```
graph/
  ir.py         Input (Value, Edge -> CallEdge/MapEdge, Local), Call, CompiledNode
  rewriter.py   Guard, GuardStack, RawEdge, RawLocal, Rewriter -- the AST transform
  compiler.py   compile_node(): source -> CompiledNode
  runtime.py    make_key(), Graph, DEFAULT -- cells, deps, values, diddles
  node.py       Node descriptor, BoundNode, @node
  __init__.py   public API, bound to the default Graph

ns/
  mcobject.py   McObject -- a named object that can be persisted
  namespace.py  Namespace, DEFAULT -- objects by name
  store.py      SqliteStore and the JSON codec
  __init__.py   public API, bound to the default Namespace

analytics/
  blackscholes.py  pure Black-Scholes maths, no graph import
  market.py        Market, DiscountCurve, PricingEnv -- the /mkt objects
  instrument.py    EuropeanOption -- the /inst objects
  __init__.py      public API

tui/
  __init__.py       a home for terminal tools; imports nothing itself
  graph_browser/
    render.py     what a cell looks like, as plain data -- no terminal import
    app.py        the terminal application: the only module importing textual
    __main__.py   python -m tui.graph_browser: the demo at example_browser.py
    __init__.py   show_node()
```

`analytics` depends on `ns`, `ns` depends on `graph`; imports never run the
other way. `tui` sits outside that stack and depends on `graph` alone.

Imports run one way, `compiler -> ir <- runtime`, with `node` on top:

- **`compiler`** holds everything that happens once per class. `compile_node`
  reads the source with `inspect.getsourcelines`, rewrites the AST, then builds
  a `__make` factory containing the rewritten body plus three lambdas per edge
  (its receiver, its args, its guard) and `exec`s it. The factory exists so
  those lambdas close over the *original method's* free variables. Inside it the
  body is renamed to `__impl`: keeping the node's own name would shadow a free
  variable called the same thing.
- **`runtime`** holds everything that happens per cell. `Graph.expand` walks
  inputs for dependencies; `Graph.evaluate` walks them for values too. Both go
  through `_run_inputs`.
- **`node`** wires them together. `Node` is a descriptor: `__set_name__` fires
  once the class body is complete, which is why a node may reference one defined
  later in the class, and why mutual recursion works. Accessed on an instance it
  gives a `BoundNode` rather than a `types.MethodType`, because a bound method
  has nowhere to hang `set_value`. It keeps the names `__self__` and `__func__`,
  so anything duck-typing on a bound method still works.

`Rewriter` needs to know what counts as a node, but `node.py` needs the
compiler. The cycle is broken by passing an `is_node` callable into
`compile_node`.

### Where state lives

Two registries with deliberately different lifetimes:

- **Compilation** is write-once per class and lives on the descriptor, as
  `Node.compiled`.
- **Cells** live in a `Graph`: `_deps` (expanded), `_known` (referenced),
  `_values` (memoised), `_overrides` (set directly), `_dirty` (stale) and
  `_layers` (open diddle scopes). `graph.deps(...)` and friends use the
  module-level `DEFAULT`; construct `Graph()` for an isolated one.

Overrides and dirty flags are runtime state, in the graph — never on the `Node`.
A node is compiled once and is then read-only, so two graphs can diddle the same
class independently.

Dependencies are held in the graph namespace rather than on the functions that
define them — that was an original design requirement, so that the graph can be
explored (`graph.all_nodes()`, `graph.deps(fn)`) independently of the code.

## Guards, and how to break them

`GuardStack` tracks the conditions in force at each point in the body. Guards
come from `if`/`else`, ternaries, `and`/`or` short-circuits, and **early
returns** — statements after `if n < 2: return n` are guarded by `not n < 2`.

Each guard is a `Guard(original, rewritten)` pair: `original` is in terms of the
node's parameters and is only ever shown to humans, `rewritten` is in terms of
`ivs` and is what gets compiled.

The pair survives compilation: an `Edge` carries `guard`, the compiled
predicate, and `guard_source`, the readable text. `str(edge)` puts the call site
and its guard back together, so keeping them in separate fields costs nothing at
the point of reading and lets a tool show guard status in a column of its own.

`GuardStack.scope()` captures the stack depth **on entry** and truncates to it on
exit. This matters: an earlier version removed a *count* of guards instead, so a
guard pushed mid-block by an early return corrupted the accounting and produced
`n > 0 and (not n > 0)` — a dependency that was silently dropped and a node that
returned `None`. The graph was wrong, not loud. See
`test_guards_do_not_leak_out_of_a_nested_block`.

## Intermediate locals

Inputs are hoisted above the body, so an input expression cannot read a body
local. But a plain intermediate can be hoisted too, if its right-hand side only
uses things an input may already use:

```python
@node
def price(self):
    tenor = self.expiry() / 2.0  # hoisted: reads an earlier input
    return self.curve().discount(tenor)  # ...so it can fill this argument
```

`tenor` becomes a third input kind alongside `Value` and `Edge` — a `Local`,
carrying a `(self, node, ivs)` lambda and no dependency of its own. It takes an
`ivs` slot in source order, and later inputs (arguments, guards, receivers, and
other locals) refer to it as `ivs[k]`. `graph.inputs(...)` lists it as
`tenor = self.expiry() / 2.0`; `graph.code(...)` shows the body reading `ivs[k]`
with the assignment gone.

An assignment is hoisted only when it is a single bare `name =` target, bound
exactly once in the whole body, and reached unconditionally. Anything else — a
name that is rebound, one assigned under an `if`, a tuple unpack, or a
right-hand side that reads a local which itself could not be hoisted — stays in
the body, and a node call whose argument uses it still raises. `needed` is
widened transitively through hoisted locals, so a local an edge's shape depends
on is still evaluated during expansion, and a diddle that changes such a local
restores the graph shape on exit like any other.

## Comprehensions

A book is a collection of positions, and its PV is the sum of theirs. That is one
call site naming *many* cells — as many as the book has members, which is not
known until the member list has been evaluated:

```python
@node
def pv(self):
    return sum(self.ns[path].pv() for path in self.position_paths())
```

The whole comprehension becomes one input — a `MapEdge` — and one `ivs` slot
holding the results as a list. The rewritten body never loops:

```
ivs[0] = self.position_paths()                          <- CallEdge
ivs[1] = (self.ns[path].pv() for path in ivs[0])        <- MapEdge, over ivs[0]
needed = {0}
return sum(ivs[1])
```

`MapEdge.over` produces the collection; `receiver` and `args` take the element
as a fourth parameter, named after the comprehension's own loop variable, so the
loop variable needs no rewriting — `self.ns[path]` compiles to a lambda of
`(self, node, ivs, path)`. That is what lets a book hold *names* rather than
objects, which is why it is the shape `analytics.Book` uses (see
`docs/adr/0002-book-representation.md`).

Expansion evaluates the collection, because that is what says how many cells
there are — but not the elements' values, which it does not need to name them.
So `graph.deps(book.pv)` runs `position_paths` and nothing below it.

**What a comprehension may contain.** One `for` clause, no `if` filter, and an
element that is exactly one node call. A list comprehension and a generator
expression compile identically; a set comprehension is rejected because it would
silently drop cells whose values happen to be equal, and a dict comprehension
because it is not one list of cells.

| Written | Becomes |
|---|---|
| `[p.pv() for p in self.Positions()]` | map, receiver is the element |
| `[self.ns[p].pv() for p in self.Paths()]` | map, receiver built from the element |
| `[p.pv() * 2 for p in self.Positions()]` | raises — the element must be the call |
| `[p.pv() * p.size() for p in self.Positions()]` | raises — one node call, not two |
| `[p.pv() for p in self.Positions() if p.live()]` | raises — no filter yet |
| `[r * 2 for r in self.Rates()]` | plain code over one edge's value |

The two that raise are asking for a node on the element that combines them —
`t.weighted_pv()` — which is better modelling anyway. A loop-invariant call can
be hoisted into an assignment above the comprehension instead.

Every element must resolve the same way. A collection whose members' targets are
all nodes gives one dependency each; one where none are gives plain calls and no
dependencies; a *mixed* one raises `TypeError` when it resolves, because
contributing dependencies for some members and silently not for others is
exactly the half-connected graph this layer exists to prevent.

## Deliberately unsupported

These raise `ValueError` when the class is created, rather than building a wrong
graph. Adding support for any of them means answering "what is the fixed list of
inputs?" first.

| Pattern | Why |
|---|---|
| Node call in a loop or lambda | Not one call site, so not one input. A comprehension *is* supported — see above. |
| A comprehension with a filter, two `for` clauses, or more than one node call | One input names one collection of cells; see the table above for what to write instead. |
| `self.x` member variables, except `self.ns` | A node may only see functions and constants. |
| `self` used as a value | Would smuggle member access out to a helper. |
| Node call argument using a non-hoistable local | Inputs are hoisted; a local that is rebound, conditional, or reads another such local cannot come with them (see above). |
| Rebinding a parameter | Parameters are read-only inputs. |
| A stored node with parameters | What is persisted is one cell per object. |
| `async def`, `*args`/`**kwargs` at a call site | Not modelled. |

Also not supported: unhashable arguments, and a node reached through anything
that does not read `self` and is not a comprehension's element — `other.a()`,
where `other` is a local or a global, stays inline as plain code.

Because compilation reads the method's own source, a node must be defined
somewhere `inspect.getsourcelines` can find it. Classes defined in a REPL or
piped into `python` from stdin fail at decoration with `OSError: could not get
source code`.

## Working on this

```
uv run ruff format      # standardise formatting
uv run ruff check --fix # lint
uv run ty check         # types
uv run pytest -q        # 158 tests
```

Tests mirror the packages, one folder each:

```
tests/graph/     test_rewrite (the transform and its rejections), test_deps
                 (graph shape), test_eval (order and memoisation), test_api
                 (decorator surface), test_set_value (overrides and dirtying),
                 test_diddle (scoped overrides), test_cross_object (edges
                 reaching other objects), test_stored (the Stored marker)
tests/ns/        test_namespace, test_store
tests/analytics/ test_blackscholes (the pure maths), test_market and
                 test_instrument (the /mkt and /inst objects),
                 test_greeks_by_diddle (the recompute-set artefact)
tests/tui/graph_browser/
                 test_render (what is shown, without a terminal), test_app
                 (the application, driven headless), test_packaging (the
                 extra stays optional)
```

Shared class factories are in `tests/helpers.py`; each test builds its own
classes so nothing leaks between them, and the autouse `fresh_graph` fixture
(in `tests/conftest.py`, so it covers every folder) clears the default graph,
namespace and store (`graph.clear()`, `ns.clear()`, `ns.clear_store()`).

The exception is the `McObject` classes in `helpers.py`, which are module level
on purpose: a stored row names the class to rebuild, and a class defined inside
a test function cannot be found again by that name.

The single most valuable assertion in the suite is in
`test_deps_are_known_without_evaluating`:

```python
graph.deps(f.fib, 6)
assert evaluated == []  # deps must never run a body
```

If a change makes that fail, the design has been lost regardless of what else
still passes.

Its counterpart for mutation is in
`test_leaving_a_diddle_restores_rather_than_recomputes`:

```python
with graph.diddle((p.spot, 110.0)):
    p.pv()
evaluated.clear()
p.pv()
assert evaluated == []  # exiting a diddle must restore, not recompute
```
