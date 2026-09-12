"""Walking the graph: a focused cell, a back-stack, and a depth.

None of this needs a terminal, so none of these tests use one -- pressing a
key is only ever a call to one of `Navigation`'s methods, and that is what is
tested here. What the terminal does with the result belongs to `test_app.py`.
"""

import graph
from tests.helpers import make_book, make_chooser
from tui.graph_browser.navigation import Navigation


class TestDrillingIntoAnInput:
    """Drilling into a resolved edge or an unresolved one, alike."""

    def test_a_resolved_edge_focuses_it_and_increases_depth(self):
        book, _ = make_book()
        root = graph.cell(book.total.key(True))
        nav = Navigation(root)

        result = nav.drill_slot(1)  # rate(): a call edge, statically resolvable

        assert result.ok
        assert nav.focus == book.rate.key()
        assert nav.depth == 1

    def test_an_unresolved_edge_resolves_and_navigates_in_one_keystroke(self):
        chooser = make_chooser()()
        root = graph.cell(chooser.pick.key())
        nav = Navigation(root)
        index = next(slot.index for slot in root.slots if slot.target == "item")
        assert root.slots[index].cells is graph.UNRESOLVED

        result = nav.drill_slot(index)

        assert result.ok
        assert nav.focus == chooser.item.key(1)
        assert nav.depth == 1

    def test_navigating_never_runs_the_destination_cells_own_body(self):
        chooser = make_chooser()()
        nav = Navigation(graph.cell(chooser.pick.key()))
        index = next(slot.index for slot in nav.focus.slots if slot.target == "item")

        nav.drill_slot(index)

        assert nav.focus.value.state is graph.ValueState.UNCOMPUTED


class TestDrillingIntoAnOutput:
    """An output is a cell already -- nothing to resolve first."""

    def test_focuses_it_and_increases_depth_the_same_way(self):
        book, _ = make_book()
        root = graph.cell(book.total.key(True))
        _ = root.slots  # let the statically resolvable slots record themselves
        rate_cell = graph.cell(book.rate.key())
        (output,) = rate_cell.outputs
        nav = Navigation(rate_cell)

        result = nav.drill_output(output)

        assert result.ok
        assert nav.focus == book.total.key(True)
        assert nav.depth == 1


class TestGoingBack:
    def test_restores_the_previous_cell_and_depth(self):
        book, _ = make_book()
        root = graph.cell(book.total.key(True))
        nav = Navigation(root)
        nav.drill_slot(1)

        nav.back()

        assert nav.focus == root
        assert nav.depth == 0

    def test_does_nothing_at_the_root(self):
        book, _ = make_book()
        root = graph.cell(book.total.key(True))
        nav = Navigation(root)

        nav.back()

        assert nav.focus == root
        assert nav.depth == 0


class TestRowsWithNoCellBehindThem:
    """Terminals, hoisted locals and blocked call sites never navigate."""

    def test_a_terminal_does_not_navigate_and_says_why(self):
        book, _ = make_book()
        nav = Navigation(graph.cell(book.total.key(True)))

        result = nav.drill_slot(0)  # live: a terminal

        assert not result.ok
        assert nav.depth == 0
        assert "terminal" in result.reason

    def test_a_hoisted_local_does_not_navigate_and_says_why(self):
        book, _ = make_book()
        nav = Navigation(graph.cell(book.total.key(True)))

        result = nav.drill_slot(2)  # scale: a hoisted local

        assert not result.ok
        assert nav.depth == 0
        assert "local" in result.reason

    def test_a_blocked_call_site_does_not_navigate_and_says_why(self):
        book, _ = make_book()
        nav = Navigation(graph.cell(book.total.key(False)))  # live=False blocks it

        result = nav.drill_slot(3)  # positions(), guarded by live

        assert not result.ok
        assert nav.depth == 0
        assert result.reason == "not reached"

    def test_an_empty_map_edge_does_not_navigate_and_says_why(self):
        book, _ = make_book(holdings=lambda one, two: ())
        nav = Navigation(graph.cell(book.total.key(True)))

        result = nav.drill_slot(4)

        assert not result.ok
        assert result.reason == "no elements"

    def test_an_unresolved_map_edge_asks_which_element_instead_of_guessing(self):
        book, _ = make_book()
        nav = Navigation(graph.cell(book.total.key(True)))

        result = nav.drill_slot(4)

        assert not result.ok
        assert nav.depth == 0
        assert "element" in result.reason


