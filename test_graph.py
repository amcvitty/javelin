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


def names(fns):
    """Collect __name__ from an iterable of functions, for readable assertions."""
    return {fn.__name__ for fn in fns}


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

        assert set(graph.all_nodes()) == {a}
        assert c not in graph.all_nodes()

    def test_registers_the_decorated_function_objects(self):
        @node
        def a():
            return 1

        @node
        def b():
            return 2

        assert set(graph.all_nodes()) == {a, b}

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

        assert graph.deps(sum) == {a, b}

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
        assert graph.deps(sum) == {b}
        assert graph.deps(b) == {a}

    def test_a_node_called_twice_appears_once(self):
        @node
        def a():
            return 1

        @node
        def sum():
            return a() + a()

        assert graph.deps(sum) == {a}

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
