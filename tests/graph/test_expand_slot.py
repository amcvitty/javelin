"""Expanding one slot at a time.

`expand` is all-or-nothing: ask what a cell depends on and every slot it has
is taken at once, evaluating whatever that costs between them. `expand_slot`
asks the same question of one slot -- one answer, and only that slot's own
closure evaluated to get it.

That is what makes the cost of looking visible. A slot whose closure reaches
no edge is resolved for free, so a cell view fills those in without being
asked; anything dearer waits until someone asks for it by name.

Either way the answer is recorded, one slot of the cell's record at a time --
what that means for the graph as a whole is in test_expansion_state.py.
"""

import graph
from graph import node
from tests.helpers import make_book, make_fib, make_pricer


def make_picker(evaluated=None):
    """Two independent picks in one body: `item(i())` and `item(j())`.

    Each call site reads one index and nothing else, so `needed` covers both
    while either slot's own closure covers one. Expanding one of them must
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


class TestExpandingOneSlot:
    """One input of one cell, expanded on its own."""

    def test_an_input_resolves_to_the_cells_it_names(self):
        book, _ = make_book()

        cell = graph.cell(book.total.key(True))

        assert cell.expand_slot(1) == (book.rate.key(),)

    def test_resolved_cells_are_views_in_the_same_graph(self):
        book, _ = make_book()

        (rate,) = graph.cell(book.total.key(True)).expand_slot(1)

        assert isinstance(rate, graph.Cell)
        assert rate.method_name == "rate"

    def test_expanding_a_slot_fills_it_in(self):
        book, (one, two) = make_book()
        cell = graph.cell(book.total.key(True))
        assert cell.slots[4].cells is graph.UNRESOLVED

        cell.expand_slot(4)

        assert cell.slots[4].cells == (one.pv.key(), two.pv.key())

    def test_expanding_one_slot_evaluates_only_its_own_closure(self):
        evaluated = []
        picker = make_picker(evaluated)

        cell = graph.cell(picker.combo.key())
        left = cell.expand_slot(1)

        assert left == (picker.item.key(1),)
        assert evaluated == ["i"]  # not j, which the other call site reads

    def test_expanding_the_whole_cell_by_contrast_evaluates_everything_needed(self):
        evaluated = []
        picker = make_picker(evaluated)

        graph.deps(picker.combo)

        assert sorted(evaluated) == ["i", "j"]

    def test_expanding_the_same_slot_twice_costs_nothing_the_second_time(self):
        evaluated = []
        picker = make_picker(evaluated)
        cell = graph.cell(picker.combo.key())

        first = cell.expand_slot(1)
        evaluated.clear()

        assert cell.expand_slot(1) == first
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
        assert graph.cell(book.total.key(True)).expand_slot(2) == ()

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


class TestSlotsThatResolveToNoCells:
    """Resolved to nothing is a different answer from not yet resolved."""

    def test_a_guard_that_blocks_its_call_site_resolves_to_no_cells(self):
        book, _ = make_book()

        slots = graph.cell(book.total.key(False)).slots

        assert slots[3].cells == ()
        assert slots[3].cells is not graph.UNRESOLVED

    def test_a_map_edge_over_an_empty_collection_resolves_to_no_cells(self):
        book, _ = make_book(holdings=lambda one, two: ())

        cell = graph.cell(book.total.key(True))

        assert cell.expand_slot(4) == ()
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

        cells = graph.cell(book.total.key(True)).expand_slot(4)

        assert cells == (one.pv.key(), two.pv.key())

    def test_duplicates_are_kept(self):
        book, (one, two) = make_book(holdings=lambda one, two: (one, two, one))

        cells = graph.cell(book.total.key(True)).expand_slot(4)

        assert cells == (one.pv.key(), two.pv.key(), one.pv.key())

    def test_the_collections_own_order_is_kept(self):
        book, (one, two) = make_book(holdings=lambda one, two: (two, one))

        cells = graph.cell(book.total.key(True)).expand_slot(4)

        assert cells == (two.pv.key(), one.pv.key())


def make_nested():
    """A pick whose index is itself a cell with a dependency of its own.

    Expanding the pick's slot has to evaluate `held`, and evaluating `held`
    records what *it* reads -- so the shape tells the one slot `expand_slot`
    records apart from the whole record evaluating a cell writes.
    """

    class Nested:
        @node
        def base(self):
            return 1

        @node
        def held(self):
            return self.base() + 1

        @node
        def item(self, n):
            return n * 10

        @node
        def pick(self):
            return self.item(self.held())

    return Nested()


class TestWhatExpandingOneSlotRecords:
    """One slot, recorded as one slot: the rest of the record is untouched."""

    def test_expanding_one_slot_records_that_slot_and_no_other(self):
        book, (one, two) = make_book()

        graph.cell(book.total.key(True)).expand_slot(4)

        slots = graph.cell(book.total.key(True)).slots
        assert slots[4].cells == (one.pv.key(), two.pv.key())
        assert slots[2].cells is graph.UNRESOLVED  # nobody asked about this one

    def test_the_cell_being_expanded_joins_the_graph(self):
        """A cell one slot has been expanded on is a cell the graph knows
        about -- which is what lets dirty propagation reach it."""
        nested = make_nested()

        graph.cell(nested.pick.key()).expand_slot(1)

        assert nested.pick.key() in graph.all_nodes()

    def test_a_cell_the_closure_evaluates_records_its_own_dependencies(self):
        """Evaluating a cell on the way has always recorded what it reads, and
        a value asked for here is no different from one asked for anywhere
        else -- so `held` reads `base`, and `pick` reads `held`."""
        nested = make_nested()

        graph.cell(nested.pick.key()).expand_slot(1)

        assert graph.cell(nested.base.key()).outputs == {nested.held.key()}
        assert graph.cell(nested.held.key()).outputs == {nested.pick.key()}

    def test_expanding_the_whole_cell_afterwards_finds_every_dependency(self):
        book, (one, two) = make_book()

        graph.cell(book.total.key(True)).expand_slot(4)
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

        graph.cell(pricer.pv.key()).expand_slot(0)
        pricer.spot.set_value(110.0)

        assert graph.cell(pricer.pv.key()).value.state is graph.ValueState.DIRTY
        assert pricer.pv() == 40.0  # recomputed from the new spot
