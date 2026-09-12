"""Objects with well-known names, referring to each other."""

import pytest

import graph
import ns
from tests.helpers import make_market_classes


class TestCreation:
    def test_objects_must_come_from_a_namespace(self):
        _, Market = make_market_classes()

        with pytest.raises(TypeError, match="must be created through a namespace"):
            Market()

    def test_a_new_object_gets_a_guid_name(self):
        _, Market = make_market_classes()

        mkt = ns.new(Market)

        assert mkt.name.startswith("/limbo/Market/")
        assert ns.new(Market).name != mkt.name

    def test_str_names_the_class_and_the_object(self):
        _, Market = make_market_classes()

        mkt = ns.lookup_or_new("/Equities/ABC", Market)

        assert str(mkt) == "<Market:/Equities/ABC>"

    def test_the_namespace_is_an_identity_map(self):
        _, Market = make_market_classes()

        first = ns.lookup_or_new("/Equities/ABC", Market)
        second = ns.lookup_or_new("/Equities/ABC", Market)

        assert first is second
        assert ns.DEFAULT["/Equities/ABC"] is first

    def test_an_unknown_name_raises(self):
        with pytest.raises(KeyError):
            ns.DEFAULT["/nothing/here"]


class TestValues:
    def test_values_override_the_class_default(self):
        _, Market = make_market_classes()

        mkt = ns.new(Market, spot=20.0)

        assert mkt.spot() == 20.0

    def test_values_are_applied_to_an_existing_object_too(self):
        _, Market = make_market_classes()
        mkt = ns.lookup_or_new("/Equities/ABC", Market, spot=20.0)

        again = ns.lookup_or_new("/Equities/ABC", Market, spot=30.0)

        assert again is mkt
        assert mkt.spot() == 30.0

    def test_a_value_for_something_that_is_not_a_node_is_rejected(self):
        _, Market = make_market_classes()

        with pytest.raises(TypeError, match="is not a node"):
            ns.new(Market, nonsense=1)


class TestLookupFromANode:
    def test_a_node_may_reach_another_object_by_name(self):
        Params, Market = make_market_classes()
        params = ns.lookup_or_new("/Params", Params)
        mkt = ns.new(Market)

        assert mkt.scaled() == 100.0 * 2
        assert (params, Params.factor) in graph.deps(mkt.scaled)

    def test_setting_a_value_on_the_other_object_dirties_this_one(self):
        Params, Market = make_market_classes()
        params = ns.lookup_or_new("/Params", Params)
        mkt = ns.new(Market)
        mkt.scaled()

        params.factor.set_value(3.0)

        assert mkt.scaled.is_dirty()
        assert mkt.scaled() == 300.0
