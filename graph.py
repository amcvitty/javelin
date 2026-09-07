import ast
import contextlib
import copy
import functools
import inspect
import textwrap
import types
from dataclasses import dataclass

# A cell is one invocation of a node method on an object, keyed
# (object, method, *args). Terminals are the constant argument values
# themselves; everything else is a cell.
#
# A node's body is rewritten when its class is created into a pure function
# of its input values, `impl(self, node, ivs)`, plus a spec describing how to
# produce each input. Those specs are what let a cell's dependencies be found
# without ever running its body.
#
# Everything lives here in the "graph" namespace rather than on the methods.
_defs: dict = {}    # node -> _Def
_cells: dict = {}   # key -> frozenset of dependency keys, or None if unexpanded
_values: dict = {}  # key -> memoised result


@dataclass(frozen=True)
class Value:
    """A terminal input: one of the cell's own arguments."""

    index: int
    name: str

    def __str__(self):
        return self.name


@dataclass(frozen=True)
class Edge:
    """An input that is itself a cell, reached by calling `target` on the
    same object.

    Which cell is only known once `args` is evaluated against the earlier
    inputs, and only if `guard` (the condition under which the original call
    site is reached) holds. Both are pure functions of (self, node, ivs).
    """

    index: int
    target: str
    args: object
    guard: object
    source: str

    def __str__(self):
        return self.source


@dataclass(frozen=True)
class _Def:
    impl: object
    inputs: tuple
    signature: inspect.Signature  # without self
    needed: frozenset  # input indices whose values some later input reads
    code: str


class _Node:
    """What @node puts on the class.

    Accessed on an instance it is a bound method that evaluates the cell
    (obj, node, *args); accessed on the class it is the node itself.
    """

    def __init__(self, func):
        self.func = func
        self.owner = None
        functools.update_wrapper(self, func)

    def __set_name__(self, owner, name):
        # The class body is complete here, so every self.<method>() in the
        # source can be checked against it.
        self.owner = owner
        _defs[self] = _parse(self.func, owner)

    def __get__(self, obj, objtype=None):
        return self if obj is None else types.MethodType(self, obj)

    def __call__(self, *args, **kwargs):
        if self.owner is None:
            raise TypeError(f"@node {self.__name__} must be defined inside a class")
        obj, *args = args
        return _evaluate(_key(obj, self, args, kwargs))

    def __repr__(self):
        return f"<node {self.__qualname__}>"


# ---------------------------------------------------------------------------
# Parsing: rewrite the body and extract the input specs
# ---------------------------------------------------------------------------


def _not(expr):
    return ast.UnaryOp(op=ast.Not(), operand=expr)


def _terminates(stmts):
    return bool(stmts) and isinstance(stmts[-1], (ast.Return, ast.Raise))


def _impl_args(self_name):
    return ast.arguments(
        args=[ast.arg(arg=self_name), ast.arg(arg="node"), ast.arg(arg="ivs")]
    )


def _ivs_indices(expr):
    """The input indices an expression reads, i.e. its ivs[k] subscripts."""
    return {
        n.slice.value
        for n in ast.walk(expr)
        if isinstance(n, ast.Subscript)
        and isinstance(n.value, ast.Name)
        and n.value.id == "ivs"
        and isinstance(n.slice, ast.Constant)
    }


