"""A terminal browser for the graph: one cell on screen.

    show_node(option.pv)
    show_node(sheet.fibonacci, 5)

Opens a terminal application showing one cell: a header card saying what the
cell is and what it is currently worth, a table of its inputs a row per `ivs`
slot, and a table of the cells known to read it. No navigation yet.

A debugging tool, so it is an optional extra rather than a dependency:

    uv sync --extra tui

The engine has no runtime dependencies and installing it should not acquire
any, so the terminal library is imported here, inside `show_node`, rather than
at module scope -- `browser.render` can be imported and tested without it, and
the `graph` package never reaches in this direction at all.
"""

from graph import DEFAULT, Cell, make_key

from .render import header_card, input_rows, output_rows

__all__ = ["header_card", "input_rows", "output_rows", "show_node"]


def show_node(method, *args, graph=DEFAULT, **kwargs):
    """Open the browser on the cell `method(*args)`.

    `method` is a bound node -- `show_node(option.pv)` -- so the object comes
    with it, exactly as `deps` and `set_value` take one.

    `graph` defaults to the default graph, for symmetry with the other
    exploring helpers, and is there so a test can hand in an isolated one.

    Runs no body: the cell is shown as it stands, uncomputed if that is what
    it is.
    """
    if not hasattr(method, "__self__"):
        raise TypeError("show_node needs a bound node, e.g. show_node(option.pv)")
    key = make_key(method.__self__, method.__func__, args, kwargs)
    return show_cell(Cell(key, graph))


def show_cell(cell):
    """Open the browser on a cell view that has already been built."""
    from .app import CellBrowser

    return CellBrowser(cell).run()
