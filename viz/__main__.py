"""`python -m viz`: the demo, with no setup beyond the extra.

Reuses `example_browser`'s toy book -- the same graph `python -m
tui.graph_browser` shows one cell of at a time -- so the two tools can be
compared on the same picture.
"""

import graph
from example_browser import build

from .show import show


def main():
    book = build()
    show(graph.cell(book.pv.key(True)))


if __name__ == "__main__":
    main()
