# 0001 — Namespace taxonomy for analytics objects

## Status

accepted

## Decision

Persisted `analytics` objects are named by a path under one of six fixed
prefixes — `/mkt` (market data), `/inst` (instruments), `/prod` (structured
products), `/pos` (positions), `/trade` (transactions), `/book` (books) — with
the path below the prefix ordered asset-class-first (`/mkt/EQ/ACME/Market`,
`/inst/EQ/Option/...`, `/pos/EQD/exotics/...`). `/mkt`, `/inst`, `/pos` and
`/book` are implemented; `/prod` is specified here but built later (a GEN-16
child), and `/trade` is reserved for the transaction layer (GEN-33). How
`/book` and `/pos` are shaped is `docs/adr/0002`.

## Why

The names are the store's primary keys and appear inside cell keys
`(object, method, *args)`, so the naming scheme is an interface, not a
convention: changing a prefix or a nesting level later means migrating stored
rows and is not a refactor. It is worth fixing the shape once, up front, even
for the layers we have not built.

Six prefixes rather than one flat namespace because the layers have genuinely
different lifecycles and ownership — market data is calibrated and shared,
instruments are contract terms, positions add size and desk ownership, books are
organisational. A reader seeing `/pos/...` in a cell key should know what kind
of object it is without loading it.

Positions and transactions are separate prefixes because they are separate
kinds of thing: a position is a standing net holding, a trade is a dated event.
Naming a holding `/trade` was the original mistake this taxonomy inherited, and
it closed off the word for the layer that should own it (GEN-31, GEN-33).

## Considered and rejected

- **Flat names / GUIDs only** (what `ns.new` still does by default): fine for
  throwaway objects, but gives no way to look up "the USD curve" or "ACME's
  market" by a stable name, which cross-object nodes need.
- **Product-type-first** (`/EQ/mkt/...`): puts the least stable discriminator
  (asset class taxonomy) outermost and scatters each layer across the tree.

## Consequences

- `/inst` and `/prod` names are *conventionally* economic
  (`ACME-C100-21AUG2031`) but not machine-checked against the object's stored
  contract terms. A computed `identity()` that derives the canonical name from
  the terms, and reconciles the two, is future work (GEN-16 child).
- `analytics` depends on `ns`, which depends on `graph`; nothing lower imports
  `analytics`.
