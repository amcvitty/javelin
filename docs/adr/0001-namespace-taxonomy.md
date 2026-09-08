# 0001 — Namespace taxonomy for analytics objects

## Status

accepted

## Decision

Persisted `analytics` objects are named by a path under one of five fixed
prefixes — `/mkt` (market data), `/inst` (instruments), `/prod` (structured
products), `/trade` (trades), `/book` (books) — with the path below the prefix
ordered asset-class-first (`/mkt/EQ/ACME/Market`, `/inst/EQ/Option/...`,
`/trade/EQD/2026/...`). Only `/mkt` and `/inst` are implemented now; `/prod`,
`/trade` and `/book` are specified here but built later (GEN-16 children).

## Why

The names are the store's primary keys and appear inside cell keys
`(object, method, *args)`, so the naming scheme is an interface, not a
convention: changing a prefix or a nesting level later means migrating stored
rows and is not a refactor. It is worth fixing the shape once, up front, even
for the layers we have not built.

Five prefixes rather than one flat namespace because the layers have genuinely
different lifecycles and ownership — market data is calibrated and shared,
instruments are contract terms, trades add size and desk ownership, books are
organisational. A reader seeing `/trade/...` in a cell key should know what kind
of object it is without loading it.

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
