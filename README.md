# beacon-clone

An Excel-style calculation engine in Python. A method decorated with `@node` is
a cell in a spreadsheet: it has a value, and the engine knows what that value
depends on **before** computing any of it.

This is a reimplementation of the "grommit" dependency graph from
Beacon/Clearwater, worked out from their public description.

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

| Term | Meaning |
|---|---|
| **node** | A method decorated with `@node`. Compiled once, when the class is created. |
| **cell** | One *invocation* of a node on an object: `fib(5)` and `fib(4)` are different cells. |
| **key** | How a cell is identified: the flat tuple `(object, method, *args)`. |
| **terminal** | A constant. The node's own arguments; the key is implicitly the value. |
| **`Value`** | An input that is one of the cell's arguments — a terminal. |
| **`Edge`** | An input that is another cell. Carries `args` and `guard` as compiled `(self, node, ivs)` lambdas. |
| **guard** | The condition under which a call site is reached. `None` means unconditional. |
| **`ivs`** | The input-value array a compiled body reads instead of parameters and node calls. |
| **`needed`** | Indices whose *values* a later input reads (see below). |
| **override** | A value set on a cell directly, shadowing its body. |
| **dirty** | A cell whose memoised value is stale because something it depends on changed. |
| **diddle** | A scope in which overrides are temporary, and undoing them is a restore. |

## When an edge's shape depends on a value

Usually resolving dependencies needs no values at all. Sometimes it needs a few:

```python
@node
def pick(self, n):
    return self.fib(n) if n > self.threshold() else 0
```

Deciding whether `self.fib(n)` is a dependency requires knowing
`self.threshold()`. So `threshold` must be evaluated during expansion, while
`fib` must not be. `CompiledNode.needed` records exactly which input indices
some later argument expression or guard reads — here `{0, 1}` — and expansion
evaluates only those. `deps(pick, 5)` is `{threshold, fib(5)}`; `deps(pick, 1)`
is `{threshold}`.

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

## Layout

```
graph/
  ir.py         Value, Edge, CompiledNode -- the compiled form
  rewriter.py   Guard, GuardStack, RawEdge, Rewriter -- the AST transform
  compiler.py   compile_node(): source -> CompiledNode
  runtime.py    make_key(), Graph, DEFAULT -- cells, deps, values, diddles
  node.py       Node descriptor, BoundNode, @node
  __init__.py   public API, bound to the default Graph
```

Imports run one way, `compiler -> ir <- runtime`, with `node` on top:

- **`compiler`** holds everything that happens once per class. `compile_node`
  reads the source with `inspect.getsourcelines`, rewrites the AST, then builds
  a `__make` factory containing the rewritten body plus two lambdas per edge
  (its args, its guard) and `exec`s it. The factory exists so those lambdas
  close over the *original method's* free variables.
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
node's parameters and is only ever shown to humans (`str(edge)`), `rewritten` is
in terms of `ivs` and is what gets compiled.

`GuardStack.scope()` captures the stack depth **on entry** and truncates to it on
exit. This matters: an earlier version removed a *count* of guards instead, so a
guard pushed mid-block by an early return corrupted the accounting and produced
`n > 0 and (not n > 0)` — a dependency that was silently dropped and a node that
returned `None`. The graph was wrong, not loud. See
`test_guards_do_not_leak_out_of_a_nested_block`.

## Deliberately unsupported

These raise `ValueError` when the class is created, rather than building a wrong
graph. Adding support for any of them means answering "what is the fixed list of
inputs?" first.

| Pattern | Why |
|---|---|
| Node call in a loop or comprehension | Not one call site, so not one input. |
| `self.x` member variables | A node may only see functions and constants. |
| `self` used as a value | Would smuggle member access out to a helper. |
| Node call argument using a body local | Inputs are hoisted, so they cannot see locals. |
| Rebinding a parameter | Parameters are read-only inputs. |
| `async def`, `*args`/`**kwargs` at a call site | Not modelled. |

Also not supported yet: calling a node on another object (`other.a()` stays
inline as plain code — only `self.` receivers are node calls), and unhashable
arguments.

Because compilation reads the method's own source, a node must be defined
somewhere `inspect.getsourcelines` can find it. Classes defined in a REPL or
piped into `python` from stdin fail at decoration with `OSError: could not get
source code`.

## Working on this

```
uv run ruff format      # standardise formatting
uv run ruff check --fix # lint
uv run ty check         # types
uv run pytest -q        # 75 tests
```

Tests mirror the package: `test_rewrite.py` (the transform and its rejections),
`test_deps.py` (graph shape), `test_eval.py` (order and memoisation),
`test_api.py` (decorator surface), `test_set_value.py` (overrides and dirtying),
`test_diddle.py` (scoped overrides). Shared class factories are in
`tests/helpers.py`; each test builds its own classes so nothing leaks between
them, and the autouse `fresh_graph` fixture clears the default graph.

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
