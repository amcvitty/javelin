"""Rewriting a node's body into a pure function of its input values.

Every parameter and every `self.<node>()` call becomes an `ivs[i]` subscript,
and each one yields an input saying how it is produced. A node call also
records the *guard* under which its call site is reached, so an input that a
particular invocation never touches is never made a dependency -- which is
what stops a recursive node expanding forever.

A comprehension whose element is a node call is rewritten the same way: the
whole comprehension becomes one `ivs[i]` holding the list of results, and the
input it yields is a `MapEdge` naming one cell per element.
"""

import ast
import contextlib
import copy
from dataclasses import dataclass

from .ir import CallEdge, MapEdge

# The only member variable a node may read. An object's namespace is fixed when
# it is created, so reading it cannot smuggle mutable state past the graph.
# Named rather than imported: `graph` knows nothing about the `ns` package.
PERMITTED_MEMBER = "ns"


def not_(expr):
    return ast.UnaryOp(op=ast.Not(), operand=expr)


def terminates(stmts):
    """Whether a block ends in a way that skips whatever follows it."""
    return bool(stmts) and isinstance(stmts[-1], (ast.Return, ast.Raise))


def impl_args(self_name, element=None):
    """The (self, node, ivs) parameter list every compiled callable takes.

    A `MapEdge`'s receiver and arguments take the element as a fourth parameter,
    named after the comprehension's own loop variable -- which is why the loop
    variable needs no rewriting inside them.
    """
    names = [self_name, "node", "ivs"]
    if element is not None:
        names.append(element)
    return ast.arguments(args=[ast.arg(arg=name) for name in names])


def call_args(args, keywords):
    """An expression building one call's (positional, keyword) arguments."""
    return ast.Tuple(
        elts=[
            ast.Tuple(elts=args, ctx=ast.Load()),
            ast.Dict(
                keys=[ast.Constant(value=k.arg) for k in keywords],
                values=[k.value for k in keywords],
            ),
        ],
        ctx=ast.Load(),
    )


def ivs_indices(expr):
    """The input indices an expression reads, i.e. its ivs[k] subscripts."""
    return {
        n.slice.value
        for n in ast.walk(expr)
        if isinstance(n, ast.Subscript)
        and isinstance(n.value, ast.Name)
        and n.value.id == "ivs"
        and isinstance(n.slice, ast.Constant)
    }


def binding_counts(func_def):
    """How many times each name is bound in the body.

    Anything not in `Load` context is a binding: assignment targets, loop
    variables, `with ... as`, comprehension and lambda parameters. The names are
    what a hoisted input cannot see; a name bound exactly once, by a plain
    top-level assignment, is a candidate for hoisting.
    """
    counts = {}
    for n in ast.walk(func_def):
        if isinstance(n, ast.Name) and not isinstance(n.ctx, ast.Load):
            counts[n.id] = counts.get(n.id, 0) + 1
        elif isinstance(n, (ast.Lambda, ast.FunctionDef)) and n is not func_def:
            for a in ast.walk(n.args):
                if isinstance(a, ast.arg):
                    counts[a.arg] = counts.get(a.arg, 0) + 1
    return counts


@dataclass(frozen=True)
class Guard:
    """A condition under which a call site is reached.

    Kept as a pair: `original` is in terms of the node's own parameters and is
    only ever shown to humans, `rewritten` is in terms of ivs[i] and is what
    gets compiled and run.
    """

    original: ast.expr
    rewritten: ast.expr

    def negated(self):
        return Guard(not_(self.original), not_(self.rewritten))


class GuardStack:
    """The guards currently in force, innermost last."""

    def __init__(self):
        self._stack = []

    @contextlib.contextmanager
    def scope(self):
        """Discard on exit any guard pushed while inside.

        The depth is captured on entry, so a guard pushed part-way through a
        block (an early `return` guarding the statements after it) is unwound
        with the rest.
        """
        depth = len(self._stack)
        try:
            yield
        finally:
            del self._stack[depth:]

    @contextlib.contextmanager
    def pushed(self, guard):
        with self.scope():
            self._stack.append(guard)
            yield

    def push(self, guard):
        """Add a guard that holds for the remainder of the enclosing scope."""
        self._stack.append(guard)

    def current(self):
        """The conjunction of every guard in force, or None if there are none.

        Deep-copied, since the caller embeds the result in a tree of its own.
        """
        if not self._stack:
            return None
        if len(self._stack) == 1:
            guard = self._stack[0]
            return Guard(copy.deepcopy(guard.original), copy.deepcopy(guard.rewritten))
        return Guard(
            ast.BoolOp(
                op=ast.And(),
                values=[copy.deepcopy(g.original) for g in self._stack],
            ),
            ast.BoolOp(
                op=ast.And(),
                values=[copy.deepcopy(g.rewritten) for g in self._stack],
            ),
        )


