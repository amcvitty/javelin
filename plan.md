I'm going to make an Excel-style calculation engine but using Python. So I need to be able to parse the formula using the abstract syntax tree AST. Any function with the @node Decorator can be considered like a cell in Excel.

We need to create an implementation of the node function that is a Python decorator that parses the abstract syntax tree of the code of the function it decorates to identify other nodes and create a graph of references between them.

Only function calls that are also decorated with the @node decorator should be considered as nodes in the graph. In example.py, we see the sum() function has node dependencies on a() and b(), but c() is not decorated, so should not be listed as a node dependency.

Dependencies are stored as a variable in the "graph" namespace, rather than on the functions that define them, so we can have functions to explore the graph like graph.all_nodes() or graph.deps(fn) where fn is the function definition.
