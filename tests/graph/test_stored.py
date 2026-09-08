"""Nodes declared with @node(node.Stored).

A stored node is the object's persisted state. It is otherwise an ordinary
node -- the marker only says the value should survive the process.
"""

import pytest

import graph
from graph import node


def make_marked():
    class Marked:
        @node(node.Stored)
        def kept(self):
            return 1

        @node
        def derived(self):
            return self.kept() + 1

    return Marked


class TestMarkers:
    def test_a_stored_node_is_still_a_node(self):
        Marked = make_marked()
        m = Marked()

        assert m.kept() == 1
        assert graph.deps(m.derived) == {(m, Marked.kept)}

    def test_the_bare_decorator_still_works(self):
        Marked = make_marked()

        assert Marked.kept.stored
        assert not Marked.derived.stored

    def test_stored_nodes_are_listed(self):
        assert graph.stored_nodes(make_marked()) == ("kept",)

    def test_an_unmarked_class_has_none(self):
        class Plain:
            @node
            def a(self):
                return 1

        assert graph.stored_nodes(Plain) == ()

    def test_markers_are_inherited(self):
        Marked = make_marked()

        class Extended(Marked):
            @node(node.Stored)
            def extra(self):
                return 2

        assert graph.stored_nodes(Extended) == ("kept", "extra")

    def test_an_override_can_drop_stored(self):
        Marked = make_marked()

        class Plain(Marked):
            @node
            def kept(self):
                return 3

        assert graph.stored_nodes(Plain) == ()

    def test_an_unknown_marker_is_rejected(self):
        with pytest.raises(TypeError, match="does not take"):
            # Wrong on purpose: a type checker rejects it too, which is the
            # point -- this is the runtime half of the same guarantee.
            node("nonsense", "also nonsense")  # ty: ignore[invalid-argument-type]  # pyright: ignore[reportArgumentType]


class TestStoredMustBeACell:
    def test_a_stored_node_may_not_take_parameters(self):
        with pytest.raises(ValueError, match="takes parameters"):

            class Bad:
                @node(node.Stored)
                def value(self, n):
                    return n
