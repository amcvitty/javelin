# Context: beacon-clone

Two layers of vocabulary live here. The **engine** terms (node, cell, key,
terminal, `Value`, `Edge`, `Local`, guard, `ivs`, `needed`, override, dirty,
diddle) are defined in the README's "Vocabulary" table and are not repeated
here. This file covers the **quant / analytics** domain that the `analytics`
package builds on top of the engine, and the namespace taxonomy that organises
persisted objects.

## Language — namespace taxonomy

Every persisted object has a name that is a path under one of five prefixes.
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
_Avoid_: security, product, position.

**`/prod`**:
Structured product — a composition of instrument legs into one payoff, with the
per-leg weights held on the product, not the instrument. Not yet implemented
(see `docs/adr/0001` and GEN-16 children). Example: `/prod/EQ/CPN/ACME-70PCT-2031`.
_Avoid_: basket, portfolio, structure.

**`/trade`**:
Trade — an instrument or product plus a size and a direction (bought/sold).
Not yet implemented. Example: `/trade/EQD/2026/NOTE-0001`.
_Avoid_: position, booking, ticket.

**`/book`**:
Book — a named collection of trade paths. Not yet implemented. Example:
`/book/EQD/exotics/london`.
_Avoid_: portfolio, folder, blotter.

## Language — pricing

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
