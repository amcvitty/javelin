"""Rendering `GraphData` into one self-contained HTML file.

Pure, no I/O beyond reading this package's own bundled static assets: given a
`GraphData`, `to_html` returns a string with everything a browser needs to
draw and interact with the picture already inside it -- the vendored layout
library, this project's own drawing code, and the graph itself as one inlined
JSON payload. Nothing here reaches outside the returned string: no
`<script src="...">`, no stylesheet link, no CDN -- `show` can hand the same
string to a webserver or straight to `IPython.display.HTML` and either way
the picture is complete.

Expanding a collapsed `MapEdge` group is client-side JS over this same
payload (see `static/render.js`) -- there is no callback into Python, so
nothing here needs to change to support it.
"""

import dataclasses
import html
import json
from pathlib import Path

from .build import GraphData

_STATIC = Path(__file__).parent / "static"


def _read_static(*parts: str) -> str:
    return _STATIC.joinpath(*parts).read_text()


def _to_jsonable(value):
    """A dataclass tree as plain `dict`/`list`/primitive, JSON round-trips it.

    Not `dataclasses.asdict`: that keeps tuples as tuples, and JSON has no
    tuple type, so a payload embedded and read back would not equal what
    went in. Converting tuples to lists here is what makes the round trip
    the tests check for actually hold.
    """
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        return {
            f.name: _to_jsonable(getattr(value, f.name))
            for f in dataclasses.fields(value)
        }
    if isinstance(value, dict):
        return {key: _to_jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_to_jsonable(item) for item in value]
    return value


def as_dict(graph_data: GraphData) -> dict[str, object]:
    """`graph_data`, as the plain JSON-shaped dict `to_html` embeds."""
    return {
        f.name: _to_jsonable(getattr(graph_data, f.name))
        for f in dataclasses.fields(graph_data)
    }


def to_html(graph_data: GraphData) -> str:
    """`graph_data`, rendered into one self-contained, offline-capable page."""
    # "</" is escaped so the payload cannot close the script tag it sits
    # inside, whatever a label or a repr'd value happens to contain.
    payload = json.dumps(as_dict(graph_data)).replace("</", "<\\/")
    root_label = graph_data.nodes[graph_data.root].label
    return f"""<!doctype html>
<html>
<head>
<meta charset="utf-8">
<title>{html.escape(root_label)} -- dependency graph</title>
<style>
{_read_static("style.css")}
</style>
</head>
<body>
<div id="viz-toolbar">{html.escape(root_label)}</div>
<svg id="viz-graph"></svg>
<script id="graph-data" type="application/json">{payload}</script>
<script>
{_read_static("vendor", "dagre.min.js")}
</script>
<script>
{_read_static("render.js")}
</script>
</body>
</html>
"""
