"""Temporary overrides.

A diddle scope remembers what it displaces, so leaving it restores the graph
rather than recomputing it.
"""

import pytest

import graph
from tests.helpers import make_chooser, make_fib, make_pricer


class TestDiddle:
    def test_overrides_apply_inside_and_are_gone_after(self):
        p = make_pricer()()

        with graph.diddle((p.spot, 110.0)):
            assert p.spot() == 110.0
            assert p.pv() == 40.0

        assert p.spot() == 100.0
        assert p.pv() == 20.0

    def test_leaving_a_diddle_restores_rather_than_recomputes(self):
        evaluated = []
        p = make_pricer(evaluated)()
        p.pv()
        evaluated.clear()

        with graph.diddle((p.spot, 110.0)):
            assert p.pv() == 40.0
        assert evaluated == ["payoff", "pv"]

        evaluated.clear()
        assert p.pv() == 20.0
        assert evaluated == []

    def test_cells_first_computed_inside_a_diddle_do_not_survive_it(self):
        evaluated = []
        p = make_pricer(evaluated)()

        with graph.diddle((p.spot, 110.0)):
            p.pv()
        evaluated.clear()

        assert p.pv() == 20.0
        assert evaluated == ["spot", "strike", "payoff", "quantity", "pv"]

    def test_a_diddle_restores_dirty_flags_too(self):
        p = make_pricer()()
        p.pv()
        p.spot.set_value(110.0)

        with graph.diddle((p.strike, 95.0)):
            p.pv()  # leaves nothing dirty inside the scope

        assert p.payoff.is_dirty()
        assert p.pv.is_dirty()

    def test_an_exception_still_unwinds_the_scope(self):
        p = make_pricer()()

        with pytest.raises(RuntimeError), graph.diddle((p.spot, 110.0)):
            raise RuntimeError("boom")

        assert p.pv() == 20.0
        assert graph.dirty() == ()

    def test_dependency_edges_are_restored_not_just_values(self):
        Chooser = make_chooser()
        c = Chooser()
        c.pick()

        with graph.diddle((c.which, 5)):
            assert c.pick() == 50
            assert (c, Chooser.item, 5) in graph.deps(c.pick)

        assert c.pick() == 10
        assert graph.deps(c.pick) == {(c, Chooser.which), (c, Chooser.item, 1)}


class TestNesting:
    def test_an_inner_diddle_shadows_the_outer_one(self):
        p = make_pricer()()

        with graph.diddle((p.spot, 110.0)):
            assert p.pv() == 40.0
            with graph.diddle((p.spot, 120.0)):
                assert p.pv() == 60.0
            assert p.pv() == 40.0

        assert p.pv() == 20.0

    def test_leaving_an_inner_diddle_costs_no_recomputes(self):
        evaluated = []
        p = make_pricer(evaluated)()

        with graph.diddle((p.spot, 110.0)):
            p.pv()
            with graph.diddle((p.spot, 120.0)):
                p.pv()
            evaluated.clear()
            assert p.pv() == 40.0

        assert evaluated == []


class TestEntries:
    def test_entries_are_shorthand_for_set_value(self):
        p = make_pricer()()

        with graph.diddle((p.spot, 110.0), (p.strike, 95.0)):
            shorthand = p.pv()

        with graph.diddle():
            p.spot.set_value(110.0)
            p.strike.set_value(95.0)
            longhand = p.pv()

        assert shorthand == longhand == 30.0

    def test_an_entry_can_name_a_parameterised_cell(self):
        f = make_fib()()

        with graph.diddle((f.fib, 2.0, (0,)), (f.fib, 3.0, (1,))):
            assert f.fib(5) == 21.0

        assert f.fib(5) == 5


class TestSeparateGraphs:
    def test_a_diddle_belongs_to_one_graph(self):
        Pricer = make_pricer()
        p = Pricer()
        pv = graph.make_key(p, Pricer.pv)
        other = graph.Graph()

        with other.diddle((p.spot, 110.0)):
            assert other.evaluate(pv) == 40.0
            assert p.pv() == 20.0  # the default graph never saw the override

        assert other.evaluate(pv) == 20.0
