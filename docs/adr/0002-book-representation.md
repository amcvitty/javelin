# 0002 — A book is a stored list of trade paths

## Status

accepted

## Decision

A `/book` object holds its membership as one stored node returning a list of
`/trade` path strings, and prices by aggregating a comprehension over that list:

```python
class Book(McObject):
    @node(node.Stored)
    def trade_paths(self):
        return []

    @node
    def pv(self):
        return sum(self.ns[path].pv() for path in self.trade_paths())
```

Membership is stored state, not derived from the store. A trade's direction is a
signed `quantity`, not a separate enum. Each member becomes a real graph
dependency of `pv` through a `MapEdge` — one call site, one cell per element.

## Why

Names are the store's primary keys (`docs/adr/0001`), so a path is the only
thing about a trade that is stable enough to persist inside another object. A
list of paths reloads without loading the trades themselves, and resolving one
through `self.ns[path]` is an ordinary cross-object edge, so the graph dirties a
book's `pv` when anything under any of its trades moves.

Storing membership rather than deriving it is what makes it an *input*. A
derived book — "every trade whose desk is london" — would be a function of the
store's contents, and the store is not a cell: adding a trade would leave every
book's `pv` memoised and stale, with nothing to dirty it. Stored membership
makes adding a trade a `set_value` on `trade_paths`, which propagates like any
other change.

Signed `quantity` because a `quantity` plus a `direction` enum is two fields that
can contradict each other — a trade that is `Sold` with a negative size has no
defined meaning, and nothing in the type system stops one being written. A
human-facing bought/sold label is a derived node if it is ever wanted.

## Considered and rejected

- **Holding trade objects rather than paths.** A stored list of live objects has
  no persistable form; the store would have to inline or re-reference them, and
  the "re-reference by name" case is just this decision with extra steps.
- **Membership on the trade** (each trade names its book, book membership found
  by scanning): puts the edge the wrong way round for the graph — a book's
  dependencies would not be knowable from the book, and expansion would have to
  scan the store.
- **Nested books instead of a separate portfolio layer.** Rejected only for now:
  a book of books needs no new machinery, since the fan-out recurses, but the
  taxonomy in `docs/adr/0001` gives `/book` one meaning and a portfolio layer can
  be added above it without changing this decision.

## Consequences

- `graph.deps(book.pv)` evaluates the member list, because that is what says how
  many cells there are — but not the trades themselves, which it does not need in
  order to name them. Expansion of a book therefore costs one cell, not the
  subtree: the same rule that already applies to a composed edge's receiver.
- A member that cannot be priced raises rather than being skipped: the
  comprehension has no `if` filter yet, and a `MapEdge` requires every element to
  resolve the same way (all cells, or all plain calls). Fixing the data or giving
  the odd instrument a `pv` node are the two available answers.
- Membership is not machine-checked against the store: `trade_paths` may name a
  path that does not resolve, which fails at expansion rather than at write time.
