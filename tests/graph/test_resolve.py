"""Resolving one input at a time.

Expansion is all-or-nothing: ask what a cell depends on and every edge it has
is resolved, evaluating whatever that takes. Resolution is the other end of
the same question -- one slot, one answer, and only that slot's own closure
evaluated to get it.

That is what makes the cost of looking visible. A slot whose closure reaches
no edge is resolved for free, so a cell view fills those in without being
asked; anything dearer waits until someone asks for it by name.
"""

import graph
from graph import node
from tests.helpers import make_book, make_fib, make_pricer


def make_picker(evaluated=None):
    """Two independent picks in one body: `item(i())` and `item(j())`.

    Each call site reads one index and nothing else, so `needed` covers both
    while either slot's own closure covers one. Resolving one of them must
    leave the other index unevaluated.
    """

    def record(name):
        if evaluated is not None:
            evaluated.append(name)

    class Picker:
        @node
        def i(self):
            record("i")
            return 1

        @node
        def j(self):
            record("j")
            return 3

        @node
        def item(self, n):
            record(f"item({n})")
            return n * 10

        @node
        def combo(self):
            record("combo")
            return self.item(self.i()) + self.item(self.j())

    return Picker()


class TestResolvingOneInput:
    """One input of one cell, resolved on its own."""

    def test_an_input_resolves_to_the_cells_it_names(self):
        book, _ = make_book()

        cell = graph.cell(book.total.key(True))

        assert cell.resolve(1) == (book.rate.key(),)

    def test_resolved_cells_are_views_in_the_same_graph(self):
        book, _ = make_book()

        (rate,) = graph.cell(book.total.key(True)).resolve(1)

        assert isinstance(rate, graph.Cell)
        assert rate.method_name == "rate"

    def test_resolving_fills_the_slot_in(self):
        book, (one, two) = make_book()
        cell = graph.cell(book.total.key(True))
        assert cell.slots[4].cells is graph.UNRESOLVED

        cell.resolve(4)

        assert cell.slots[4].cells == (one.pv.key(), two.pv.key())

    def test_resolving_one_input_evaluates_only_its_own_closure(self):
        evaluated = []
        picker = make_picker(evaluated)

        cell = graph.cell(picker.combo.key())
        left = cell.resolve(1)

        assert left == (picker.item.key(1),)
        assert evaluated == ["i"]  # not j, which the other call site reads

    def test_expansion_by_contrast_evaluates_everything_needed(self):
        evaluated = []
        picker = make_picker(evaluated)

        graph.deps(picker.combo)

        assert sorted(evaluated) == ["i", "j"]

    def test_resolving_the_same_input_twice_costs_nothing_the_second_time(self):
        evaluated = []
        picker = make_picker(evaluated)
        cell = graph.cell(picker.combo.key())

        first = cell.resolve(1)
        evaluated.clear()

        assert cell.resolve(1) == first
        assert evaluated == []


class TestStaticResolutionComesFree:
    """A slot whose closure reaches no edge is filled in without being asked."""

    def test_statically_resolvable_slots_are_resolved_when_the_view_is_built(self):
        evaluated = []
        book, _ = make_book(evaluated)

        slots = graph.cell(book.total.key(True)).slots

        assert slots[1].cells == (book.rate.key(),)
        assert slots[3].cells == (book.positions.key(),)
        assert evaluated == []

    def test_slots_that_are_not_statically_resolvable_start_unresolved(self):
        book, _ = make_book()

        slots = graph.cell(book.total.key(True)).slots

        assert slots[2].cells is graph.UNRESOLVED
        assert slots[4].cells is graph.UNRESOLVED

    def test_an_unresolved_slot_says_what_is_blocking_it(self):
        book, _ = make_book()

        slots = graph.cell(book.total.key(True)).slots

        assert slots[4].blocked_by == frozenset({3})
        assert str(slots[3]) == "self.positions() if live"

    def test_a_slot_that_is_not_an_edge_resolves_to_no_cells(self):
        """A terminal and a hoisted local are values, not cells -- but they
        are still resolved, not left looking unexplored."""
        book, _ = make_book()

        slots = graph.cell(book.total.key(True)).slots

        assert slots[0].cells == ()
        assert graph.cell(book.total.key(True)).resolve(2) == ()

    def test_a_recursive_call_site_resolves_without_evaluation(self):
        """fib(n - 1) reads the node's own parameter, and a terminal's value
        comes free with the key, so the call site costs nothing."""
        evaluated = []
        Fib = make_fib(evaluated)
        f = Fib()

        _, left, right = graph.cell((f, Fib.fib, 6)).slots

        assert left.cells == ((f, Fib.fib, 5),)
        assert right.cells == ((f, Fib.fib, 4),)
        assert evaluated == []


class TestResolvingToNoCells:
    """Resolved to nothing is a different answer from not yet resolved."""

    def test_a_guard_that_blocks_its_call_site_resolves_to_no_cells(self):
        book, _ = make_book()

        slots = graph.cell(book.total.key(False)).slots

        assert slots[3].cells == ()
        assert slots[3].cells is not graph.UNRESOLVED

    def test_a_map_edge_over_an_empty_collection_resolves_to_no_cells(self):
        book, _ = make_book(holdings=lambda one, two: ())

        cell = graph.cell(book.total.key(True))

        assert cell.resolve(4) == ()
        assert cell.slots[4].cells is not graph.UNRESOLVED

    def test_no_cells_and_not_yet_resolved_do_not_compare_equal(self):
        book, _ = make_book()

        unresolved = graph.cell(book.total.key(True)).slots[4].cells

        assert unresolved != ()
        assert str(unresolved) == "not yet resolved"


class TestMapEdges:
    """One cell per element, in the collection's own order."""

    def test_a_map_edge_resolves_to_one_cell_per_element(self):
        book, (one, two) = make_book()

        cells = graph.cell(book.total.key(True)).resolve(4)

        assert cells == (one.pv.key(), two.pv.key())

    def test_duplicates_are_kept(self):
        book, (one, two) = make_book(holdings=lambda one, two: (one, two, one))

        cells = graph.cell(book.total.key(True)).resolve(4)

        assert cells == (one.pv.key(), two.pv.key(), one.pv.key())

    def test_the_collections_own_order_is_kept(self):
        book, (one, two) = make_book(holdings=lambda one, two: (two, one))

        cells = graph.cell(book.total.key(True)).resolve(4)

        assert cells == (two.pv.key(), one.pv.key())


class TestDependenciesAreLeftAlone:
    """Full expansion stays the only writer of the dependency map."""

    def test_resolving_one_input_records_no_dependency_for_the_cell(self):
        book, _ = make_book()

        graph.cell(book.total.key(True)).resolve(4)

        # Nothing has been told that total reads positions, because nothing
        # asked total what it depends on.
        assert graph.cell(book.positions.key()).outputs == frozenset()

    def test_expansion_after_partial_resolution_finds_every_dependency(self):
        book, (one, two) = make_book()

        graph.cell(book.total.key(True)).resolve(4)
        deps = graph.cell(book.total.key(True)).expand()

        assert deps == {
            book.rate.key(),
            book.positions.key(),
            one.pv.key(),
            two.pv.key(),
        }

    def test_dirty_propagation_is_unaffected(self):
        pricer = make_pricer()()
        pricer.pv()

        graph.cell(pricer.pv.key()).resolve(0)
        pricer.spot.set_value(110.0)

        assert graph.cell(pricer.pv.key()).value.state is graph.ValueState.DIRTY
        assert pricer.pv() == 40.0  # recomputed from the new spot
