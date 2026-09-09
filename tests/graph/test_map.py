"""Comprehensions: one call site naming one cell per element.

A `MapEdge` is the only input that contributes a variable number of
dependencies, so these tests are about the two things that follow from that --
which cells it names, and when it has to be re-expanded to find out.
"""

import pytest

import graph
from graph import node
from tests.helpers import names


def make_book(prices=(1.0, 2.0, 4.0)):
    """A book over positions, each with a price of its own.

    A node may read neither a member variable nor `self` itself, so each
    position's price is set on its cell rather than carried on the object.
    """
    positions = []

    class Position:
        @node
        def value(self):
            return 0.0

    class Book:
        @node
        def members(self):
            return list(positions)

        @node
        def total(self):
            return sum(p.value() for p in self.members())

    for price in prices:
        position = Position()
        position.value.set_value(price)
        positions.append(position)
    return Book(), Position, positions


class TestWhatItNames:
    def test_every_element_is_a_dependency(self):
        book, position, positions = make_book()

        assert graph.deps(book.total) == {
            (book, type(book).members),
            *((p, position.value) for p in positions),
        }

    def test_the_comprehension_is_one_input(self):
        book, _, _ = make_book()

        kinds = [(type(i).__name__, str(i)) for i in graph.inputs(type(book).total)]
        assert kinds == [
            ("CallEdge", "self.members()"),
            ("MapEdge", "(p.value() for p in self.members())"),
        ]

    def test_the_body_does_not_loop(self):
        book, _, _ = make_book()

        # The whole comprehension became one ivs slot, so the rewritten body
        # is a sum over a list that is handed to it.
        assert "for" not in graph.code(type(book).total)
        assert book.total() == 7.0

    def test_a_list_comprehension_and_a_generator_agree(self):
        class Leaf:
            @node
            def value(self):
                return 3.0

        leaves = [Leaf(), Leaf()]

        class Both:
            @node
            def members(self):
                return leaves

            @node
            def listed(self):
                return sum([m.value() for m in self.members()])

            @node
            def generated(self):
                return sum(m.value() for m in self.members())

        both = Both()
        assert both.listed() == both.generated() == 6.0
        assert graph.deps(both.listed) == graph.deps(both.generated)

    def test_an_empty_collection_names_no_cells(self):
        book, _, _ = make_book(prices=())

        assert graph.deps(book.total) == {(book, type(book).members)}
        assert book.total() == 0

    def test_duplicates_are_one_cell_but_counted_once_each(self):
        book, position, positions = make_book(prices=(5.0,))
        positions.extend([positions[0], positions[0]])

        assert graph.deps(book.total) == {
            (book, type(book).members),
            (positions[0], position.value),
        }
        assert book.total() == 15.0

    def test_order_is_the_collection_s_order(self):
        class Leaf:
            @node
            def value(self):
                return 0

        leaves = [Leaf(), Leaf(), Leaf()]
        for leaf, value in zip(leaves, (1, 2, 3)):
            leaf.value.set_value(value)

        class Ordered:
            @node
            def members(self):
                return leaves

            @node
            def values(self):
                return [leaf.value() for leaf in self.members()]

        assert Ordered().values() == [1, 2, 3]


class TestReExpansion:
    def test_changing_the_collection_changes_the_dependencies(self):
        book, position, positions = make_book()
        first = positions[0]
        book.total()

        book.members.set_value([first])

        assert graph.deps(book.total) == {
            (book, type(book).members),
            (first, position.value),
        }
        assert book.total() == 1.0

    def test_an_element_going_stale_dirties_the_map(self):
        book, _, positions = make_book()
        book.total()
        assert not book.total.is_dirty()

        positions[0].value.set_value(100.0)

        assert book.total.is_dirty()
        assert book.total() == 106.0

    def test_the_collection_is_evaluated_during_expansion(self):
        ran = []

        class Leaf:
            @node
            def value(self):
                ran.append("value")
                return 1.0

        leaves = [Leaf(), Leaf()]

        class Agg:
            @node
            def members(self):
                ran.append("members")
                return leaves

            @node
            def total(self):
                return sum(leaf.value() for leaf in self.members())

        graph.deps(Agg().total)

        # Which cells the map names comes from the collection, so that runs --
        # but the elements' own values are not needed to name them.
        assert ran == ["members"]


class TestElementsThatAreNotNodes:
    def test_plain_methods_on_every_element_are_values_not_cells(self):
        class Plain:
            def value(self):
                return 2.0

        plains = [Plain(), Plain()]

        class Agg:
            @node
            def members(self):
                return plains

            @node
            def total(self):
                return sum(p.value() for p in self.members())

        agg = Agg()
        assert agg.total() == 4.0
        assert graph.deps(agg.total) == {(agg, Agg.members)}

    def test_a_mixed_collection_is_an_error(self):
        class Celled:
            @node
            def value(self):
                return 1.0

        class Plain:
            def value(self):
                return 2.0

        mixed = [Celled(), Plain()]

        class Agg:
            @node
            def members(self):
                return mixed

            @node
            def total(self):
                return sum(m.value() for m in self.members())

        with pytest.raises(TypeError, match="Plain.value is not a node"):
            Agg().total()


class TestGuards:
    def test_a_map_under_a_branch_is_only_a_dependency_when_reached(self):
        class Leaf:
            @node
            def value(self):
                return 1.0

        leaves = [Leaf(), Leaf()]

        class Agg:
            @node
            def members(self):
                return leaves

            @node
            def total(self, aggregate):
                if not aggregate:
                    return 0.0
                return sum(leaf.value() for leaf in self.members())

        agg = Agg()
        assert names(graph.deps(agg.total, False)) == set()
        assert names(graph.deps(agg.total, True)) == {"members", "value"}


class TestReachingAcrossTheGraph:
    def test_the_receiver_may_be_built_from_the_element(self):
        """What a book of position *paths* needs: the element names the object
        rather than being it."""

        class Leaf:
            @node
            def value(self):
                return 7.0

        rows = {"a": Leaf(), "b": Leaf()}

        class Table:
            def row(self, key):
                return rows[key]

            @node
            def keys(self):
                return ["a", "b"]

            @node
            def total(self):
                return sum(self.row(key).value() for key in self.keys())

        table = Table()
        assert table.total() == 14.0
        assert graph.deps(table.total) == {
            (table, Table.keys),
            *((row, Leaf.value) for row in rows.values()),
        }
