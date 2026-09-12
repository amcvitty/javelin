"""A single picture of a cell's transitive dependency graph.

    viz.show(graph.cell(book.pv.key(True)))

Read-only and presentation-only, unlike `tui/graph_browser`: no drilling in,
no evaluating, no editing. `build_graph` walks a cell's `Edge` inputs
backwards -- never `outputs`, never a node's own body -- into a plain
`GraphData`; `to_html` renders that into one self-contained, offline-capable
HTML file; `show` displays it, inline in a Jupyter kernel or as a browser tab
opened against a throwaway local webserver otherwise.
"""

from .build import EdgeEntry, GraphData, GroupEntry, NodeEntry, build_graph
from .render import to_html
from .show import show

__all__ = [
    "EdgeEntry",
    "GraphData",
    "GroupEntry",
    "NodeEntry",
    "build_graph",
    "show",
    "to_html",
]
