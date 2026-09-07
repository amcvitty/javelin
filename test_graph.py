"""Tests for the @node decorator and the dependency graph it builds.

Nodes are methods; a cell is one invocation of a node on an object, keyed
(object, method, *args). Each test defines its own class, mirroring the
shape of example.py:

    @node a(self)   -> 1          (no node deps)
    @node b(self)   -> 2          (no node deps)
          c(self)   -> 4          (NOT a node)
    @node sum(self) -> self.a() + self.b() + self.c() + 1
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
        for obj, fn, *args in keys
    }


def make_calc():
    class Calc:
        @node
        def a(self):
            return 1

        @node
        def b(self):
            return 2

        def c(self):
            return 4

        @node
        def sum(self):
            return self.a() + self.b() + self.c() + 1

    return Calc


class TestCells:
    def test_cells_appear_once_referenced(self):
        calc = make_calc()()
        assert graph.all_nodes() == ()

        graph.deps(calc.sum)
        assert names(graph.all_nodes()) == {"a", "b", "sum"}

    def test_cells_are_keyed_by_object_and_method(self):
        Calc = make_calc()
        calc = Calc()
        graph.deps(calc.sum)

        assert set(graph.all_nodes()) == {
            (calc, Calc.a),
            (calc, Calc.b),
            (calc, Calc.sum),
        }

    def test_undecorated_method_is_not_a_node(self):
        Calc = make_calc()
        calc = Calc()
        graph.deps(calc.sum)

        assert (calc, Calc.c) not in graph.all_nodes()
        with pytest.raises(KeyError):
            graph.inputs(Calc.c)

    def test_each_object_has_its_own_cells(self):
        Calc = make_calc()
        x, y = Calc(), Calc()
        graph.deps(x.sum)
        graph.deps(y.sum)

        assert set(graph.all_nodes()) == {
            (x, Calc.a), (x, Calc.b), (x, Calc.sum),
            (y, Calc.a), (y, Calc.b), (y, Calc.sum),
        }

    def test_an_empty_graph_has_no_nodes(self):
        assert graph.all_nodes() == ()


class TestDeps:
    def test_deps_only_include_other_nodes(self):
        Calc = make_calc()
        calc = Calc()

        assert graph.deps(calc.sum) == {(calc, Calc.a), (calc, Calc.b)}

    def test_deps_exclude_calls_to_undecorated_methods(self):
        class Calc:
            def c(self):
                return 4

            @node
            def sum(self):
                return self.c() + 1

        assert graph.deps(Calc().sum) == frozenset()

    def test_leaf_nodes_have_no_deps(self):
        calc = make_calc()()
        assert graph.deps(calc.a) == frozenset()

    def test_deps_are_direct_only(self):
        class Calc:
            @node
            def a(self):
                return 1

            @node
            def b(self):
                return self.a() + 1

            @node
            def sum(self):
                return self.b() + 1

        calc = Calc()
        # sum reaches a only through b, so a is not a *direct* dependency.
        assert graph.deps(calc.sum) == {(calc, Calc.b)}
        assert graph.deps(calc.b) == {(calc, Calc.a)}

    def test_a_node_called_twice_appears_once(self):
        class Calc:
            @node
            def a(self):
                return 1

            @node
            def sum(self):
                return self.a() + self.a()

        calc = Calc()
        assert graph.deps(calc.sum) == {(calc, Calc.a)}

    def test_deps_of_a_non_node_is_an_error(self):
        calc = make_calc()()
        with pytest.raises(KeyError):
            graph.deps(calc.c)

    def test_deps_needs_a_bound_method(self):
        Calc = make_calc()
        with pytest.raises(TypeError, match="bound method"):
            graph.deps(Calc.sum)


class TestDecoratedBehaviour:
    def test_node_preserves_method_metadata(self):
        class Calc:
            @node
            def a(self):
                """Return one."""
                return 1

        assert Calc.a.__name__ == "a"
        assert Calc.a.__doc__ == "Return one."

    def test_nodes_are_still_callable(self):
        calc = make_calc()()
        assert calc.a() == 1
        assert calc.b() == 2
        assert calc.sum() == 1 + 2 + 4 + 1

    def test_node_outside_a_class_is_rejected(self):
        @node
        def a():
            return 1

        with pytest.raises(TypeError, match="inside a class"):
            a()


class TestRewrite:
    """@node rewrites the body into a pure function of its input values,
    ivs, plus a spec for how each input is produced:

        def fib(self, node, ivs):
            return ivs[0] if ivs[0] < 2 else ivs[1] + ivs[2]

        ivs[0] = n
        ivs[1] = self.fib(n - 1) if not n < 2
        ivs[2] = self.fib(n - 2) if not n < 2
    """

    def test_parameters_and_node_calls_become_input_values(self):
        class Calc:
            @node
            def fib(self, n):
                return n if n < 2 else self.fib(n - 1) + self.fib(n - 2)

        assert graph.code(Calc.fib) == (
            "def fib(self, node, ivs):\n"
            "    return ivs[0] if ivs[0] < 2 else ivs[1] + ivs[2]"
        )

    def test_inputs_list_arguments_then_calls_with_their_guards(self):
        class Calc:
            @node
            def fib(self, n):
                return n if n < 2 else self.fib(n - 1) + self.fib(n - 2)

        assert [str(i) for i in graph.inputs(Calc.fib)] == [
            "n",
            "self.fib(n - 1) if not n < 2",
            "self.fib(n - 2) if not n < 2",
        ]

    def test_arguments_are_terminals_and_calls_are_edges(self):
        class Calc:
            @node
            def fib(self, n):
                return n if n < 2 else self.fib(n - 1) + self.fib(n - 2)

        n, left, right = graph.inputs(Calc.fib)
        assert isinstance(n, graph.Value)
        assert isinstance(left, graph.Edge) and left.target == "fib"
        assert isinstance(right, graph.Edge) and right.target == "fib"

    def test_undecorated_calls_stay_in_the_body(self):
        Calc = make_calc()

        assert graph.code(Calc.sum) == (
            "def sum(self, node, ivs):\n    return ivs[0] + ivs[1] + self.c() + 1"
        )
        assert [str(i) for i in graph.inputs(Calc.sum)] == ["self.a()", "self.b()"]

    def test_module_level_calls_stay_in_the_body(self):
        class Calc:
            @node
            def a(self):
                return 1

            @node
            def sum(self):
                return self.a() + helper()

        assert graph.code(Calc.sum) == (
            "def sum(self, node, ivs):\n    return ivs[0] + helper()"
        )
        assert Calc().sum() == 1

    def test_early_return_guards_what_follows(self):
        class Calc:
            @node
            def fib(self, n):
                if n < 2:
                    return n
                return self.fib(n - 1) + self.fib(n - 2)

        assert [str(i) for i in graph.inputs(Calc.fib)] == [
            "n",
            "self.fib(n - 1) if not n < 2",
            "self.fib(n - 2) if not n < 2",
        ]
        assert Calc().fib(6) == 8

    def test_short_circuit_guards(self):
        class Calc:
            @node
            def a(self):
                return 0

            @node
            def b(self):
                return 2

            @node
            def either(self):
                return self.a() or self.b()

        assert [str(i) for i in graph.inputs(Calc.either)] == [
            "self.a()",
            "self.b() if not self.a()",
        ]
        assert Calc().either() == 2

    def test_node_calls_nested_in_arguments_are_evaluated_first(self):
        class Calc:
            @node
            def one(self):
                return 1

            @node
            def double(self, n):
                return n * 2

            @node
            def answer(self):
                return self.double(self.one())

        calc = Calc()
        assert [str(i) for i in graph.inputs(Calc.answer)] == [
            "self.one()",
            "self.double(self.one())",
        ]
        assert graph.deps(calc.answer) == {(calc, Calc.one), (calc, Calc.double, 1)}
        assert calc.answer() == 2

    def test_nodes_may_reference_ones_defined_later_in_the_class(self):
        class Parity:
            @node
            def even(self, n):
                return True if n == 0 else self.odd(n - 1)

            @node
            def odd(self, n):
                return False if n == 0 else self.even(n - 1)

        p = Parity()
        assert graph.deps(p.even, 2) == {(p, Parity.odd, 1)}
        assert p.even(4) is True
        assert p.odd(4) is False


def helper():
    """A module-level function that is deliberately not a node."""
    return 0


def make_fib(evaluated=None):
    class Fib:
        @node
        def fib(self, n):
            if evaluated is not None:
                evaluated.append(n)
            return n if n < 2 else self.fib(n - 1) + self.fib(n - 2)

    return Fib


class TestStaticDeps:
    """A cell's dependencies come from its input specs, so they can be found
    without running its body. Which cells they are may still depend on the
    *values* of earlier inputs: those edges change the shape of the graph.
    """

    def test_deps_are_known_without_evaluating(self):
        evaluated = []
        Fib = make_fib(evaluated)
        f = Fib()

        assert graph.deps(f.fib, 6) == {(f, Fib.fib, 5), (f, Fib.fib, 4)}
        assert graph.deps(f.fib, 5) == {(f, Fib.fib, 4), (f, Fib.fib, 3)}
        assert evaluated == []

    def test_guarded_edges_are_absent_in_the_base_case(self):
        f = make_fib()()

        assert graph.deps(f.fib, 0) == frozenset()
        assert graph.deps(f.fib, 1) == frozenset()

    def test_a_parameterised_node_has_no_cells_until_one_is_referenced(self):
        f = make_fib()()
        assert graph.all_nodes() == ()

        graph.deps(f.fib, 2)
        assert names(graph.all_nodes()) == {"fib(2)", "fib(1)", "fib(0)"}

    def test_keyword_and_positional_args_name_the_same_cell(self):
        Fib = make_fib()
        f = Fib()

        assert (
            graph.deps(f.fib, 4)
            == graph.deps(f.fib, n=4)
            == {(f, Fib.fib, 3), (f, Fib.fib, 2)}
        )

    def test_zero_arg_node_depending_on_a_parameterised_one(self):
        class Calc:
            @node
            def fib(self, n):
                return n if n < 2 else self.fib(n - 1) + self.fib(n - 2)

            @node
            def answer(self):
                return self.fib(4) + 1

        calc = Calc()
        assert graph.deps(calc.answer) == {(calc, Calc.fib, 4)}
        assert calc.answer() == 4

    def test_edge_whose_shape_depends_on_another_cells_value(self):
        class Calc:
            @node
            def fib(self, n):
                return n if n < 2 else self.fib(n - 1) + self.fib(n - 2)

            @node
            def threshold(self):
                return 3

            @node
            def pick(self, n):
                return self.fib(n) if n > self.threshold() else 0

        calc = Calc()
        assert [str(i) for i in graph.inputs(Calc.pick)] == [
            "n",
            "self.threshold()",
            "self.fib(n) if n > self.threshold()",
        ]
        # Deciding whether fib(n) is an edge needs threshold's value, but
        # never fib's.
        assert graph.deps(calc.pick, 5) == {(calc, Calc.threshold), (calc, Calc.fib, 5)}
        assert graph.deps(calc.pick, 1) == {(calc, Calc.threshold)}

    def test_cells_are_shared_between_callers(self):
        f = make_fib()()
        f.fib(5)
        f.fib(4)

        assert sum(1 for obj, fn, *args in graph.all_nodes() if args == [4]) == 1

    def test_a_subclass_may_override_a_node(self):
        Calc = make_calc()

        class Override(Calc):
            @node
            def a(self):
                return 10

        o = Override()
        assert graph.deps(o.sum) == {(o, Override.a), (o, Calc.b)}
        assert o.sum() == 10 + 2 + 4 + 1


class TestEvaluation:
    """Evaluation follows the graph: a cell's inputs are produced before its
    body runs, so the leaves are evaluated first, and every cell only once.
    """

    def test_leaves_run_first_and_each_cell_runs_once(self):
        evaluated = []
        f = make_fib(evaluated)()

        assert f.fib(5) == 5
        assert evaluated == [1, 0, 2, 3, 4, 5]

    def test_results_are_memoised_across_calls(self):
        evaluated = []
        f = make_fib(evaluated)()

        f.fib(5)
        f.fib(5)
        f.fib(3)
        assert evaluated == [1, 0, 2, 3, 4, 5]

    def test_objects_are_memoised_separately(self):
        evaluated = []
        Fib = make_fib(evaluated)
        x, y = Fib(), Fib()

        x.fib(2)
        y.fib(2)
        assert evaluated == [1, 0, 2, 1, 0, 2]

    def test_every_evaluated_cell_is_a_node(self):
        f = make_fib()()
        f.fib(4)

        assert names(graph.all_nodes()) == {
            "fib(4)",
            "fib(3)",
            "fib(2)",
            "fib(1)",
            "fib(0)",
        }

    def test_parameterised_node_computes_correctly(self):
        f = make_fib()()
        assert [f.fib(n) for n in range(8)] == [0, 1, 1, 2, 3, 5, 8, 13]


class TestUnsupported:
    """Patterns that cannot be turned into a fixed list of inputs, or that
    would let a node see more than functions and constants, fail when the
    class is created rather than silently building the wrong graph."""

    def test_reference_to_a_member_variable(self):
        with pytest.raises(ValueError, match="member variable self.x"):

            class Calc:
                def __init__(self):
                    self.x = 1

                @node
                def total(self):
                    return self.x + 1

    def test_self_used_as_a_value(self):
        with pytest.raises(ValueError, match="'self' may only be used to call"):

            class Calc:
                @node
                def me(self):
                    return helper_taking(self)

    def test_node_call_inside_a_loop(self):
        with pytest.raises(ValueError, match="loop"):

            class Calc:
                @node
                def a(self):
                    return 1

                @node
                def total(self):
                    acc = 0
                    for _ in range(3):
                        acc += self.a()
                    return acc

    def test_node_call_whose_argument_is_a_local(self):
        with pytest.raises(ValueError, match="local 'x'"):

            class Calc:
                @node
                def double(self, n):
                    return n * 2

                @node
                def answer(self):
                    x = 3
                    return self.double(x)

    def test_rebinding_a_parameter(self):
        with pytest.raises(ValueError, match="rebound"):

            class Calc:
                @node
                def bump(self, n):
                    n = n + 1
                    return n

    def test_node_without_self(self):
        with pytest.raises(ValueError, match="needs a self parameter"):

            class Calc:
                @node
                def a():
                    return 1


def helper_taking(obj):
    return obj
