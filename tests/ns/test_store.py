"""Persisting objects, and getting them back.

A stored object comes back as a set of values rather than a set of bodies to
run, so reloading costs nothing and gives the same answers.
"""

import datetime

import pytest

import graph
import ns
from ns.mcobject import CREATION_TOKEN
from ns.store import SqliteStore
from tests.helpers import Unstorable, make_market_classes, ran


@pytest.fixture
def namespace(tmp_path):
    """A namespace backed by a real sqlite file."""
    return ns.Namespace(SqliteStore(str(tmp_path / "objects.db")))


class TestRoundTrip:
    def test_a_stored_object_comes_back(self, namespace):
        _, Market = make_market_classes()
        mkt = namespace.lookup_or_new("/Equities/ABC", Market, spot=20.0)
        mkt.store()

        namespace.clear()
        graph.clear()
        reloaded = namespace["/Equities/ABC"]

        assert reloaded is not mkt
        assert reloaded.name == "/Equities/ABC"
        assert reloaded.spot() == 20.0

    def test_reloading_runs_no_bodies(self, namespace):
        _, Market = make_market_classes()
        namespace.lookup_or_new("/Equities/ABC", Market, spot=20.0).store()
        namespace.clear()
        graph.clear()
        ran.clear()

        reloaded = namespace["/Equities/ABC"]

        assert reloaded.spot() == 20.0
        assert reloaded.asof() == datetime.date(2026, 1, 1)
        assert ran == []

    def test_stored_cells_have_no_dependencies(self, namespace):
        _, Market = make_market_classes()
        namespace.lookup_or_new("/Equities/ABC", Market).store()
        namespace.clear()
        graph.clear()

        assert graph.deps(namespace["/Equities/ABC"].spot) == frozenset()

    def test_only_stored_nodes_are_written(self, namespace):
        _, Market = make_market_classes()
        mkt = namespace.new(Market)

        assert sorted(mkt.stored_values()) == ["asof", "spot"]

    def test_storing_evaluates_every_stored_node(self, namespace):
        _, Market = make_market_classes()
        mkt = namespace.new(Market)
        ran.clear()

        mkt.store()

        assert sorted(ran) == ["asof", "spot"]

    def test_a_derived_node_recomputes_from_reloaded_values(self, namespace):
        Params, Market = make_market_classes()
        namespace.lookup_or_new("/Params", Params)
        namespace.lookup_or_new("/Equities/ABC", Market, spot=20.0).store()

        namespace.clear()
        graph.clear()
        namespace.lookup_or_new("/Params", Params)

        assert namespace["/Equities/ABC"].scaled() == 40.0


class TestReload:
    def test_reload_picks_up_a_change_made_elsewhere(self, namespace):
        _, Market = make_market_classes()
        mkt = namespace.lookup_or_new("/Equities/ABC", Market, spot=20.0)
        mkt.store()
        namespace.lookup_or_new("/Equities/ABC", Market, spot=30.0).store()
        mkt.spot.set_value(999.0)

        reloaded = mkt.reload()

        assert reloaded is mkt
        assert mkt.spot() == 30.0

    def test_reload_runs_no_bodies(self, namespace):
        _, Market = make_market_classes()
        mkt = namespace.lookup_or_new("/Equities/ABC", Market, spot=20.0)
        mkt.store()
        ran.clear()

        mkt.reload()

        assert ran == []

    def test_reloading_something_never_stored_raises(self, namespace):
        _, Market = make_market_classes()
        mkt = namespace.new(Market)

        with pytest.raises(KeyError, match=mkt.name):
            mkt.reload()

    def test_reloading_onto_the_wrong_class_raises(self, namespace):
        Params, Market = make_market_classes()
        namespace.lookup_or_new("/Equities/ABC", Market, spot=20.0).store()
        mismatched = Params(CREATION_TOKEN, name="/Equities/ABC", ns=namespace)

        with pytest.raises(TypeError, match="stored as Market"):
            mismatched.reload()


class TestEncoding:
    def test_dates_survive(self, namespace):
        _, Market = make_market_classes()
        namespace.lookup_or_new("/Equities/ABC", Market).store()
        namespace.clear()
        graph.clear()

        assert namespace["/Equities/ABC"].asof() == datetime.date(2026, 1, 1)

    def test_an_unencodable_value_names_the_node(self, namespace):
        obj = namespace.new(Unstorable)

        with pytest.raises(TypeError, match=r"cannot store .*\.thing"):
            obj.store()


class TestStoreDirectly:
    def test_an_unknown_name_reads_as_none(self):
        assert SqliteStore().read("/nothing") is None

    def test_names_are_listed(self):
        _, Market = make_market_classes()
        store = SqliteStore()
        store.write("/b", Market, {"spot": 1.0})
        store.write("/a", Market, {"spot": 2.0})

        assert store.names() == ("/a", "/b")

    def test_writing_the_same_name_replaces_it(self):
        _, Market = make_market_classes()
        store = SqliteStore()
        store.write("/a", Market, {"spot": 1.0})
        store.write("/a", Market, {"spot": 2.0})

        assert store.read("/a") == (Market, {"spot": 2.0})

    def test_clear_forgets_everything(self):
        _, Market = make_market_classes()
        store = SqliteStore()
        store.write("/a", Market, {"spot": 1.0})
        store.write("/b", Market, {"spot": 2.0})

        store.clear()

        assert store.names() == ()
        assert store.read("/a") is None


class TestClearStore:
    def test_clear_store_drops_persisted_objects(self, namespace):
        _, Market = make_market_classes()
        namespace.lookup_or_new("/Equities/ABC", Market, spot=20.0).store()
        namespace.clear()

        namespace.clear_store()

        assert "/Equities/ABC" not in namespace
        with pytest.raises(KeyError):
            _ = namespace["/Equities/ABC"]

    def test_plain_clear_still_leaves_the_store_alone(self, namespace):
        _, Market = make_market_classes()
        namespace.lookup_or_new("/Equities/ABC", Market, spot=20.0).store()

        namespace.clear()

        assert namespace["/Equities/ABC"].spot() == 20.0