class _Rewriter(ast.NodeTransformer):
    """Replace parameters and node calls with ivs[i], collecting an input
    spec for each, together with the guard under which it is reached."""

    _REPEATED = (
        ast.For, ast.AsyncFor, ast.While, ast.Lambda, ast.FunctionDef,
        ast.AsyncFunctionDef, ast.ListComp, ast.SetComp, ast.DictComp,
        ast.GeneratorExp,
    )

    def __init__(self, func, owner, self_name, params, func_def):
        self.func = func
        self.owner = owner
        self.self_name = self_name
        self.params = params  # name -> ivs index
        self.edges = []
        self.guards = []      # stack of (original expr, rewritten expr)
        self.repeat = 0       # >0 while inside a loop, comprehension or lambda
        self.locals = self._local_names(func_def)

    @staticmethod
    def _local_names(func_def):
        """Names bound inside the body, which a hoisted input cannot see."""
        names = set()
        for n in ast.walk(func_def):
            if isinstance(n, ast.Name) and not isinstance(n.ctx, ast.Load):
                names.add(n.id)
            elif isinstance(n, (ast.Lambda, ast.FunctionDef)) and n is not func_def:
                names.update(a.arg for a in ast.walk(n.args) if isinstance(a, ast.arg))
        return names

    # -- helpers -----------------------------------------------------------

    def _ivs(self, index):
        return ast.Subscript(
            value=ast.Name(id="ivs", ctx=ast.Load()),
            slice=ast.Constant(value=index),
            ctx=ast.Load(),
        )

    @contextlib.contextmanager
    def _guarded(self, *guards):
        self.guards.extend(guards)
        try:
            yield
        finally:
            del self.guards[len(self.guards) - len(guards):]

    def _current_guard(self):
        if not self.guards:
            return None
        original = [copy.deepcopy(o) for o, _ in self.guards]
        rewritten = [copy.deepcopy(r) for _, r in self.guards]
        if len(self.guards) == 1:
            return original[0], rewritten[0]
        return (
            ast.BoolOp(op=ast.And(), values=original),
            ast.BoolOp(op=ast.And(), values=rewritten),
        )

    def _is_self_receiver(self, func_expr):
        return (
            isinstance(func_expr, ast.Attribute)
            and isinstance(func_expr.value, ast.Name)
            and func_expr.value.id == self.self_name
        )

    def _target(self, func_expr):
        """The name of the node a call refers to, or None if not a node call."""
        if not self._is_self_receiver(func_expr):
            return None
        attr = getattr(self.owner, func_expr.attr, None)
        return func_expr.attr if isinstance(attr, _Node) else None

    def _check_hoistable(self, expr, source):
        for n in ast.walk(expr):
            if isinstance(n, ast.Name) and n.id in self.locals:
                raise ValueError(
                    f"input {source!r} refers to local {n.id!r}; an input may "
                    "only use the node's parameters, earlier inputs and names "
                    "from outside the method"
                )

    def _visit_arguments(self, call):
        call.args = [self.visit(a) for a in call.args]
        call.keywords = [self.visit(k) for k in call.keywords]
        return call

    # -- the rewrite -------------------------------------------------------

    def visit_Name(self, node):
        if node.id == self.self_name:
            raise ValueError(
                f"{self.func.__name__}: {node.id!r} may only be used to call a "
                f"method, as {node.id}.<method>(...)"
            )
        if node.id not in self.params:
            return node
        if not isinstance(node.ctx, ast.Load):
            raise ValueError(
                f"parameter {node.id!r} is rebound in {self.func.__name__}; "
                "parameters are read-only inputs"
            )
        return ast.copy_location(self._ivs(self.params[node.id]), node)

    def visit_Attribute(self, node):
        if isinstance(node.value, ast.Name) and node.value.id == self.self_name:
            raise ValueError(
                f"{self.func.__name__}: reference to member variable "
                f"{ast.unparse(node)}; only functions and constants may be "
                "used in a node"
            )
        return self.generic_visit(node)

    def visit_Call(self, node):
        target = self._target(node.func)
        if target is None:
            if self._is_self_receiver(node.func):
                # A plain method call stays in the body; only its arguments
                # are rewritten.
                return self._visit_arguments(node)
            return self.generic_visit(node)

        source = ast.unparse(node)
        if self.repeat:
            raise ValueError(
                f"{source} is inside a loop, comprehension or lambda, so it "
                "cannot be a single input"
            )
        if any(isinstance(a, ast.Starred) for a in node.args) or any(
            k.arg is None for k in node.keywords
        ):
            raise ValueError(f"{source}: *args and **kwargs are not supported")

        # Node calls nested in the arguments become inputs first.
        node = self._visit_arguments(node)
        for expr in [*node.args, *(k.value for k in node.keywords)]:
            self._check_hoistable(expr, source)

        guard = self._current_guard()
        if guard is not None:
            self._check_hoistable(guard[1], source)
            source = f"{source} if {ast.unparse(guard[0])}"

        index = len(self.params) + len(self.edges)
        self.edges.append(
            dict(
                index=index,
                target=target,
                args=node.args,
                keywords=node.keywords,
                guard=None if guard is None else guard[1],
                source=source,
            )
        )
        return ast.copy_location(self._ivs(index), node)

    def visit_block(self, stmts):
        """Visit a statement list, guarding whatever follows an early return."""
        out = []
        with self._guarded():
            for stmt in stmts:
                out.append(self.visit(stmt))
                if not isinstance(stmt, ast.If):
                    continue
                original, rewritten = stmt.tests
                body_ends = _terminates(stmt.body)
                else_ends = bool(stmt.orelse) and _terminates(stmt.orelse)
                if body_ends and not else_ends:
                    self.guards.append((_not(original), _not(rewritten)))
                elif else_ends and not body_ends:
                    self.guards.append((original, rewritten))
        return out

    def visit_If(self, node):
        original = copy.deepcopy(node.test)
        node.test = self.visit(node.test)
        node.tests = (original, node.test)
        with self._guarded((original, node.test)):
            node.body = self.visit_block(node.body)
        with self._guarded((_not(original), _not(node.test))):
            node.orelse = self.visit_block(node.orelse)
        return node

    def visit_IfExp(self, node):
        original = copy.deepcopy(node.test)
        node.test = self.visit(node.test)
        with self._guarded((original, node.test)):
            node.body = self.visit(node.body)
        with self._guarded((_not(original), _not(node.test))):
            node.orelse = self.visit(node.orelse)
        return node

    def visit_BoolOp(self, node):
        # Each operand only runs if the previous ones did not short-circuit.
        values = []
        with self._guarded():
            for value in node.values:
                original = copy.deepcopy(value)
                value = self.visit(value)
                values.append(value)
                if isinstance(node.op, ast.And):
                    self.guards.append((original, value))
                else:
                    self.guards.append((_not(original), _not(value)))
        node.values = values
        return node

    def generic_visit(self, node):
        if isinstance(node, self._REPEATED):
            self.repeat += 1
            try:
                return super().generic_visit(node)
            finally:
                self.repeat -= 1
        return super().generic_visit(node)


