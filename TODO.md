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

# Gromit and the Beacon Namespace

• Single objects are interesting, but limited
• Real applications have multiple different objects encapsulating
different bits of functionality
• In Beacon, we have an in-memory namespace, connected to
an object-oriented document store, that lets you define
well-named objects
Gromit's graph lets you access those objects by name, and
depend on methods on other objects

- Inherit from McObject
  - Default GUID name for object
  - Get name
- Global namespace to allow references between objects via ns[] lookup.

# Store

- store objects - add mcdb.Stored

```

```
