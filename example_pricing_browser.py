"""The shakeout graph: real options and a real book, not the toy one.

The toy in `example_browser.py` exercises the display's shapes; this exercises
the engine's real cost model against them; see GEN-46. Two underlyings, one
shared curve and pricing environment, options reaching all three through the
namespace, and a book of positions large enough to overflow the table's cap.

Run it directly, or `python -m tui.graph_browser`, which shows the same cell.
"""

import ns
from analytics.book import Book, Position
from analytics.instrument import EuropeanOption
from analytics.market import DiscountCurve, Market, PricingEnv
from tui.graph_browser import show_node

#: More than `render.MAP_ROW_CAP` (12), so the book's map edge has to
#: summarise a remainder rather than showing every position.
POSITIONS = 14


def build():
    """The real pricing graph, and the book worth looking at.

    Everything the toy graph could not exercise: options reach their market,
    curve and pricing environment through the namespace (cross-object edges),
    `tenor` is a hoisted local feeding `discount_factor`'s argument, the book's
    membership is itself a stored node (a real map edge), and the namespace
    paths are the genuine `/mkt`, `/inst`, `/pos`, `/book` taxonomy.
    """
    ns.lookup_or_new("/mkt/ENV/Default", PricingEnv)
    ns.lookup_or_new("/mkt/IR/USD/Curve", DiscountCurve, rate=0.03)
    ns.lookup_or_new("/mkt/EQ/ACME/Market", Market, spot=105.0, vol=0.2)
    # A second market on another underlying: the identity column truncates
    # both from the left, and they must stay distinguishable.
    ns.lookup_or_new("/mkt/EQ/WIDGETCO/Market", Market, spot=95.0, vol=0.4)

    paths = []
    for leg in range(POSITIONS):
        option = ns.lookup_or_new(
            f"/inst/EQ/Option/ACME-C{90 + leg}",
            EuropeanOption,
            ticker="ACME",
            strike=float(90 + leg),
        )
        # A realistically deep desk/book/date path -- well past the identity
        # column's width, so the display's left-truncation is genuinely
        # exercised rather than shown a path short enough to fit already.
        position = ns.lookup_or_new(
            f"/pos/EQD/exotics/london-flow-desk/2026-01-01/leg-{leg:04d}",
            Position,
            instrument_path=option.name,
            quantity=1.0,
        )
        paths.append(position.name)

    widget_option = ns.lookup_or_new(
        "/inst/EQ/Option/WIDGETCO-C100",
        EuropeanOption,
        ticker="WIDGETCO",
        strike=100.0,
    )
    widget_position = ns.lookup_or_new(
        "/pos/EQD/exotics/widget-hedge",
        Position,
        instrument_path=widget_option.name,
        quantity=-1.0,
    )

    book = ns.lookup_or_new("/book/EQD/exotics/london", Book, position_paths=paths)

    # A dirty cell left on a position that is *not* in the book: dirtying
    # anything the book reads would dirty the book too, and dirtying a cell
    # forgets the slots a changed value could have moved -- which would put
    # the book's map edge back to unresolved.
    widget_position.pv()
    ns.DEFAULT["/mkt/EQ/WIDGETCO/Market"].spot.set_value(99.0)

    # Price the book last, so its map edge is resolved and its legs have
    # values. The browser itself runs nothing: anything on screen got there by
    # having been asked for before it opened.
    book.pv()

    return book


def main():
    """Open the browser on the real book's `pv`.

    One session, not several: `build()` already leaves a dirty cell in the
    graph (the widget leg, outside the book) alongside the clean, computed
    `pv`, so both value states are on screen to browse to without reopening.
    Dirtying-in-front-of-the-reader and diddle scopes are exercised in
    `tests/tui/graph_browser/test_pricing_demo.py`, not here -- a demo a human
    has to quit out of four times to close is worse than one that shows less.
    """
    book = build()
    show_node(book.pv)


if __name__ == "__main__":
    main()
