"""`to_html`: one self-contained HTML file, string in, string out.

No browser, no webserver: everything here is a fact about the returned text.
The two facts that matter are that the embedded payload is exactly
`GraphData`, ready for the vendored JS to read, and that nothing in the file
reaches outside it -- no `<script src="...">`, no CDN host named anywhere --
since the whole point is that this file works with no network at all.
"""

import json
import re

import graph
from viz.build import EdgeEntry, GraphData, GroupEntry, NodeEntry, build_graph
from viz.render import as_dict, to_html

_PAYLOAD = re.compile(
    r'<script id="graph-data" type="application/json">(.*?)</script>', re.DOTALL
)

#: Hosts a "no CDN" promise has to rule out -- not "http://" itself, which
#: also appears harmlessly inside the vendored library's own source comments.
_CDN_HOSTS = ("cdn.jsdelivr.net", "unpkg.com", "cdnjs.cloudflare.com", "googleapis.com")


def _extract_payload(html_text):
    match = _PAYLOAD.search(html_text)
    assert match is not None, "no embedded graph-data script tag found"
    return json.loads(match.group(1))


def _sample_graph_data():
    return GraphData(
        root="n0",
        nodes={
            "n0": NodeEntry(
                id="n0",
                label="Book.pv()",
                value_state="clean",
                value="5.0",
                annotations=("hedged=True",),
                group=None,
            ),
            "n1": NodeEntry(
                id="n1",
                label="Position.pv()",
                value_state="uncomputed",
                value="",
                annotations=(),
                group="g0",
            ),
        },
        groups={
            "g0": GroupEntry(id="g0", guard="live", group=None, members=("n1",)),
        },
        edges=(
            EdgeEntry(
                from_="n0",
                slot_index=4,
                kind="map edge",
                guard="live",
                to_type="group",
                to_id="g0",
            ),
        ),
    )


class TestPayloadRoundTrips:
    def test_the_embedded_payload_equals_as_dict_of_the_input(self):
        data = _sample_graph_data()

        html_text = to_html(data)

        assert _extract_payload(html_text) == as_dict(data)

    def test_round_trips_a_graph_built_from_a_real_cell(self):
        from tests.helpers import make_book

        book, _ = make_book()
        data = build_graph(graph.cell(book.total.key(True)))

        html_text = to_html(data)

        assert _extract_payload(html_text) == as_dict(data)


class TestNoCdnDependency:
    def test_no_script_tag_points_outside_the_file(self):
        html_text = to_html(_sample_graph_data())

        assert 'src="http' not in html_text
        assert "src='http" not in html_text

    def test_no_known_cdn_host_is_named(self):
        html_text = to_html(_sample_graph_data())

        for host in _CDN_HOSTS:
            assert host not in html_text

    def test_the_vendored_layout_library_is_inlined(self):
        html_text = to_html(_sample_graph_data())

        assert "dagre" in html_text.lower()
