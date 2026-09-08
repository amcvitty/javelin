"""Setting a cell's value directly.

A set value shadows the node's body, and everything downstream of it is marked
dirty so that it -- and only it -- recomputes on demand.
"""

import graph
from tests.helpers import make_chooser, make_fib, make_pricer


class TestSetValue:
    def test_a_set_value_is_returned_without_running_the_body(self):
        evaluated = []
        p = make_pricer(evaluated)()

        p.spot.set_value(110.0)

        assert p.spot() == 110.0
        assert evaluated == []

    def test_a_dependent_sees_the_new_value(self):
        p = make_pricer()()
        assert p.pv() == (100.0 - 90.0) * 2.0

        p.spot.set_value(110.0)

        assert p.pv() == (110.0 - 90.0) * 2.0

    def test_a_value_can_be_set_before_anything_is_evaluated(self):
        p = make_pricer()()
        p.spot.set_value(110.0)

        assert p.pv() == (110.0 - 90.0) * 2.0


class TestDirtying:
    def test_dirtying_is_transitive(self):
        p = make_pricer()()
        p.pv()

        p.spot.set_value(110.0)

        assert p.payoff.is_dirty()
        assert p.pv.is_dirty()

    def test_dirtying_stops_at_cells_that_do_not_depend_on_the_change(self):
        evaluated = []
        p = make_pricer(evaluated)()
        p.pv()
        assert evaluated == ["spot", "strike", "payoff", "quantity", "pv"]

        p.spot.set_value(110.0)
        evaluated.clear()
        p.pv()

        # strike and quantity are untouched, and spot is shadowed.
        assert evaluated == ["payoff", "pv"]

    def test_a_cell_is_clean_again_once_it_has_recomputed(self):
        p = make_pricer()()
        p.pv()
        p.spot.set_value(110.0)
        assert graph.dirty()

        p.pv()

        assert not p.pv.is_dirty()
        assert graph.dirty() == ()

    def test_setting_a_value_does_not_dirty_the_cell_itself(self):
        p = make_pricer()()
        p.pv()

        p.spot.set_value(110.0)

        assert not p.spot.is_dirty()


class TestDepsWhileSet:
    def test_a_set_cell_has_no_dependencies(self):
        p = make_pricer()()
        assert graph.deps(p.payoff)

        p.payoff.set_value(7.0)

        assert graph.deps(p.payoff) == frozenset()

    def test_its_dependents_still_depend_on_it(self):
        Pricer = make_pricer()
        p = Pricer()
        p.spot.set_value(110.0)

        assert (p, Pricer.spot) in graph.deps(p.payoff)

    def test_dependencies_come_back_when_the_value_is_cleared(self):
        Pricer = make_pricer()
        p = Pricer()
        p.payoff.set_value(7.0)
        p.payoff.clear_value()

        assert graph.deps(p.payoff) == {(p, Pricer.spot), (p, Pricer.strike)}


class TestParameterisedCells:
    def test_setting_the_base_cases_changes_the_recursion(self):
        evaluated = []
        f = make_fib(evaluated)()

        f.fib.set_value(2.0, args=(0,))
        f.fib.set_value(3.0, args=(1,))

        # fib(2) = 5, fib(3) = 8, fib(4) = 13, fib(5) = 21
        assert f.fib(5) == 21.0
        # Only the base cases are shadowed; everything above still runs.
        assert evaluated == [2, 3, 4, 5]

    def test_only_the_named_cell_is_set(self):
        f = make_fib()()
        f.fib.set_value(2.0, args=(0,))

        assert f.fib(0) == 2.0
        assert f.fib(1) == 1
        assert not f.fib.is_dirty(args=(0,))

    def test_arguments_are_canonicalised_like_a_call(self):
        f = make_fib()()
        f.fib.set_value(2.0, args=(0,))

        assert f.fib(n=0) == 2.0


class TestChangingGraphShape:
    """A set value can reach an edge's arguments, and so change which cell is
    depended on -- not just what that cell is worth."""

    def test_the_dependency_moves_with_the_value(self):
        Chooser = make_chooser()
        c = Chooser()
        assert c.pick() == 10
        assert (c, Chooser.item, 1) in graph.deps(c.pick)

        c.which.set_value(3)

        assert c.pick() == 30
        assert graph.deps(c.pick) == {(c, Chooser.which), (c, Chooser.item, 3)}


class TestClearValue:
    def test_the_computed_value_comes_back(self):
        p = make_pricer()()
        p.pv()
        p.spot.set_value(110.0)
        assert p.pv() == 40.0

        p.spot.clear_value()

        assert p.pv() == 20.0

    def test_clearing_does_not_recompute_the_cell_that_was_set(self):
        evaluated = []
        p = make_pricer(evaluated)()
        p.pv()
        p.spot.set_value(110.0)
        p.pv()
        evaluated.clear()

        p.spot.clear_value()
        p.pv()

        # spot's memoised value was never overwritten, so it need not run again.
        assert evaluated == ["payoff", "pv"]

    def test_clearing_a_value_that_was_never_set_is_harmless(self):
        p = make_pricer()()
        p.spot.clear_value()

        assert p.spot() == 100.0
