"""Which cells exist, and what each depends on.

A cell's dependencies come from its compiled inputs, so they can be found
running its body. Which cells they are may still depend on the *values* of
earlier inputs: those edges change the shape of the graph.
"""

import pytest

import graph
from graph import node
from tests.helpers import make_calc, make_fib, names


class TestCells:
    def test_cells_appear_once_referenced(self):
        Calc = make_calc()
        calc = Calc()
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
            (x, Calc.a),
            (x, Calc.b),
            (x, Calc.sum),
            (y, Calc.a),
            (y, Calc.b),
            (y, Calc.sum),
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


class TestStaticDeps:
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
        assert graph.deps(calc.pick, 5) == {
            (calc, Calc.threshold),
            (calc, Calc.fib, 5),
        }
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