@dataclass
class RawEdge:
    """A node call site found in the body, before it is compiled.

    Each kind knows both the expressions it needs compiling (`parts`) and how to
    put the results back together (`build`), so that the compiler never has to
    know how many lambdas an edge kind takes.
    """

    index: int
    target: str
    guard: ast.expr | None
    source: str
    guard_source: str | None

    def _lambda(self, self_name, body, element=None):
        return ast.Lambda(args=impl_args(self_name, element), body=body)

    def _guard_part(self, self_name):
        if self.guard is None:
            return ast.Constant(value=None)
        return self._lambda(self_name, self.guard)

    def parts(self, self_name) -> list[ast.expr]:
        """The expressions to compile, in the order `build` expects them."""
        raise NotImplementedError

    def build(self, compiled, reads) -> object:
        """The `Edge` for this call site, from its compiled parts.

        `reads` is the slots resolving it reads, which only the compiler knows:
        it is the one thing here that depends on the *other* inputs.
        """
        raise NotImplementedError


@dataclass
class RawCallEdge(RawEdge):
    """One call site naming one cell."""

    receiver: ast.expr
    args: list
    keywords: list

    def parts(self, self_name):
        return [
            self._lambda(self_name, self.receiver),
            self._lambda(self_name, call_args(self.args, self.keywords)),
            self._guard_part(self_name),
        ]

    def build(self, compiled, reads):
        receiver, args, guard = compiled
        return CallEdge(
            index=self.index,
            target=self.target,
            guard=guard,
            guard_source=self.guard_source,
            source=self.source,
            reads=reads,
            receiver=receiver,
            args=args,
        )


@dataclass
class RawMapEdge(RawEdge):
    """One call site naming one cell per element of a collection.

    `receiver` and `args` are compiled with the loop variable as an extra
    parameter, so they may refer to it by name.
    """

    over: ast.expr
    receiver: ast.expr
    args: list
    keywords: list
    var: str

    def parts(self, self_name):
        return [
            self._lambda(self_name, self.over),
            self._lambda(self_name, self.receiver, self.var),
            self._lambda(self_name, call_args(self.args, self.keywords), self.var),
            self._guard_part(self_name),
        ]

    def build(self, compiled, reads):
        over, receiver, args, guard = compiled
        return MapEdge(
            index=self.index,
            target=self.target,
            guard=guard,
            guard_source=self.guard_source,
            source=self.source,
            reads=reads,
            over=over,
            receiver=receiver,
            args=args,
            var=self.var,
        )


@dataclass
class RawLocal:
    """A body assignment lifted above the body, before it is compiled.

    `value` is the right-hand side already rewritten to read `ivs`; `source` is
    the original right-hand side, kept for `str(Local)`.
    """

    index: int
    name: str
    value: ast.expr
    source: str


