"""`build_graph`: the transitive dependency graph rooted at one cell.

Pure, no I/O -- built entirely off `Cell.slots` / `Slot.cells` /
`Cell.expand_slot`, so every test here can assert on `GraphData`'s shape
without a browser, a webserver or a Jupyter kernel in sight.

Two things this module is careful never to do, matching the engine's own
"expansion is not free, evaluation is deliberate" split: run a node's own
body (`Cell.evaluate`), or trust `cell.slots` for a cell whose value is
overridden -- an override shadows the body, so the cells its slots would
otherwise name are not really depended on any more.
"""

import graph
from graph import ValueState, node
from tests.helpers import make_book, make_linked, make_pricer
from viz.build import build_graph


def by_label(graph_data, label):
    """The one node entry with this label, or raises -- labels are unique
    across these small fixtures, so this is a convenient lookup for tests
    that do not want to depend on assigned node-id order."""
    matches = [n for n in graph_data.nodes.values() if n.label == label]
    assert len(matches) == 1, f"{label}: {len(matches)} matches"
    return matches[0]


def edges_from(graph_data, node_id):
    return tuple(e for e in graph_data.edges if e.from_ == node_id)


def target_id(edge):
    """An edge's `to_id`, asserted non-`None` -- only `guarded_off` lacks one."""
    assert edge.to_id is not None
    return edge.to_id


class TestLinearChain:
    """A small DAG of call edges: pv -> payoff, quantity; payoff -> spot, strike."""

    def test_every_reachable_cell_gets_a_node(self):
        Pricer = make_pricer()
        pricer = Pricer()

        data = build_graph(graph.cell(pricer.pv.key()))

        labels = {n.label for n in data.nodes.values()}
        assert labels == {
            "Pricer.pv()",
            "Pricer.payoff()",
            "Pricer.quantity()",
            "Pricer.spot()",
            "Pricer.strike()",
        }

    def test_root_is_recorded(self):
        Pricer = make_pricer()
        pricer = Pricer()

        data = build_graph(graph.cell(pricer.pv.key()))

        assert data.nodes[data.root].label == "Pricer.pv()"

    def test_edges_connect_the_right_cells(self):
        Pricer = make_pricer()
        pricer = Pricer()

        data = build_graph(graph.cell(pricer.pv.key()))

        pv = by_label(data, "Pricer.pv()")
        payoff = by_label(data, "Pricer.payoff()")
        targets = {
            (e.kind, data.nodes[target_id(e)].label) for e in edges_from(data, pv.id)
        }
        assert targets == {
            ("call edge", "Pricer.payoff()"),
            ("call edge", "Pricer.quantity()"),
        }
        payoff_targets = {
            data.nodes[target_id(e)].label for e in edges_from(data, payoff.id)
        }
        assert payoff_targets == {"Pricer.spot()", "Pricer.strike()"}

    def test_runs_no_body(self):
        evaluated = []
        Pricer = make_pricer(evaluated)
        pricer = Pricer()

        build_graph(graph.cell(pricer.pv.key()))

        assert evaluated == []

    def test_value_state_is_carried(self):
        Pricer = make_pricer()
        pricer = Pricer()
        pricer.spot()  # evaluate just this one cell, outside build_graph

        data = build_graph(graph.cell(pricer.pv.key()))

        assert by_label(data, "Pricer.spot()").value_state == "clean"
        assert by_label(data, "Pricer.pv()").value_state == "uncomputed"


class TestTerminalAndLocalAnnotations:
    """A `Value` or `Local` input annotates the cell that owns it -- it is
    never its own node or edge."""

    def test_a_terminal_is_an_annotation_not_a_node(self):
        book, _ = make_book()

        data = build_graph(graph.cell(book.total.key(True)))

        total = by_label(data, "Book.total(True)")
        assert "live=True" in total.annotations
        assert not any(n.label == "True" for n in data.nodes.values())

    def test_a_hoisted_local_is_an_annotation_not_a_node(self):
        book, _ = make_book()

        data = build_graph(graph.cell(book.total.key(True)))

        total = by_label(data, "Book.total(True)")
        assert any(a.startswith("scale = ") for a in total.annotations)

    def test_annotations_cost_no_edges(self):
        book, _ = make_book()

        data = build_graph(graph.cell(book.total.key(True)))

        total = by_label(data, "Book.total(True)")
        kinds = {e.kind for e in edges_from(data, total.id)}
        assert kinds <= {"call edge", "map edge"}


