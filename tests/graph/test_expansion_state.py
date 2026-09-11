"""One record of what a cell's expansion knows, held by the graph.

`expand` and `expand_slot` write into the same per-slot record: one entry per
`ivs` slot, holding the cells that slot names or `UNRESOLVED` where nothing has
looked yet. A partial record is a first-class thing rather than something to be
avoided -- `UNRESOLVED` is what keeps it from reading as a complete one -- so a
slot resolved once stays resolved, whoever asked.

Two things follow, and both are the point. A second view of a key finds the
work the first one paid for; and a cell that has only ever had one slot
expanded is in the reverse index, so dirty propagation reaches it.
"""

import dataclasses

import graph
from graph import ValueState, node
from tests.helpers import make_book, make_chooser, make_pricer


def clean_cells_are_fully_expanded():
    """The invariant that replaces "never write a partial record".

    A cell carrying a value the graph will hand out as current has every slot
    resolved. A dirty cell is exempt: resetting the slots that could have moved
    is what makes it dirty in the shape as well as in the number.
    """
    return all(
        graph.cell(key).expanded
        for key in graph.all_nodes()
        if graph.cell(key).value.state is ValueState.CLEAN
    )


class TestASlotStaysResolved:
    """`expand_slot` records its answer, so the next asker finds it."""

    def test_a_second_view_of_the_same_key_finds_the_slot_resolved(self):
        book, (one, two) = make_book()

        graph.cell(book.total.key(True)).expand_slot(4)

        assert graph.cell(book.total.key(True)).slots[4].cells == (
            one.pv.key(),
            two.pv.key(),
        )

    def test_a_second_view_runs_no_body_to_say_so(self):
        evaluated = []
        book, _ = make_book(evaluated)
        graph.cell(book.total.key(True)).expand_slot(4)
        evaluated.clear()

        graph.cell(book.total.key(True)).expand_slot(4)

        assert evaluated == []

    def test_two_views_of_one_key_answer_slots_identically(self):
        book, _ = make_book()
        first, second = (graph.cell(book.total.key(True)) for _ in range(2))

        first.expand_slot(4)

        assert [slot.cells for slot in first.slots] == [
            slot.cells for slot in second.slots
        ]


class TestPartialRecordsAreVisible:
    """A cell one slot has been expanded on is in the graph, not outside it."""

    def test_a_slot_expanded_on_its_own_is_recorded(self):
        book, (one, _) = make_book()

        graph.cell(book.total.key(True)).expand_slot(4)

        assert graph.cell(one.pv.key()).outputs == {book.total.key(True)}

    def test_outputs_names_exactly_the_cells_with_a_resolved_slot(self):
        """Partial by nature, never wrong: `positions` is named by a slot that
        resolves statically, so the reverse index has it before anyone asks."""
        book, _ = make_book()

        assert graph.cell(book.total.key(True)).slots  # every slot is described
        assert graph.cell(book.positions.key()).outputs == {book.total.key(True)}
        assert graph.cell(book.rate.key()).outputs == {book.total.key(True)}

    def test_a_cell_with_a_slot_expanded_joins_the_graph(self):
        book, _ = make_book()

        graph.cell(book.total.key(True)).expand_slot(4)

        assert book.total.key(True) in graph.all_nodes()


class TestBeingExpanded:
    """Whether every slot is resolved is read off the slots."""

    def test_a_cell_nothing_has_expanded_is_not_expanded(self):
        book, _ = make_book()

        assert not graph.cell(book.total.key(True)).expanded

    def test_one_slot_short_is_not_expanded(self):
        book, _ = make_book()

        graph.cell(book.total.key(True)).expand_slot(4)

        assert not graph.cell(book.total.key(True)).expanded

    def test_a_cell_that_was_expanded_says_so(self):
        book, _ = make_book()

        graph.cell(book.total.key(True)).expand()

        assert graph.cell(book.total.key(True)).expanded

    def test_being_expanded_is_the_slots_saying_so(self):
        book, _ = make_book()
        cell = graph.cell(book.total.key(True))
        cell.expand()

        assert cell.expanded == all(
            slot.cells is not graph.UNRESOLVED for slot in cell.slots
        )


class TestTheCleanValueInvariant:
    """A value the graph hands out as current comes with every slot resolved."""

    def test_an_evaluated_cell_has_every_slot_resolved(self):
        book, _ = make_book()
        book.total(True)

        assert graph.cell(book.total.key(True)).expanded
        assert clean_cells_are_fully_expanded()

    def test_evaluating_completes_a_partial_record(self):
        book, _ = make_book()
        graph.cell(book.total.key(True)).expand_slot(4)

        book.total(True)

        assert clean_cells_are_fully_expanded()

    def test_the_invariant_survives_a_value_being_set(self):
        pricer = make_pricer()()
        pricer.pv()

        pricer.spot.set_value(110.0)

        assert clean_cells_are_fully_expanded()

    def test_the_invariant_survives_a_diddle(self):
        pricer = make_pricer()()
        pricer.pv()

        with graph.diddle((pricer.spot, 110.0)):
            pricer.pv()
            assert clean_cells_are_fully_expanded()

        assert clean_cells_are_fully_expanded()


