"""Tests for the @node decorator and the dependency graph it builds.

Each test defines its own nodes, mirroring the shape of example.py:

    @node a()   -> 1          (no node deps)
    @node b()   -> 2          (no node deps)
          c()   -> 4          (NOT a node)
    @node sum() -> a() + b() + c() + 1
"""

import pytest

import graph
from graph import node


@pytest.fixture(autouse=True)
def fresh_graph():
    """Every test builds its own graph, so start from an empty registry."""
    graph.clear()


def names(keys):
    """Render node keys as "a" / "fib(5)" strings, for readable assertions."""
    return {
        f"{fn.__name__}({', '.join(map(repr, args))})" if args else fn.__name__
        for fn, *args in keys
    }


class TestAllNodes:
    def test_decorated_functions_are_registered(self):
        @node
        def a():
            return 1

        @node
        def b():
            return 2

        def c():
            return 4

        @node
        def sum():
            return a() + b() + c() + 1

        assert names(graph.all_nodes()) == {"a", "b", "sum"}

    def test_undecorated_function_is_not_a_node(self):
        @node
        def a():
            return 1

        def c():
            return 4

        assert set(graph.all_nodes()) == {(a,)}
        assert (c,) not in graph.all_nodes()

    def test_registers_the_decorated_function_objects(self):
        @node
        def a():
            return 1

        @node
        def b():
            return 2

        assert set(graph.all_nodes()) == {(a,), (b,)}

    def test_an_empty_graph_has_no_nodes(self):
        assert graph.all_nodes() == ()


class TestDeps:
    def test_deps_only_include_other_nodes(self):
        @node
        def a():
            return 1

        @node
        def b():
            return 2

        def c():
            return 4

        @node
        def sum():
            return a() + b() + c() + 1

        assert graph.deps(sum) == {(a,), (b,)}

    def test_deps_exclude_calls_to_undecorated_functions(self):
        def c():
            return 4

        @node
        def sum():
            return c() + 1

        assert graph.deps(sum) == frozenset()

    def test_leaf_nodes_have_no_deps(self):
        @node
        def a():
            return 1

        assert graph.deps(a) == frozenset()

    def test_deps_are_direct_only(self):
        @node
        def a():
            return 1

        @node
        def b():
            return a() + 1

        @node
        def sum():
            return b() + 1

        # sum reaches a only through b, so a is not a *direct* dependency.
        assert graph.deps(sum) == {(b,)}
        assert graph.deps(b) == {(a,)}

    def test_a_node_called_twice_appears_once(self):
        @node
        def a():
            return 1

        @node
        def sum():
            return a() + a()

        assert graph.deps(sum) == {(a,)}

    def test_deps_of_a_non_node_is_an_error(self):
        def c():
            return 4

        with pytest.raises(KeyError):
            graph.deps(c)


class TestDecoratedBehaviour:
    def test_node_preserves_function_metadata(self):
        @node
        def a():
            """Return one."""
            return 1

        assert a.__name__ == "a"
        assert a.__doc__ == "Return one."

    def test_nodes_are_still_callable(self):
        @node
        def a():
            return 1

        @node
        def b():
            return 2

        def c():
            return 4

        @node
        def sum():
            return a() + b() + c() + 1

        assert a() == 1
        assert b() == 2
        assert sum() == 1 + 2 + 4 + 1


class TestRewrite:
    """@node rewrites the body into a pure function of its input values,
    ivs, plus a spec for how each input is produced:

        def fib(node, ivs):
            return ivs[0] if ivs[0] < 2 else ivs[1] + ivs[2]

        ivs[0] = n
        ivs[1] = fib(n - 1) if not n < 2
        ivs[2] = fib(n - 2) if not n < 2
    """

    def test_parameters_and_node_calls_become_input_values(self):
        @node
        def fib(n):
            return n if n < 2 else fib(n - 1) + fib(n - 2)

        assert graph.code(fib) == (
            "def fib(node, ivs):\n"
            "    return ivs[0] if ivs[0] < 2 else ivs[1] + ivs[2]"
        )

    def test_inputs_list_arguments_then_calls_with_their_guards(self):
        @node
        def fib(n):
            return n if n < 2 else fib(n - 1) + fib(n - 2)

        assert [str(i) for i in graph.inputs(fib)] == [
            "n",
            "fib(n - 1) if not n < 2",
            "fib(n - 2) if not n < 2",
        ]

    def test_arguments_are_terminals_and_calls_are_edges(self):
        @node
        def fib(n):
            return n if n < 2 else fib(n - 1) + fib(n - 2)

        n, left, right = graph.inputs(fib)
        assert isinstance(n, graph.Value)
        assert isinstance(left, graph.Edge) and left.target is fib
        assert isinstance(right, graph.Edge) and right.target is fib

    def test_undecorated_calls_stay_in_the_body(self):
        @node
        def a():
            return 1

        def c():
            return 4

        @node
        def sum():
            return a() + b_free() + c() + 1

        assert graph.code(sum) == (
            "def sum(node, ivs):\n    return ivs[0] + b_free() + c() + 1"
        )
        assert [str(i) for i in graph.inputs(sum)] == ["a()"]

    def test_early_return_guards_what_follows(self):
        @node
        def fib(n):
            if n < 2:
                return n
            return fib(n - 1) + fib(n - 2)

        assert [str(i) for i in graph.inputs(fib)] == [
            "n",
            "fib(n - 1) if not n < 2",
            "fib(n - 2) if not n < 2",
        ]
        assert fib(6) == 8

    def test_short_circuit_guards(self):
        @node
        def a():
            return 0

        @node
        def b():
            return 2

        @node
        def either():
            return a() or b()

        assert [str(i) for i in graph.inputs(either)] == ["a()", "b() if not a()"]
        assert either() == 2

    def test_node_calls_nested_in_arguments_are_evaluated_first(self):
        @node
        def one():
            return 1

        @node
        def double(n):
            return n * 2

        @node
        def answer():
            return double(one())

        assert [str(i) for i in graph.inputs(answer)] == ["one()", "double(one())"]
        assert graph.deps(answer) == {(one,), (double, 1)}
        assert answer() == 2