class TestMapEdgeElements:
    def test_drilling_a_specific_element_navigates_to_it(self):
        book, (_, two) = make_book()
        nav = Navigation(graph.cell(book.total.key(True)))

        result = nav.drill_slot(4, sub=1)

        assert result.ok
        assert nav.focus == two.pv.key()
        assert nav.depth == 1


class TestRevisitingACell:
    def test_the_stack_is_a_history_not_a_set(self):
        book, (one, _) = make_book()
        nav = Navigation(graph.cell(book.total.key(True)))
        nav.drill_slot(4, sub=0)  # -> one.pv()
        nav.back()

        result = nav.drill_slot(4, sub=0)  # revisit one.pv() again

        assert result.ok
        assert nav.focus == one.pv.key()
        assert nav.depth == 1


class TestBreadcrumbAndDepth:
    def test_reflect_the_path_actually_taken(self):
        book, _ = make_book()
        root = graph.cell(book.total.key(True))
        nav = Navigation(root)

        nav.drill_slot(1)  # -> rate()

        assert nav.depth == 1
        assert nav.breadcrumb == (root, nav.focus)

        nav.back()

        assert nav.depth == 0
        assert nav.breadcrumb == (root,)


class TestResolveWithoutNavigating:
    def test_fills_in_the_slot_and_leaves_focus_where_it_is(self):
        book, _ = make_book()
        root = graph.cell(book.total.key(True))
        nav = Navigation(root)
        assert root.slots[4].cells is graph.UNRESOLVED

        nav.resolve_slot(4)

        assert nav.focus == root
        assert nav.depth == 0
        assert graph.cell(book.total.key(True)).slots[4].cells != graph.UNRESOLVED


class TestEvaluating:
    """Evaluation is deliberate: it never resolves as a side effect of trying."""

    def test_evaluating_a_rows_cell_fills_in_its_value(self):
        book, _ = make_book()
        nav = Navigation(graph.cell(book.total.key(True)))

        result = nav.evaluate_slot(1)  # rate()

        assert result.ok
        assert graph.cell(book.rate.key()).value.state is graph.ValueState.CLEAN
        assert nav.focus == graph.cell(book.total.key(True))
        assert nav.depth == 0

    def test_evaluating_the_focused_cell_fills_in_its_value_and_type(self):
        book, _ = make_book()
        nav = Navigation(graph.cell(book.total.key(True)))

        nav.evaluate_focus()

        assert nav.focus.value.state is graph.ValueState.CLEAN
        assert isinstance(nav.focus.value.value, float)

    def test_evaluating_an_unresolved_row_does_not_resolve_it_first(self):
        book, _ = make_book()
        nav = Navigation(graph.cell(book.total.key(True)))
        assert nav.focus.slots[4].cells is graph.UNRESOLVED

        result = nav.evaluate_slot(4)

        assert not result.ok
        assert nav.focus.slots[4].cells is graph.UNRESOLVED

    def test_evaluating_a_map_edge_needs_an_element_chosen(self):
        book, _ = make_book()
        nav = Navigation(graph.cell(book.total.key(True)))
        nav.resolve_slot(4)

        result = nav.evaluate_slot(4)

        assert not result.ok
        assert "element" in result.reason

    def test_evaluating_a_specific_element_fills_in_its_value(self):
        book, (one, _) = make_book()
        nav = Navigation(graph.cell(book.total.key(True)))
        nav.resolve_slot(4)

        result = nav.evaluate_slot(4, sub=0)

        assert result.ok
        assert graph.cell(one.pv.key()).value.state is graph.ValueState.CLEAN

    def test_evaluating_an_output_fills_in_its_value(self):
        book, _ = make_book()
        root = graph.cell(book.total.key(True))
        _ = root.slots
        rate_cell = graph.cell(book.rate.key())
        (output,) = rate_cell.outputs
        nav = Navigation(rate_cell)

        nav.evaluate_output(output)

        assert output.value.state is graph.ValueState.CLEAN