def _cell_contents(cell):
    try:
        return cell.cell_contents
    except ValueError:
        return None


def _parse(func, owner):
    signature = inspect.signature(func)
    parameters = list(signature.parameters.values())
    if not parameters:
        raise ValueError(f"@node {func.__name__} needs a self parameter")
    self_name = parameters[0].name
    params = {p.name: i for i, p in enumerate(parameters[1:])}

    lines, first_line = inspect.getsourcelines(func)
    tree = ast.parse(textwrap.dedent("".join(lines)))
    ast.increment_lineno(tree, first_line - 1)
    func_def = tree.body[0]

    rewriter = _Rewriter(func, owner, self_name, params, func_def)
    func_def.body = rewriter.visit_block(func_def.body)
    func_def.args = _impl_args(self_name)
    func_def.decorator_list = []
    func_def.returns = None
    code = ast.unparse(func_def)

    # Compile the rewritten body and one (self, node, ivs) lambda per edge for
    # its args and guard, all inside a factory so they share the original
    # closure.
    parts = [ast.Name(id=func_def.name, ctx=ast.Load())]
    needed = set()
    for edge in rewriter.edges:
        args = ast.Tuple(
            elts=[
                ast.Tuple(elts=edge["args"], ctx=ast.Load()),
                ast.Dict(
                    keys=[ast.Constant(value=k.arg) for k in edge["keywords"]],
                    values=[k.value for k in edge["keywords"]],
                ),
            ],
            ctx=ast.Load(),
        )
        guard = edge["guard"]
        parts.append(ast.Lambda(args=_impl_args(self_name), body=args))
        parts.append(
            ast.Constant(value=None)
            if guard is None
            else ast.Lambda(args=_impl_args(self_name), body=guard)
        )
        needed |= _ivs_indices(args)
        if guard is not None:
            needed |= _ivs_indices(guard)

    freevars = func.__code__.co_freevars
    factory = ast.FunctionDef(
        name="__make",
        args=ast.arguments(args=[ast.arg(arg=name) for name in freevars]),
        body=[func_def, ast.Return(value=ast.Tuple(elts=parts, ctx=ast.Load()))],
    )
    module = ast.fix_missing_locations(
        ast.Module(body=[ast.copy_location(factory, func_def)], type_ignores=[])
    )
    namespace = {}
    exec(
        compile(module, inspect.getsourcefile(func) or "<node>", "exec"),
        func.__globals__,
        namespace,
    )
    cells = [_cell_contents(c) for c in func.__closure__ or ()]
    impl, *compiled = namespace["__make"](*cells)

    inputs = [Value(index=i, name=name) for name, i in params.items()]
    for edge, args, guard in zip(rewriter.edges, compiled[0::2], compiled[1::2]):
        inputs.append(
            Edge(
                index=edge["index"],
                target=edge["target"],
                args=args,
                guard=guard,
                source=edge["source"],
            )
        )

    return _Def(
        impl=impl,
        inputs=tuple(inputs),
        signature=signature.replace(parameters=parameters[1:]),
        needed=frozenset(needed),
        code=code,
    )


