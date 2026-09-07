"""Evaluation follows the graph.

A cell's inputs are produced before its body runs, so the leaves are evaluated
first and every cell runs at most once.
"""

import graph
from tests.helpers import make_fib, names


class TestEvaluation:
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


class TestSeparateGraphs:
    """Nodes are compiled once per class, but cells and memoised values belong
    to a graph, so independent graphs evaluate the same class independently."""

    def test_graphs_do_not_share_cells_or_values(self):
        evaluated = []
        Fib = make_fib(evaluated)
        f = Fib()
        key = graph.make_key(f, Fib.fib, (2,))

        first, second = graph.Graph(), graph.Graph()
        assert first.evaluate(key) == 1
        assert second.evaluate(key) == 1

        # Each memoises on its own, so both ran the bodies.
        assert evaluated == [1, 0, 2, 1, 0, 2]
        assert names(first.all_nodes()) == names(second.all_nodes())

    def test_the_default_graph_is_untouched_by_others(self):
        Fib = make_fib()
        f = Fib()

        other = graph.Graph()
        assert other.deps(f.fib, 3) == {(f, Fib.fib, 2), (f, Fib.fib, 1)}
        assert other.all_nodes() != ()
        assert graph.all_nodes() == ()