class Rewriter(ast.NodeTransformer):
    """Replace parameters and node calls with ivs[i], collecting an input
    input for each, together with the guard under which it is reached."""

    #: Constructs whose body runs an unknown number of times, so a node call
    #: inside one is not a single call site. Comprehensions are absent: each has
    #: its own visitor, which manages `repeat` itself when it cannot map them.
    _REPEATED = (
        ast.For,
        ast.AsyncFor,
        ast.While,
        ast.Lambda,
        ast.FunctionDef,
        ast.AsyncFunctionDef,
    )

    def __init__(self, func, owner, self_name, params, func_def, is_node):
        self.func = func
        self.owner = owner
        self.self_name = self_name
        self.params = params  # name -> ivs index
        self.is_node = is_node  # supplied by the decorator, to avoid a cycle
        self.edges = []
        self.raw_locals = []  # RawLocal per hoisted assignment, in source order
        self.hoisted = {}  # name -> ivs index, for a lifted assignment
        self.guards = GuardStack()
        self.repeat = 0  # >0 while inside a loop, comprehension or lambda
        self.if_tests = {}  # id(If) -> Guard for its test
        self._top_body = False  # True only while visiting the function's own body
        self._next_index = len(params)  # next free ivs slot, for edges and locals
        self._binding_counts = binding_counts(func_def)
        self.locals = set(self._binding_counts)
        rebound = sorted(set(params) & self.locals)
        if rebound:
            raise ValueError(
                f"parameter {rebound[0]!r} is rebound in {func.__name__}; "
                "parameters are read-only inputs"
            )

    # -- helpers -----------------------------------------------------------

    def _alloc(self):
        """Claim the next ivs slot, shared by edges and hoisted locals."""
        index = self._next_index
        self._next_index += 1
        return index

    def _ivs(self, index):
        return ast.Subscript(
            value=ast.Name(id="ivs", ctx=ast.Load()),
            slice=ast.Constant(value=index),
            ctx=ast.Load(),
        )

    def _is_self_receiver(self, func_expr):
        return (
            isinstance(func_expr, ast.Attribute)
            and isinstance(func_expr.value, ast.Name)
            and func_expr.value.id == self.self_name
        )

    def _reads_name(self, expr, name):
        return any(isinstance(n, ast.Name) and n.id == name for n in ast.walk(expr))

    def _reads_self(self, expr):
        return self._reads_name(expr, self.self_name)

    def _call_kind(self, func_expr: ast.Attribute, elements=()):
        """What a call site is, from the shape of the attribute being called.

        "input"  -- an input: self.<node>(...), or a call on an object the
                    graph produced, like self.Other().value(). Whether the
                    latter names a node is only knowable once the receiver has
                    been evaluated, so the runtime decides.
        "plain"  -- self.<method>(...) where the method is not a node.
        None     -- nothing to do with the graph.

        `elements` are the loop variables in force, if we are looking inside a
        comprehension: a call on an element is an input for the same reason a
        call on another cell's value is.
        """
        if self._is_self_receiver(func_expr):
            attr = getattr(self.owner, func_expr.attr, None)
            return "input" if self.is_node(attr) else "plain"
        if self._reads_self(func_expr.value):
            return "input"
        if any(self._reads_name(func_expr.value, name) for name in elements):
            return "input"
        return None

    def _check_hoistable(self, expr, source, allow=()):
        """Whether an expression may be lifted above the body.

        `allow` names locals it may read anyway -- a map's loop variable, which
        is a parameter of the lambdas it is compiled into rather than a local
        the body binds.
        """
        for n in ast.walk(expr):
            if (
                isinstance(n, ast.Name)
                and n.id in self.locals
                and n.id not in self.hoisted
                and n.id not in allow
            ):
                raise ValueError(
                    f"input {source!r} refers to local {n.id!r}; an input may "
                    "only use the node's parameters, earlier inputs and names "
                    "from outside the method"
                )

    def _visit_arguments(self, call):
        call.args = [self.visit(a) for a in call.args]
        call.keywords = [self.visit(k) for k in call.keywords]
        return call

    def _test_guard(self, node):
        """Visit an if/ifexp test, returning its guard as a pair."""
        original = copy.deepcopy(node.test)
        node.test = self.visit(node.test)
        return Guard(original, node.test)

    def _guard_at(self, source):
        """The guard in force at a call site, as (expression to compile, text).

        (None, None) when the call site is unconditional. The text is kept
        apart from the call site's own source so that a guard can be shown in
        its own right rather than parsed back out of a string.
        """
        guard = self.guards.current()
        if guard is None:
            return None, None
        self._check_hoistable(guard.rewritten, source)
        return guard.rewritten, ast.unparse(guard.original)

    # -- the rewrite -------------------------------------------------------

    def visit_Name(self, node):
        if node.id == self.self_name:
            raise ValueError(
                f"{self.func.__name__}: {node.id!r} may only be used to call a "
                f"method, as {node.id}.<method>(...)"
            )
        if node.id in self.hoisted:
            return ast.copy_location(self._ivs(self.hoisted[node.id]), node)
        if node.id not in self.params:
            return node
        return ast.copy_location(self._ivs(self.params[node.id]), node)

    def visit_Attribute(self, node):
        if isinstance(node.value, ast.Name) and node.value.id == self.self_name:
            if node.attr == PERMITTED_MEMBER:
                # The one member a node may read: the object's namespace, which
                # is fixed when the object is created.
                return node
            raise ValueError(
                f"{self.func.__name__}: reference to member variable "
                f"{ast.unparse(node)}; only functions and constants may be "
                "used in a node"
            )
        return self.generic_visit(node)

    def visit_Call(self, node):
        func = node.func
        if not isinstance(func, ast.Attribute):
            # Only a call on an attribute can name a node.
            return self.generic_visit(node)
        kind = self._call_kind(func)
        if kind is None:
            return self.generic_visit(node)
        if kind == "plain":
            # A plain method call stays in the body; only its arguments are
            # rewritten.
            return self._visit_arguments(node)

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

        # The object being called is resolved first, so a node call inside the
        # receiver becomes an earlier input that this one refers to.
        if self._is_self_receiver(func):
            receiver = ast.Name(id=self.self_name, ctx=ast.Load())
        else:
            receiver = self.visit(func.value)
        # Node calls nested in the arguments become inputs too.
        node = self._visit_arguments(node)
        for expr in [receiver, *node.args, *(k.value for k in node.keywords)]:
            self._check_hoistable(expr, source)

        guard, guard_source = self._guard_at(source)

        index = self._alloc()
        self.edges.append(
            RawCallEdge(
                index=index,
                target=func.attr,
                guard=guard,
                guard_source=guard_source,
                source=source,
                receiver=receiver,
                args=node.args,
                keywords=node.keywords,
            )
        )
        return ast.copy_location(self._ivs(index), node)

    # -- comprehensions ----------------------------------------------------

    def visit_ListComp(self, node):
        return self._visit_comprehension(node)

    def visit_GeneratorExp(self, node):
        return self._visit_comprehension(node)

    def visit_SetComp(self, node):
        return self._rejected_comprehension(
            node,
            "a set comprehension would silently drop cells with equal values; "
            "use a list comprehension",
        )

    def visit_DictComp(self, node):
        return self._rejected_comprehension(
            node, "a dict comprehension cannot be one input; use a list comprehension"
        )

    def _node_calls(self, node, elements=()):
        """Node call sites anywhere inside an expression."""
        return [
            n
            for n in ast.walk(node)
            if isinstance(n, ast.Call)
            and isinstance(n.func, ast.Attribute)
            and self._call_kind(n.func, elements) == "input"
        ]

    def _rejected_comprehension(self, node, reason):
        """A comprehension shape we will not map.

        Only an error if the *repeated* part of it reaches the graph: the
        outermost iterable runs once however many elements there are, so a node
        call there is an ordinary edge whatever the rest of the shape is.
        """
        source = ast.unparse(node)
        node.generators[0].iter = self.visit(node.generators[0].iter)
        self.repeat += 1
        try:
            if self._node_calls(node, self._loop_vars(node)):
                raise ValueError(f"{source}: {reason}")
            return super().generic_visit(node)
        finally:
            self.repeat -= 1

    @staticmethod
    def _loop_vars(node):
        """Every name the comprehension's `for` clauses bind.

        A call on any of them is a call on an element, however many levels of
        `for` there are -- which is what makes a shape we will not map an error
        rather than the plain code it would otherwise compile to.
        """
        return tuple(
            generator.target.id
            for generator in node.generators
            if isinstance(generator.target, ast.Name)
        )

    def _visit_comprehension(self, node):
        """Rewrite `[t.pv() for t in <iterable>]` into one `MapEdge`.

        The iterable is visited first and outside the repeat guard: it runs once
        however many elements there are, so a node call in it is an ordinary
        edge, and it has to be an *earlier* input than the map that reads it.
        """
        if len(node.generators) != 1:
            return self._rejected_comprehension(
                node, "only one 'for' clause is supported; give each level its own node"
            )
        generator = node.generators[0]
        if generator.is_async:
            return self._rejected_comprehension(node, "async is not modelled")
        if generator.ifs:
            return self._rejected_comprehension(
                node,
                "an 'if' filter is not supported: it would change how many "
                "cells the comprehension names",
            )
        if not isinstance(generator.target, ast.Name):
            return self._rejected_comprehension(
                node, "the loop variable must be a single name"
            )

        source = ast.unparse(node)
        var = generator.target.id
        generator.iter = self.visit(generator.iter)
        calls = self._node_calls(node.elt, (var,))
        if not calls:
            # Nothing in the element touches the graph, so it stays plain code
            # over whatever the iterable produced.
            return self._plain_element(node)
        if len(calls) > 1:
            raise ValueError(
                f"{source}: a comprehension may contain one node call, not "
                f"{len(calls)}; give {var!r} a node that combines them, or "
                "hoist a loop-invariant call into an assignment above"
            )
        return self._map_edge(node, calls[0], generator, var, source)

    def _map_edge(self, node, call, generator, var, source):
        if self.repeat:
            raise ValueError(
                f"{source} is inside a loop, comprehension or lambda, so it "
                "cannot be a single input"
            )
        if call is not node.elt:
            raise ValueError(
                f"{source}: the element must be the node call itself, not an "
                f"expression around it; put the rest on a node of {var!r}"
            )
        if var in (self.self_name, "node", "ivs"):
            raise ValueError(
                f"{source}: {var!r} is not available as a comprehension variable"
            )
        func = call.func
        assert isinstance(func, ast.Attribute)
        if any(isinstance(a, ast.Starred) for a in call.args) or any(
            k.arg is None for k in call.keywords
        ):
            raise ValueError(f"{source}: *args and **kwargs are not supported")

        self._check_hoistable(generator.iter, source)
        # The receiver and the arguments may mention the element -- they are
        # compiled with it as a parameter. They may not contain a node call of
        # their own, but nothing needs checking here: such a call would have
        # been a second candidate above, and one is the limit.
        receiver = (
            ast.Name(id=self.self_name, ctx=ast.Load())
            if self._is_self_receiver(func)
            else self.visit(func.value)
        )
        call = self._visit_arguments(call)
        for expr in [receiver, *call.args, *(k.value for k in call.keywords)]:
            self._check_hoistable(expr, source, allow=(var,))

        guard, guard_source = self._guard_at(source)

        index = self._alloc()
        self.edges.append(
            RawMapEdge(
                index=index,
                target=func.attr,
                guard=guard,
                guard_source=guard_source,
                source=source,
                over=generator.iter,
                receiver=receiver,
                args=call.args,
                keywords=call.keywords,
                var=var,
            )
        )
        return ast.copy_location(self._ivs(index), node)

    def _plain_element(self, node):
        """The iterable is already visited; the element stays plain code."""
        self.repeat += 1
        try:
            node.elt = self.visit(node.elt)
        finally:
            self.repeat -= 1
        return node

    def visit_body(self, stmts):
        """Visit the function's own body, where assignments may be hoisted."""
        self._top_body = True
        return self.visit_block(stmts)

    def _hoist_candidate(self, stmt):
        """The name of a plain assignment eligible to be lifted, or None.

        Eligible means: a single bare `name =` target, bound nowhere else in the
        body, not a parameter, and reached unconditionally. Whether its
        right-hand side is actually hoistable is decided after it is rewritten.
        """
        if not isinstance(stmt, ast.Assign) or len(stmt.targets) != 1:
            return None
        target = stmt.targets[0]
        if not isinstance(target, ast.Name) or target.id in self.params:
            return None
        if self._binding_counts.get(target.id, 0) != 1:
            return None
        if self.guards.current() is not None:
            return None
        return target.id

    def _reads_local(self, expr):
        """Whether a rewritten expression still refers to a body local."""
        return any(
            isinstance(n, ast.Name) and n.id in self.locals and n.id not in self.hoisted
            for n in ast.walk(expr)
        )

    def visit_block(self, stmts):
        """Visit a statement list, guarding whatever follows an early return."""
        out = []
        top, self._top_body = self._top_body, False
        with self.guards.scope():
            for stmt in stmts:
                if top and (name := self._hoist_candidate(stmt)) is not None:
                    source = ast.unparse(stmt.value)
                    value = self.visit(stmt.value)
                    if self._reads_local(value):
                        # Depends on a local that stays in the body, so this one
                        # must too. Its right-hand side is already rewritten.
                        stmt.value = value
                        out.append(stmt)
                    else:
                        index = self._alloc()
                        self.hoisted[name] = index
                        self.raw_locals.append(RawLocal(index, name, value, source))
                    continue
                visited = self.visit(stmt)
                out.append(visited)
                if not isinstance(visited, ast.If):
                    continue
                # Statements after an if whose body always returns are only
                # reached when its test failed, and vice versa.
                guard = self.if_tests[id(visited)]
                body_ends = terminates(visited.body)
                else_ends = bool(visited.orelse) and terminates(visited.orelse)
                if body_ends and not else_ends:
                    self.guards.push(guard.negated())
                elif else_ends and not body_ends:
                    self.guards.push(guard)
        return out

    def visit_If(self, node):
        guard = self._test_guard(node)
        self.if_tests[id(node)] = guard
        with self.guards.pushed(guard):
            node.body = self.visit_block(node.body)
        with self.guards.pushed(guard.negated()):
            node.orelse = self.visit_block(node.orelse)
        return node

    def visit_IfExp(self, node):
        guard = self._test_guard(node)
        with self.guards.pushed(guard):
            node.body = self.visit(node.body)
        with self.guards.pushed(guard.negated()):
            node.orelse = self.visit(node.orelse)
        return node

    def visit_BoolOp(self, node):
        # Each operand only runs if the previous ones did not short-circuit.
        values = []
        with self.guards.scope():
            for value in node.values:
                original = copy.deepcopy(value)
                value = self.visit(value)
                values.append(value)
                guard = Guard(original, value)
                self.guards.push(
                    guard if isinstance(node.op, ast.And) else guard.negated()
                )
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