class TestMapEdgeCollapsing:
    """A `MapEdge`'s fan-out is always collapsed into one group, whatever its
    size -- there is no threshold, per the issue's own out-of-scope note."""

    def test_a_map_edge_becomes_one_group(self):
        book, _ = make_book()

        data = build_graph(graph.cell(book.total.key(True)))

        total = by_label(data, "Book.total(True)")
        group_edges = [e for e in edges_from(data, total.id) if e.to_type == "group"]
        assert len(group_edges) == 1
        group = data.groups[target_id(group_edges[0])]
        assert len(group.members) == 2

    def test_members_are_pre_expanded_in_full(self):
        """The group's members already have their own transitive closure in
        `nodes` -- expanding the group client-side needs no further work."""
        book, _ = make_book()

        data = build_graph(graph.cell(book.total.key(True)))

        pv_labels = [n.label for n in data.nodes.values() if "pv()" in n.label]
        assert len(pv_labels) == 2  # one.pv() and two.pv(), both already built

    def test_members_are_hidden_until_their_group_is_revealed(self):
        book, _ = make_book()

        data = build_graph(graph.cell(book.total.key(True)))

        total = by_label(data, "Book.total(True)")
        group_edges = [e for e in edges_from(data, total.id) if e.to_type == "group"]
        group = data.groups[target_id(group_edges[0])]
        for member_id in group.members:
            assert data.nodes[member_id].group == group.id

    def test_the_group_itself_is_visible_at_the_owning_cells_level(self):
        book, _ = make_book()

        data = build_graph(graph.cell(book.total.key(True)))

        total = by_label(data, "Book.total(True)")
        group_edges = [e for e in edges_from(data, total.id) if e.to_type == "group"]
        group = data.groups[target_id(group_edges[0])]
        assert group.group == total.group

    def test_the_map_edges_guard_is_carried(self):
        book, _ = make_book()

        data = build_graph(graph.cell(book.total.key(True)))

        total = by_label(data, "Book.total(True)")
        group_edges = [e for e in edges_from(data, total.id) if e.to_type == "group"]
        assert group_edges[0].guard == "live"


class TestGuardedOff:
    """A guarded call site currently naming no cells shows up as a stub
    carrying its guard text -- not as an unresolved row and not as nothing."""

    def test_a_blocked_call_site_is_marked_guarded_off(self):
        book, _ = make_book()

        data = build_graph(graph.cell(book.total.key(False)))

        total = by_label(data, "Book.total(False)")
        guarded = [e for e in edges_from(data, total.id) if e.to_type == "guarded_off"]
        assert len(guarded) == 2  # positions() and the map edge, both guarded by live
        assert all(e.guard == "live" for e in guarded)

    def test_a_blocked_call_site_names_no_node(self):
        book, _ = make_book()

        data = build_graph(graph.cell(book.total.key(False)))

        assert not any("positions" in n.label for n in data.nodes.values())
        assert not any("pv()" in n.label for n in data.nodes.values())


class TestOverriddenCellsAreLeaves:
    """`Graph.expand` says an override shadows the body and the cell depends
    on nothing -- build_graph must agree, rather than trusting `cell.slots`,
    which describes the body's structure whether or not it actually runs."""

    def test_an_overridden_cell_has_no_outgoing_edges(self):
        Pricer = make_pricer()
        pricer = Pricer()
        pricer.payoff.set_value(42.0)

        data = build_graph(graph.cell(pricer.pv.key()))

        payoff = by_label(data, "Pricer.payoff()")
        assert edges_from(data, payoff.id) == ()

    def test_an_overridden_cells_state_is_shown(self):
        Pricer = make_pricer()
        pricer = Pricer()
        pricer.payoff.set_value(42.0)

        data = build_graph(graph.cell(pricer.pv.key()))

        payoff = by_label(data, "Pricer.payoff()")
        assert payoff.value_state == str(ValueState.OVERRIDDEN)


