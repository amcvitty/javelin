"""Turning a decorated method into a `CompiledNode`.

The body is rewritten into `impl(self, node, ivs)` and each node call site into
a pair of `(self, node, ivs)` lambdas -- one producing the call's arguments,
one its guard. All of them are compiled inside a factory function so that they
close over the same free variables as the original method.
"""

import ast
import inspect
import textwrap

from .ir import CompiledNode, Edge, Local, Value
from .rewriter import Rewriter, impl_args, ivs_indices

#: What the rewritten body is called inside the factory. Deliberately not the
#: node's own name, which could be a free variable of the method as well.
IMPL_NAME = "__impl"


def _source_ast(func):
    """The function's own AST, with line numbers pointing back at the source."""
    lines, first_line = inspect.getsourcelines(func)
    tree = ast.parse(textwrap.dedent("".join(lines)))
    ast.increment_lineno(tree, first_line - 1)
    func_def = tree.body[0]
    if not isinstance(func_def, ast.FunctionDef):
        # ValueError, not TypeError, to match every other unsupported
        # construct: the argument is fine, the shape of the source is not.
        raise ValueError(  # noqa: TRY004
            f"@node {func.__name__} must be a plain def, "
            f"not {func_def.__class__.__name__}"
        )
    return func_def


def _split_signature(func):
    """(self name, {parameter name: input index}, signature without self)."""
    signature = inspect.signature(func)
    parameters = list(signature.parameters.values())
    if not parameters:
        raise ValueError(f"@node {func.__name__} needs a self parameter")
    params = {p.name: i for i, p in enumerate(parameters[1:])}
    return parameters[0].name, params, signature.replace(parameters=parameters[1:])


def _build_factory(func_def, edges, raw_locals, self_name, freevars):
    """Wrap the rewritten body, per-edge lambdas and per-local lambdas in a
    `__make` factory.

    Returns the module, the number of parts each edge contributed, and the set
    of inputs whose *values* some edge reads to work out which cell it refers
    to -- widened to the transitive closure through any hoisted local an edge
    reaches.
    """
    parts: list[ast.expr] = [ast.Name(id=func_def.name, ctx=ast.Load())]
    counts = []
    needed = set()
    for edge in edges:
        # Each edge kind says which expressions it needs compiling: a receiver
        # and arguments for one cell, plus a collection for one cell per
        # element. The compiler stays out of the difference.
        edge_parts = edge.parts(self_name)
        counts.append(len(edge_parts))
        parts.extend(edge_parts)
        # An input whose value is read to work out which cell this edge means
        # -- through the object it is called on, its arguments, or the
        # collection it maps over -- has to be evaluated during expansion, not
        # just during evaluation.
        for part in edge_parts:
            needed |= ivs_indices(part)
    for local in raw_locals:
        parts.append(ast.Lambda(args=impl_args(self_name), body=local.value))

    # A hoisted local is only worth evaluating during expansion when something
    # that shapes the graph reads it -- and then the inputs *it* reads matter
    # too, recursively.
    local_reads = {local.index: ivs_indices(local.value) for local in raw_locals}
    pending = list(needed)
    while pending:
        for dep in local_reads.get(pending.pop(), ()):
            if dep not in needed:
                needed.add(dep)
                pending.append(dep)

    factory = ast.FunctionDef(
        name="__make",
        args=ast.arguments(args=[ast.arg(arg=name) for name in freevars]),
        body=[func_def, ast.Return(value=ast.Tuple(elts=parts, ctx=ast.Load()))],
    )
    module = ast.fix_missing_locations(
        ast.Module(body=[ast.copy_location(factory, func_def)], type_ignores=[])
    )
    return module, counts, frozenset(needed)


def _cell_contents(cell):
    try:
        return cell.cell_contents
    except ValueError:
        # Not filled yet, e.g. the class is still being created.
        return None


def _exec_factory(module, func):
    """Run the factory, closed over the original method's free variables.

    Returns the compiled body followed by a receiver/args/guard triple per edge.
    """
    namespace = {}
    # Compiling the rewritten body is the whole point of the decorator: the
    # source is derived from the node's own AST, never from external input.
    exec(  # noqa: S102
        compile(module, inspect.getsourcefile(func) or "<node>", "exec"),
        func.__globals__,
        namespace,
    )
    cells = [_cell_contents(c) for c in func.__closure__ or ()]
    return namespace["__make"](*cells)


def compile_node(func, owner, is_node):
    """Compile one decorated method into its `CompiledNode`.

    `is_node` decides whether an attribute of `owner` is itself a node; it is
    passed in so that this module need not know about the descriptor.
    """
    self_name, params, signature = _split_signature(func)
    func_def = _source_ast(func)

    rewriter = Rewriter(func, owner, self_name, params, func_def, is_node)
    func_def.body = rewriter.visit_body(func_def.body)
    func_def.args = impl_args(self_name)
    func_def.decorator_list = []
    func_def.returns = None
    code = ast.unparse(func_def)

    # Renamed only now that the readable source has been taken: inside the
    # factory the body is a nested def, which would shadow a free variable of
    # the same name -- a node called `market` closing over a `market`.
    func_def.name = IMPL_NAME
    module, counts, needed = _build_factory(
        func_def,
        rewriter.edges,
        rewriter.raw_locals,
        self_name,
        func.__code__.co_freevars,
    )
    impl, *compiled = _exec_factory(module, func)

    # `compiled` is each edge's parts in turn -- how many is the edge kind's
    # business -- then one lambda per hoisted local, in the order the factory
    # built them.
    inputs: list[Value | Edge | Local] = [
        Value(index=i, name=name) for name, i in params.items()
    ]
    at = 0
    for edge, count in zip(rewriter.edges, counts):
        inputs.append(edge.build(compiled[at : at + count]))
        at += count
    local_parts = compiled[at:]
    for local, expr in zip(rewriter.raw_locals, local_parts):
        inputs.append(
            Local(
                index=local.index,
                name=local.name,
                expr=expr,
                source=local.source,
            )
        )
    inputs.sort(key=lambda inp: inp.index)

    return CompiledNode(
        impl=impl,
        inputs=tuple(inputs),
        signature=signature,
        needed=needed,
        code=code,
    )
