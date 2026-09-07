- Update Objects with s.B.set_value(4) - explicitly sets one of the inputs to a different value.
- Notifications of dirty status, traversing the graph
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