class TestCycles:
    """A cycle is a bug in the engine's invariants, not something that should
    ever hang the tool -- it must come back as one flagged edge."""

    def test_a_forced_cycle_is_flagged_rather_than_followed(self):
        class Loop:
            @node
            def a(self):
                return self.b()

            @node
            def b(self):
                return self.a()

        loop = Loop()

        data = build_graph(graph.cell(loop.a.key()))

        assert len(data.nodes) == 2  # a() and b(), not an infinite unrolling
        a = by_label(data, "Loop.a()")
        b = by_label(data, "Loop.b()")
        a_to_b = edges_from(data, a.id)
        assert len(a_to_b) == 1
        assert a_to_b[0].to_id == b.id
        assert a_to_b[0].cycle is False
        b_to_a = edges_from(data, b.id)
        assert len(b_to_a) == 1
        assert b_to_a[0].to_id == a.id
        assert b_to_a[0].cycle is True

    def test_a_cycle_does_not_hang_build_graph(self):
        """The real assertion: this test returns at all."""

        class Loop:
            @node
            def a(self):
                return self.b()

            @node
            def b(self):
                return self.a()

        loop = Loop()

        build_graph(graph.cell(loop.a.key()))  # would hang if cycles were followed


class TestDiamonds:
    """A cell reachable by more than one path is one node, not reprocessed."""

    def test_a_shared_dependency_is_one_node_with_edges_from_both_readers(self):
        class Shared:
            @node
            def leaf(self):
                return 1.0

            @node
            def left(self):
                return self.leaf()

            @node
            def right(self):
                return self.leaf()

            @node
            def top(self):
                return self.left() + self.right()

        shared = Shared()

        data = build_graph(graph.cell(shared.top.key()))

        leaf_nodes = [n for n in data.nodes.values() if n.label == "Shared.leaf()"]
        assert len(leaf_nodes) == 1
        left = by_label(data, "Shared.left()")
        right = by_label(data, "Shared.right()")
        assert edges_from(data, left.id)[0].to_id == leaf_nodes[0].id
        assert edges_from(data, right.id)[0].to_id == leaf_nodes[0].id


class TestObjectClustering:
    """Cells share `object_id` exactly when they ran on the same object, so
    the renderer can draw one surrounding box per object rather than
    repeating the object's name on every cell inside it."""

    def test_cells_of_the_same_object_share_one_object_id(self):
        Pricer = make_pricer()
        pricer = Pricer()

        data = build_graph(graph.cell(pricer.pv.key()))

        object_ids = {n.object_id for n in data.nodes.values()}
        assert len(object_ids) == 1

    def test_the_object_label_names_the_object(self):
        Pricer = make_pricer()
        pricer = Pricer()

        data = build_graph(graph.cell(pricer.pv.key()))

        assert by_label(data, "Pricer.pv()").object_label == "Pricer"

    def test_method_label_excludes_the_object_name(self):
        Pricer = make_pricer()
        pricer = Pricer()

        data = build_graph(graph.cell(pricer.pv.key()))

        pv = by_label(data, "Pricer.pv()")
        assert pv.method_label == "pv()"
        assert "Pricer" not in pv.method_label

    def test_cells_of_different_objects_get_different_object_ids(self):
        _, _, _market, option = make_linked()

        data = build_graph(graph.cell(option.strike.key()))

        by_object_label: dict[str, set[str]] = {}
        for n in data.nodes.values():
            by_object_label.setdefault(n.object_label, set()).add(n.object_id)
        assert len(by_object_label) >= 2  # at least Market and Option
        for object_ids in by_object_label.values():
            assert len(object_ids) == 1  # one object, one id -- never split