class TestDirtyingResetsWhatCouldHaveMoved:
    """A dirtied cell forgets the slots whose cells a value could change."""

    def test_a_slot_that_is_not_statically_resolvable_is_reset(self):
        book, _ = make_book()
        book.total(True)

        book.rate.set_value(0.1)

        assert graph.cell(book.total.key(True)).slots[4].cells is graph.UNRESOLVED

    def test_a_statically_resolvable_slot_is_left_alone(self):
        """Nothing a value can change reaches a slot reading only terminals and
        hoisted locals, so resetting it would throw away a correct answer."""
        book, _ = make_book()
        book.total(True)

        book.rate.set_value(0.1)

        slots = graph.cell(book.total.key(True)).slots
        assert slots[1].cells == (book.rate.key(),)
        assert slots[3].cells == (book.positions.key(),)

    def test_the_reverse_index_drops_the_cells_a_reset_slot_named(self):
        Chooser = make_chooser()
        c = Chooser()
        c.pick()

        c.which.set_value(3)

        assert graph.cell(c.item.key(1)).outputs == frozenset()

    def test_a_cell_only_one_slot_was_expanded_on_is_reached(self):
        """The case that was invisible before: nothing had recorded `pick`, so
        propagation walked straight past it. Its value state still reads
        uncomputed -- it has no value to go stale -- but it is marked, so the
        slot that moved is reset rather than left naming the old cell."""
        Chooser = make_chooser()
        c = Chooser()
        graph.cell(c.pick.key()).expand_slot(1)

        c.which.set_value(3)

        assert c.pick.is_dirty()
        assert graph.cell(c.pick.key()).slots[1].cells is graph.UNRESOLVED

    def test_a_reset_slot_resolves_again_to_the_cell_it_now_names(self):
        Chooser = make_chooser()
        c = Chooser()
        graph.cell(c.pick.key()).expand_slot(1)

        c.which.set_value(3)

        assert graph.cell(c.pick.key()).expand_slot(1) == (c.item.key(3),)

    def test_setting_a_value_dirties_the_cell_whose_slot_it_moves(self):
        Chooser = make_chooser()
        c = Chooser()
        c.pick()

        c.which.set_value(3)

        assert graph.cell(c.pick.key()).value.state is ValueState.DIRTY
        assert c.pick() == 30


def make_shared_local(evaluated):
    """Two call sites reading one hoisted local, which reads an edge.

    The local is what tells one pass from one pass per slot: both edges are
    blocked by it, so expanding them separately would evaluate it twice.
    """

    class Shared:
        @node
        def base(self):
            return 2

        @node
        def item(self, n):
            return n * 10

        @node
        def both(self):
            step = self.base() + 1
            return self.item(step) + self.item(step + 1)

    compiled = Shared.both.compiled
    assert compiled is not None  # set by __set_name__ at class creation
    local = next(inp for inp in compiled.inputs if isinstance(inp, graph.Local))
    inner = local.expr

    def spy(obj, key, ivs):
        evaluated.append(local.name)
        return inner(obj, key, ivs)

    Shared.both.compiled = dataclasses.replace(
        compiled,
        inputs=tuple(
            dataclasses.replace(inp, expr=spy) if inp is local else inp
            for inp in compiled.inputs
        ),
    )
    return Shared()


class TestExpandIsOnePass:
    """`expand` is `expand_slot` over every slot -- conceptually, not literally."""

    def test_expanding_a_cell_fills_one_ivs_between_every_slot(self):
        evaluated = []
        shared = make_shared_local(evaluated)

        graph.cell(shared.both.key()).expand()

        assert evaluated == ["step"]  # not once per edge that reads it

    def test_expanding_produces_the_dependencies_every_slot_names(self):
        book, (one, two) = make_book()

        deps = graph.cell(book.total.key(True)).expand()

        assert deps == {
            book.rate.key(),
            book.positions.key(),
            one.pv.key(),
            two.pv.key(),
        }

    def test_a_cell_expanded_slot_by_slot_names_the_same_cells(self):
        book, _ = make_book()
        cell = graph.cell(book.total.key(True))

        slot_by_slot = set()
        for slot in cell.slots:
            slot_by_slot.update(cell.expand_slot(slot.index))

        assert slot_by_slot == cell.expand()


class TestDiddleRestoresRecords:
    """Leaving a scope puts the records back exactly as it found them."""

    def test_a_slot_expanded_inside_the_scope_is_forgotten_on_exit(self):
        book, _ = make_book()

        with graph.diddle((book.rate, 0.1)):
            graph.cell(book.total.key(True)).expand_slot(4)

        assert graph.cell(book.total.key(True)).slots[4].cells is graph.UNRESOLVED

    def test_a_record_the_scope_changed_comes_back(self):
        Chooser = make_chooser()
        c = Chooser()
        c.pick()

        with graph.diddle((c.which, 5)):
            assert c.pick() == 50

        assert graph.cell(c.pick.key()).slots[1].cells == (c.item.key(1),)
        assert graph.cell(c.item.key(1)).outputs == {c.pick.key()}
        assert graph.cell(c.item.key(5)).outputs == frozenset()

    def test_a_cell_the_scope_expanded_is_forgotten_on_exit(self):
        book, _ = make_book()

        with graph.diddle((book.rate, 0.1)):
            book.total(True)

        assert not graph.cell(book.total.key(True)).expanded
