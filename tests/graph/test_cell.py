"""Describing a cell without resolving it.

A `Cell` is a view over a key and a graph: what the engine already knows about
one cell, gathered in one place so a REPL or a TUI can print it. Building one
and reading every slot evaluates nothing -- the point of the surface is that
looking costs nothing.
"""

import pytest

import graph
from graph import InputKind, ValueState, node
from tests.helpers import make_book, make_calc, make_fib, make_pricer


class TestCellView:
    """A cell view is a thin thing built on demand from a key."""

    def test_a_cell_reports_the_parts_of_its_key(self):
        Fib = make_fib()
        f = Fib()

        cell = graph.cell((f, Fib.fib, 5))

        assert cell.obj is f
        assert cell.node is Fib.fib
        assert cell.args == (5,)
        assert cell.method_name == "fib"
        assert cell.cls is Fib

    def test_a_cell_can_be_built_from_a_bound_node_key(self):
        Calc = make_calc()
        calc = Calc()

        assert graph.cell(calc.sum.key()).args == ()

    def test_the_class_is_the_objects_own(self):
        """A subclass may override a node, so the object's class and the class
        the node was defined on are not the same question."""
        Calc = make_calc()

        class Override(Calc):
            @node
            def a(self):
                return 10

        over = Override()
        cell = graph.cell(over.b.key())

        assert cell.cls is Override
        assert cell.node.owner is Calc

    def test_a_cell_is_not_stored_in_the_graph(self):
        Calc = make_calc()
        calc = Calc()

        graph.cell(calc.sum.key())

        assert graph.all_nodes() == ()

    def test_equality_and_hashing_agree_with_the_key(self):
        Fib = make_fib()
        f = Fib()
        key = (f, Fib.fib, 5)

        cell = graph.cell(key)

        assert cell == key
        assert cell == graph.cell(key)
        assert cell != graph.cell((f, Fib.fib, 4))
        assert hash(cell) == hash(key)
        assert {cell} == {key}

    def test_a_key_that_names_no_node_is_rejected(self):
        Calc = make_calc()
        calc = Calc()

        with pytest.raises(KeyError):
            graph.cell((calc, Calc.c))

    def test_a_key_holding_a_bound_node_is_rejected(self):
        """calc.sum is not what a key holds, and a key built from it would
        match nothing in the graph rather than saying so."""
        Calc = make_calc()
        calc = Calc()

        with pytest.raises(TypeError, match="not a bound one"):
            graph.cell((calc, calc.sum))

    def test_a_cell_prints_as_the_call_it_stands_for(self):
        Fib = make_fib()
        f = Fib()

        assert str(graph.cell((f, Fib.fib, 5))) == "Fib.fib(5)"
        assert "uncomputed" in repr(graph.cell((f, Fib.fib, 5)))


class TestValueStates:
    """Four states, and a stale value is never presentable as a current one."""

    def test_a_cell_that_has_never_run_is_uncomputed(self):
        cell = graph.cell(make_pricer()().pv.key())

        assert cell.value.state is ValueState.UNCOMPUTED
        assert str(cell.value) == "uncomputed"

    def test_an_evaluated_cell_is_memoised_and_clean(self):
        pricer = make_pricer()()
        pricer.pv()

        cell = graph.cell(pricer.pv.key())

        assert cell.value.state is ValueState.CLEAN
        assert cell.value.value == 20.0
        assert str(cell.value) == "20.0"

    def test_a_cell_given_a_value_directly_is_overridden(self):
        pricer = make_pricer()()
        pricer.spot.set_value(110.0)

        cell = graph.cell(pricer.spot.key())

        assert cell.value.state is ValueState.OVERRIDDEN
        assert cell.value.value == 110.0
        assert str(cell.value) == "110.0 (overridden)"

    def test_a_dirtied_cell_reports_dirty_and_keeps_its_stale_value(self):
        pricer = make_pricer()()
        pricer.pv()
        pricer.spot.set_value(110.0)

        cell = graph.cell(pricer.pv.key())

        assert cell.value.state is ValueState.DIRTY
        assert cell.value.value == 20.0  # the pre-diddle value, still stale
        assert str(cell.value) == "20.0 (dirty)"

    def test_the_four_states_are_distinguishable(self):
        Pricer = make_pricer()
        pricer, untouched = Pricer(), Pricer()
        pricer.pv()
        pricer.spot.set_value(110.0)

        states = {
            graph.cell(pricer.pv.key()).value.state,
            graph.cell(pricer.spot.key()).value.state,
            graph.cell(pricer.quantity.key()).value.state,
            graph.cell(untouched.pv.key()).value.state,
        }

        assert states == {
            ValueState.DIRTY,
            ValueState.OVERRIDDEN,
            ValueState.CLEAN,
            ValueState.UNCOMPUTED,
        }

    def test_a_cell_repr_shows_the_state_alongside_the_value(self):
        pricer = make_pricer()()
        pricer.pv()
        pricer.spot.set_value(110.0)

        printed = repr(graph.cell(pricer.pv.key()))

        assert "20.0" in printed
        assert "dirty" in printed