def b_free():
    """A module-level helper that is deliberately not a node."""
    return 0


class TestStaticDeps:
    """A cell's dependencies come from its input specs, so they can be found
    without running its body. Which cells they are may still depend on the
    *values* of earlier inputs: those edges change the shape of the graph.
    """

    @staticmethod
    def make_fib(evaluated=None):
        @node
        def fib(n):
            if evaluated is not None:
                evaluated.append(n)
            return n if n < 2 else fib(n - 1) + fib(n - 2)

        return fib

    def test_deps_are_known_without_evaluating(self):
        evaluated = []
        fib = self.make_fib(evaluated)

        assert graph.deps(fib, 6) == {(fib, 5), (fib, 4)}
        assert graph.deps(fib, 5) == {(fib, 4), (fib, 3)}
        assert evaluated == []

    def test_guarded_edges_are_absent_in_the_base_case(self):
        fib = self.make_fib()

        assert graph.deps(fib, 0) == frozenset()
        assert graph.deps(fib, 1) == frozenset()

    def test_a_parameterised_node_has_no_cells_until_one_is_referenced(self):
        fib = self.make_fib()
        assert graph.all_nodes() == ()

        graph.deps(fib, 2)
        assert names(graph.all_nodes()) == {"fib(2)", "fib(1)", "fib(0)"}

    def test_keyword_and_positional_args_name_the_same_cell(self):
        fib = self.make_fib()

        assert graph.deps(fib, 4) == graph.deps(fib, n=4) == {(fib, 3), (fib, 2)}

    def test_zero_arg_node_depending_on_a_parameterised_one(self):
        fib = self.make_fib()

        @node
        def answer():
            return fib(4) + 1

        assert graph.deps(answer) == {(fib, 4)}
        assert answer() == 4

    def test_edge_whose_shape_depends_on_another_cells_value(self):
        fib = self.make_fib()

        @node
        def threshold():
            return 3

        @node
        def pick(n):
            return fib(n) if n > threshold() else 0

        assert [str(i) for i in graph.inputs(pick)] == [
            "n",
            "threshold()",
            "fib(n) if n > threshold()",
        ]
        # Deciding whether fib(n) is an edge needs threshold's value, but
        # never fib's.
        assert graph.deps(pick, 5) == {(threshold,), (fib, 5)}
        assert graph.deps(pick, 1) == {(threshold,)}
        assert (threshold,) in graph.all_nodes()

    def test_cells_are_shared_between_callers(self):
        fib = self.make_fib()
        fib(5)
        fib(4)

        assert sum(1 for fn, *args in graph.all_nodes() if args == [4]) == 1


class TestEvaluation:
    """Evaluation follows the graph: a cell's inputs are produced before its
    body runs, so the leaves are evaluated first, and every cell only once.
    """

    def test_leaves_run_first_and_each_cell_runs_once(self):
        evaluated = []
        fib = TestStaticDeps.make_fib(evaluated)

        assert fib(5) == 5
        assert evaluated == [1, 0, 2, 3, 4, 5]

    def test_results_are_memoised_across_calls(self):
        evaluated = []
        fib = TestStaticDeps.make_fib(evaluated)

        fib(5)
        fib(5)
        fib(3)
        assert evaluated == [1, 0, 2, 3, 4, 5]

    def test_every_evaluated_cell_is_a_node(self):
        fib = TestStaticDeps.make_fib()
        fib(4)

        assert names(graph.all_nodes()) == {
            "fib(4)",
            "fib(3)",
            "fib(2)",
            "fib(1)",
            "fib(0)",
        }

    def test_parameterised_node_computes_correctly(self):
        fib = TestStaticDeps.make_fib()
        assert [fib(n) for n in range(8)] == [0, 1, 1, 2, 3, 5, 8, 13]


class TestUnsupported:
    """Patterns that cannot be turned into a fixed list of inputs fail at
    decoration time rather than silently building the wrong graph."""

    def test_node_call_inside_a_loop(self):
        @node
        def a():
            return 1

        with pytest.raises(ValueError, match="loop"):

            @node
            def total():
                acc = 0
                for _ in range(3):
                    acc += a()
                return acc

    def test_node_call_whose_argument_is_a_local(self):
        @node
        def double(n):
            return n * 2

        with pytest.raises(ValueError, match="local 'x'"):

            @node
            def answer():
                x = 3
                return double(x)

    def test_rebinding_a_parameter(self):
        with pytest.raises(ValueError, match="rebound"):

            @node
            def bump(n):
                n = n + 1
                return n
