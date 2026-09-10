# Context: beacon-clone

An Excel-style calculation engine, and a quant pricing library built on it. Two
layers of vocabulary live here, and this file is the one home for both: the
**engine** terms the `graph` package defines, and the **analytics** terms the
`analytics` package and the namespace taxonomy add on top.

## Language — engine

**node**:
A method decorated with `@node`. Compiled once, when its class is created.

**cell**:
One *invocation* of a node on an object. `fib(5)` and `fib(4)` are different
cells of the same node.

**key**:
How a cell is identified: the flat tuple `(object, method, *args)`.

**terminal**:
An input that needs no computing — a node's own argument, whose value the key
already carries.
_Avoid_: leaf, literal.

**`ivs`**:
The input-value array a compiled body reads in place of its parameters and its
node calls. One slot per input.

**`Input`**:
What fills one `ivs` slot: where it sits, and what resolving it reads.
`Value`, `Edge` and `Local` are the three kinds.

**`Value`**:
The input kind that is one of the cell's own arguments — a terminal.

**`Edge`**:
The input kind reached by calling a method on an object the graph produced. How
many cells one call site names is left to `CallEdge` and `MapEdge`.

**`CallEdge`**:
An `Edge` naming exactly one cell.

**`MapEdge`**:
An `Edge` naming one cell per element of a collection — what a comprehension
compiles to.

**`Local`**:
The input kind that is a body intermediate hoisted above the body. It fills a
slot without being a dependency of its own.

**guard**:
The condition under which a call site is reached. An unconditional call site
has none.
_Avoid_: condition, predicate, filter.

**expansion**:
Working out which cells a cell depends on without running any body. What
evaluation is not.

**`reads`**:
Per input: the slots that resolving *that one* input reads, closed through any
hoisted locals among them.

**`needed`**:
Every slot expansion has to evaluate for a node — the union of its edges'
`reads`.

**override**:
A value set on a cell directly, shadowing its body so the body never runs.

**dirty**:
A cell whose memoised value is stale because something it depends on changed.

**diddle**:
A scope in which overrides are temporary: leaving it restores what was
displaced rather than recomputing.
_Avoid_: bump, shift, scenario, what-if.

## Language — analytics

### Namespace taxonomy

Every persisted object has a name that is a path under one of six prefixes.
The prefix says what kind of thing it is; the rest of the path is
asset-class-first (`EQ`, `IR`, `EQD`, ...), then narrower. Names are store keys,
so the scheme is effectively an interface — see `docs/adr/0001`.

**`/mkt`**:
Market data — the observable or calibrated inputs to pricing: spots, curves,
vol surfaces, and the valuation environment. Example: `/mkt/EQ/ACME/Market`,
`/mkt/IR/USD/Curve`, `/mkt/ENV/Default`.
_Avoid_: reference data, static data.

**`/inst`**:
Instrument — one priceable contract with economic terms but no size or
direction. An option, a swap, a single leg. Its `pv()` is per unit. Example:
`/inst/EQ/Option/ACME-C100-21AUG2031`.
_Avoid_: security, product.

**`/prod`**:
Structured product — a composition of instrument legs into one payoff, with the
per-leg weights held on the product, not the instrument. Not yet implemented
(see `docs/adr/0001` and GEN-16 children). Example: `/prod/EQ/CPN/ACME-70PCT-2031`.
_Avoid_: basket, portfolio, structure.

**`/pos`**:
Position — a net holding: an instrument or product plus a size and a direction,
carried as one **signed** `quantity`. A standing state, not an event: no price,
timestamp or counterparty. Its direction is **long or short**, never bought or
sold — buying and selling are events, and events are `/trade`. Example:
`/pos/EQD/exotics/NOTE-0001`.
_Avoid_: booking, ticket.

**`/trade`**:
Trade — a discrete transaction at a point in time: an instrument, a direction, a
price, a timestamp, a counterparty. A historical fact, as opposed to the net
holding it contributes to. Not yet implemented (see GEN-33). Example:
`/trade/EQD/2026/FILL-0001`.
_Avoid_: fill, execution.

**`/book`**:
Book — a named collection of position paths, held as stored state so that
membership is a graph input. Example: `/book/EQD/exotics/london`. See
`docs/adr/0002-book-representation.md`.
_Avoid_: portfolio, folder, blotter.

### Pricing

**Market**:
The `/mkt/EQ/<ticker>/Market` object: the per-asset aggregate of everything
pricing needs for one underlying — its `spot` and its `vol`. One object per
underlying.
_Avoid_: quote, feed, snapshot.

**DiscountCurve**:
The `/mkt/IR/<ccy>/Curve` object: turns a year fraction into a discount factor.
Currently **flat** — one stored `rate`, `discount_factor(t) = exp(-rate * t)`.
Term-structure interpolation is future work.
_Avoid_: yield curve, rate curve, term structure.

**PricingEnv**:
The `/mkt/ENV/Default` object: the shared valuation context. Holds `Today`, the
one valuation date the whole graph agrees on. Stored, so it is set or diddled
rather than read from the wall clock.
_Avoid_: pricing environment (spelled out), context, as-of.

**EuropeanOption**:
An `/inst` instrument: a call (puts are a one-guard extension, not built) on one
underlying, exercised only at expiry. Priced by Black-Scholes off the `Market`,
`DiscountCurve` and `PricingEnv` it reaches through the namespace.

**leg**:
One instrument inside a composition. A leg carries no weight of its own; the
weight lives on the `/prod` that composes it.

**tenor**:
The year fraction from `PricingEnv.Today` to an instrument's expiry, ACT/365.
Not a node — a derived intermediate, hoisted as a `Local` where it feeds a
node-call argument.
_Avoid_: term, time to expiry, maturity.

**forward**:
The underlying's expected price at expiry under the pricing measure:
`spot * exp(rate * tenor)` (no dividends). A node on the instrument.

**greeks by diddle**:
Computing a sensitivity by bumping an input inside a `diddle` scope, repricing,
and letting scope exit restore — `delta = (up - down) / 2h`. The test of this
repo: the bump dirties exactly the cells downstream of the bumped input, and
scope exit recomputes nothing.
_Avoid_: bump-and-revalue, finite-difference greeks, shift.
