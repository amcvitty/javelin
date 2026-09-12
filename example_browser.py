"""A toy graph for the browser to show, built to exercise the display.

Small -- three classes -- but between them the input table has one of
everything it can draw: a terminal, a hoisted local, a plain call edge, a
guarded call edge, and a map edge over more legs than the table will show at
once. The objects live at real `/mkt`, `/inst` and `/book` names, so the
identity column has long paths to truncate and two markets on different
underlyings to keep apart.

Run it directly, or `python -m browser`, which shows the same cell.
"""

import ns
from browser import show_node
from graph import node
from ns import McObject

#: Enough legs that the map edge overflows the table's cap and has to
#: summarise the remainder.
LEGS = 14


class Market(McObject):
    """Market data for one underlying, at `/mkt/EQ/<ticker>/Market`."""

    @node(node.Stored)
    def spot(self):
        return 100.0

    @node(node.Stored)
    def vol(self):
        return 0.2


class Option(McObject):
    """A call, at `/inst/EQ/Option/<ticker>-C<strike>`."""

    @node(node.Stored)
    def market_path(self):
        return "/mkt/EQ/ACME/Market"

    @node(node.Stored)
    def strike(self):
        return 100.0

    @node
    def market(self):
        """Reaches across the graph: one call edge, resolved for nothing."""
        return self.ns[self.market_path()]

    @node
    def intrinsic(self):
        return max(self.market().spot() - self.strike(), 0.0)


class Book(McObject):
    """A list of option names, at `/book/EQD/exotics/<desk>`."""

    @node(node.Stored)
    def option_paths(self):
        return []

    @node
    def hedge(self):
        return -1.0

    @node
    def pv(self, hedged):
        """One node, four kinds of input.

        `hedged` is a terminal, `floor` a hoisted local, the comprehension a
        map edge naming one cell per leg, and the hedge a call edge under a
        guard -- which is what makes a blocked call site visible on screen.
        """
        floor = 0.0
        legs = [self.ns[path].intrinsic() for path in self.option_paths()]
        return sum(legs, floor) + (self.hedge() if hedged else floor)


def build():
    """The toy graph, and the cell worth looking at."""
    ns.lookup_or_new("/mkt/EQ/ACME/Market", Market, spot=105.0, vol=0.2)
    # A second market on another underlying: the identity column truncates
    # both from the left, and they must stay distinguishable.
    ns.lookup_or_new("/mkt/EQ/WIDGETCO/Market", Market, spot=95.0, vol=0.4)

    paths = []
    for leg in range(LEGS):
        option = ns.lookup_or_new(
            f"/inst/EQ/Option/ACME-C{90 + leg}",
            Option,
            strike=float(90 + leg),
        )
        paths.append(option.name)
    widget = ns.lookup_or_new(
        "/inst/EQ/Option/WIDGETCO-C100",
        Option,
        strike=100.0,
        market_path="/mkt/EQ/WIDGETCO/Market",
    )

    book = ns.lookup_or_new("/book/EQD/exotics/london", Book, option_paths=paths)

    # A dirty cell to be found in the graph, left on the leg that is *not* in
    # the book: dirtying anything the book reads would dirty the book too, and
    # dirtying a cell forgets the slots a changed value could have moved --
    # which would put the map edge back to unresolved.
    widget.intrinsic()
    ns.DEFAULT["/mkt/EQ/WIDGETCO/Market"].spot.set_value(99.0)

    # Price the book last, so its map edge is resolved and its legs have
    # values. The browser itself runs nothing: anything on screen got there by
    # having been asked for before it opened.
    book.pv(True)

    return book


def main():
    """Open the browser on the toy book's `pv`, hedged."""
    show_node(build().pv, True)


if __name__ == "__main__":
    main()