# ---------------------------------------------------------------------------
# Building and evaluating the graph
# ---------------------------------------------------------------------------


def _key(obj, fn, args=(), kwargs=None):
    """The (object, method, *args) key for a cell, canonicalising how args
    were passed so that fib(3) and fib(n=3) name the same cell."""
    bound = _defs[fn].signature.bind(*args, **(kwargs or {}))
    bound.apply_defaults()
    return (obj, fn, *bound.arguments.values())


def _resolve_inputs(key, evaluate_all):
    """Run a cell's input specs in order.

    Returns (dependency keys, ivs). Dependency values are only computed when
    evaluate_all is set, or when a later input reads them to decide which
    cell it refers to.
    """
    obj, fn, *args = key
    d = _defs[fn]
    ivs = [None] * len(d.inputs)
    deps = []
    for inp in d.inputs:
        if isinstance(inp, Value):
            ivs[inp.index] = args[inp.index]
            continue
        if inp.guard is not None and not inp.guard(obj, key, ivs):
            continue
        positional, keywords = inp.args(obj, key, ivs)
        # Looked up on the object's own type, so a subclass may override a node.
        dep = _key(obj, getattr(type(obj), inp.target), positional, keywords)
        deps.append(dep)
        if evaluate_all or inp.index in d.needed:
            ivs[inp.index] = _evaluate(dep)
    return frozenset(deps), ivs


def _register(key, deps):
    _cells[key] = deps
    for dep in deps:
        _cells.setdefault(dep, None)


def _expand(key):
    deps, _ = _resolve_inputs(key, evaluate_all=False)
    _register(key, deps)
    return deps


def _evaluate(key):
    if key in _values:
        return _values[key]
    deps, ivs = _resolve_inputs(key, evaluate_all=True)
    _register(key, deps)
    obj, fn, *_ = key
    _values[key] = _defs[fn].impl(obj, key, ivs)
    return _values[key]


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def node(func):
    """Decorator marking a method as a node (a "cell") in the dependency graph."""
    return _Node(func)


def _node_of(method):
    """Accept a node from the class (Calc.fib) or bound to an instance (calc.fib)."""
    return getattr(method, "__func__", method)


def inputs(method):
    """The input specs of a node, in evaluation order."""
    return _defs[_node_of(method)].inputs


def code(method):
    """The rewritten source of a node: a pure function of (self, node, ivs)."""
    return _defs[_node_of(method)].code


def all_nodes():
    """Every known cell, as (object, method, *args) keys."""
    return tuple(_cells)


def clear():
    """Forget every registered node. Mainly for building graphs in isolation."""
    _defs.clear()
    _cells.clear()
    _values.clear()


def deps(method, *args, **kwargs):
    """The direct dependencies of the cell obj.method(*args), as node keys.

    `method` is bound, e.g. deps(calc.fib, 5). Worked out from the node's
    input specs, so the cell itself never runs. Raises KeyError if the method
    is not a node.
    """
    if not hasattr(method, "__self__"):
        raise TypeError("deps needs a bound method, e.g. deps(calc.fib, 5)")
    key = _key(method.__self__, method.__func__, args, kwargs)
    if _cells.get(key) is None:
        _expand(key)
    return _cells[key]