class TestSlots:
    """One slot per `ivs` slot, in slot order, whatever fills it."""

    def test_every_input_appears_as_a_slot_in_ivs_order(self):
        book, _ = make_book()

        slots = graph.cell(book.total.key(True)).slots

        assert [slot.index for slot in slots] == [0, 1, 2, 3, 4]
        assert [str(slot) for slot in slots] == [
            "live",
            "self.rate()",
            "scale = self.rate() * 2.0",
            "self.positions() if live",
            "[p.pv() for p in self.positions()] if live",
        ]

    def test_each_slot_reports_its_kind(self):
        book, _ = make_book()

        slots = graph.cell(book.total.key(True)).slots

        assert [slot.kind for slot in slots] == [
            InputKind.TERMINAL,
            InputKind.CALL_EDGE,
            InputKind.LOCAL,
            InputKind.CALL_EDGE,
            InputKind.MAP_EDGE,
        ]

    def test_each_slot_reports_its_call_site_and_its_guard(self):
        book, _ = make_book()

        slots = graph.cell(book.total.key(True)).slots

        assert slots[4].source == "[p.pv() for p in self.positions()]"
        assert slots[4].guard_source == "live"
        assert slots[1].guard_source is None

    def test_a_slot_that_is_not_an_edge_has_no_guard(self):
        book, _ = make_book()

        slots = graph.cell(book.total.key(True)).slots

        assert (slots[0].guard_source, slots[2].guard_source) == (None, None)

    def test_each_slot_reports_its_read_set(self):
        book, _ = make_book()

        slots = graph.cell(book.total.key(True)).slots

        assert [slot.reads for slot in slots] == [
            frozenset(),
            frozenset(),
            frozenset({1}),
            frozenset({0}),
            frozenset({0, 3}),
        ]

    def test_a_slot_reading_only_terminals_and_locals_resolves_statically(self):
        book, _ = make_book()

        slots = graph.cell(book.total.key(True)).slots

        # The terminal costs nothing; the two call edges read a terminal or
        # nothing at all, so which cell each names is known for free.
        assert [slot.statically_resolvable for slot in slots] == [
            True,
            True,
            False,
            True,
            False,
        ]

    def test_a_slot_that_does_not_resolve_statically_names_its_blockers(self):
        book, _ = make_book()

        slots = graph.cell(book.total.key(True)).slots

        assert slots[2].blocked_by == frozenset({1})  # the local reads an edge
        assert slots[4].blocked_by == frozenset({3})  # which positions, though?

    def test_a_statically_resolvable_slot_names_no_blockers(self):
        book, _ = make_book()

        slots = graph.cell(book.total.key(True)).slots

        assert [slot.blocked_by for slot in slots[:2]] == [frozenset(), frozenset()]

    def test_a_recursive_call_site_resolves_statically(self):
        """Reading nothing is the wrong test: fib(n - 1) reads the node's own
        parameter, but a terminal's value comes free with the key."""
        Fib = make_fib()
        f = Fib()

        _, left, right = graph.cell((f, Fib.fib, 6)).slots

        assert left.reads == frozenset({0})
        assert (left.statically_resolvable, right.statically_resolvable) == (True, True)

    def test_a_slot_that_costs_an_evaluation_reports_its_cells_as_unresolved(self):
        """Which cells such a slot names is in tests/graph/test_resolve.py --
        here, only that it says it does not know yet, and says so distinguishably
        from an edge that resolved to no cells at all."""
        book, _ = make_book()

        slots = graph.cell(book.total.key(True)).slots

        assert [slots[2].cells, slots[4].cells] == [graph.UNRESOLVED] * 2
        assert slots[4].cells != ()
        assert str(graph.UNRESOLVED) == "not yet resolved"


class TestLookingCostsNothing:
    def test_building_a_cell_and_reading_every_slot_runs_no_body(self):
        evaluated = []
        book, _ = make_book(evaluated)

        cell = graph.cell(book.total.key(True))
        described = [
            (
                cell.obj,
                cell.node,
                cell.args,
                cell.method_name,
                cell.cls,
                cell.value,
                cell.outputs,
            ),
            *(
                (
                    slot.index,
                    slot.kind,
                    slot.source,
                    slot.guard_source,
                    slot.reads,
                    slot.statically_resolvable,
                    slot.blocked_by,
                    slot.cells,
                )
                for slot in cell.slots
            ),
        ]

        assert described  # everything above was actually read
        assert evaluated == []


class TestActions:
    def test_a_cell_can_expand_to_the_cells_it_depends_on(self):
        Pricer = make_pricer()
        pricer = Pricer()

        deps = graph.cell(pricer.pv.key()).expand()

        assert deps == {(pricer, Pricer.payoff), (pricer, Pricer.quantity)}
        assert all(isinstance(dep, graph.Cell) for dep in deps)

    def test_a_cell_can_be_evaluated(self):
        pricer = make_pricer()()

        assert graph.cell(pricer.pv.key()).evaluate() == 20.0
        assert graph.cell(pricer.pv.key()).value.state is ValueState.CLEAN


class TestOutputs:
    def test_the_cells_that_read_a_cell_are_reported(self):
        Pricer = make_pricer()
        pricer = Pricer()
        pricer.pv()

        assert graph.cell(pricer.payoff.key()).outputs == {(pricer, Pricer.pv)}
        assert graph.cell(pricer.spot.key()).outputs == {(pricer, Pricer.payoff)}

    def test_outputs_are_known_only_for_cells_already_expanded(self):
        """Partial by construction: nothing has looked at pv, so nothing yet
        knows that pv reads payoff."""
        Pricer = make_pricer()
        pricer = Pricer()

        assert graph.cell(pricer.payoff.key()).outputs == frozenset()

        pricer.pv()
        assert graph.cell(pricer.payoff.key()).outputs == {(pricer, Pricer.pv)}
