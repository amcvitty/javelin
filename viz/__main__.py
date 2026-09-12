"""`python -m viz`: the demo, with no setup beyond the extra.

Reuses `example_browser`'s toy book -- the same graph `python -m
tui.graph_browser` shows one cell of at a time -- so the two tools can be
compared on the same picture.

`show` starts its server on a daemon thread and returns immediately, on
purpose: a caller in a REPL or a long-running script keeps going with the
page still up behind it. A one-shot script has no "still going" to lean on,
so this demo waits on its own -- otherwise the process would exit, taking
the daemon thread with it, before a browser ever got to load the page.
"""

import graph
from example_browser import build

from .show import show


def main():
    book = build()
    server = show(graph.cell(book.pv.key(True)))
    if server is None:
        return  # displayed inline in a kernel; nothing to stay alive for
    try:
        input("Press Enter to stop the server and exit.\n")
    except (EOFError, KeyboardInterrupt):
        pass  # no interactive stdin to wait on, or the reader gave up waiting
    server.shutdown()


if __name__ == "__main__":
    main()
