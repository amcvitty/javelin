"""Depending on a node of another object.

A call whose receiver expression reads `self` becomes an input. The object it
is called on is resolved during expansion, exactly as an edge's arguments are,
so the dependency is a real graph edge on another object's cell.
"""

import pytest

import graph
from tests.helpers import make_linked


class TestCrossObjectDeps:
    def test_the_dependency_is_the_other_object_s_cell(self):
        Market, Option, mkt, opt = make_linked()

        assert graph.deps(opt.strike) == {(opt, Option.market), (mkt, Market.spot)}

    def test_the_receiver_is_evaluated_but_the_target_is_not(self):
        evaluated = []
        *_, opt = make_linked(evaluated)

        graph.deps(opt.strike)

        # `market` names the cell, so it has to run; `spot` is the cell itself.
        assert evaluated == ["market"]

    def test_the_value_crosses_objects(self):
        _, _, mkt, opt = make_linked()

        assert opt.strike() == mkt.spot() == 100.0

    def test_setting_a_value_dirties_across_objects(self):
        _, _, mkt, opt = make_linked()
        opt.strike()

        mkt.spot.set_value(120.0)

        assert opt.strike.is_dirty()
        assert opt.strike() == 120.0

    def test_dirtying_is_transitive_across_objects(self):
        _, _, mkt, opt = make_linked()
        opt.doubled()

        mkt.spot.set_value(120.0)

        assert opt.doubled() == 240.0


class TestFallback:
    def test_a_non_node_attribute_is_an_ordinary_call(self):
        _, _, _, opt = make_linked()

        assert opt.shout() == "ABC"

    def test_an_ordinary_call_is_not_a_dependency(self):
        Market, Option, _, opt = make_linked()

        # `ticker` is a node and so a dependency; `.upper()` on its result is
        # not, so the only cells are the two nodes.
        assert graph.deps(opt.shout) == {
            (opt, Option.market),
            (opt.market(), Market.ticker),
        }


class TestGuards:
    def test_an_unreached_cross_object_call_is_not_a_dependency(self):
        Market, Option, mkt, opt = make_linked()

        # The receiver is guarded like any other input, so when the call site
        # is not reached neither it nor the cell it names is a dependency.
        assert graph.deps(opt.maybe, False) == frozenset()
        assert graph.deps(opt.maybe, True) == {
            (opt, Option.market),
            (mkt, Market.spot),
        }

    def test_the_body_is_still_correct_when_the_call_is_skipped(self):
        _, _, _, opt = make_linked()

        assert opt.maybe(False) == 0.0
        assert opt.maybe(True) == 100.0


class TestStillInline:
    def test_a_non_node_method_on_self_stays_in_the_body(self):
        _, _, _, opt = make_linked()

        assert opt.with_helper() == 101.0
        assert graph.code(type(opt).with_helper).count("self.helper()") == 1

    def test_a_call_that_does_not_read_self_is_untouched(self):
        _, _, _, opt = make_linked()

        assert "max(" in graph.code(type(opt).clamped)

    def test_a_member_variable_is_still_rejected(self):
        from graph import node

        with pytest.raises(ValueError, match="member variable"):

            class Bad:
                @node
                def a(self):
                    # Wrong on purpose; both checkers object as well.
                    return self.thing  # ty: ignore[unresolved-attribute]  # pyright: ignore[reportAttributeAccessIssue]

    def test_a_node_may_close_over_a_variable_of_its_own_name(self):
        """The rewritten body is a nested def inside a factory, so if it kept
        the node's name it would shadow a free variable called the same."""
        from graph import node

        market = 42

        class Sheet:
            @node
            def market(self):
                return market

        assert Sheet().market() == 42
