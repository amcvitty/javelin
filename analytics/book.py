"""Trades and books: the ``/trade`` and ``/book`` layers.

A ``Trade`` is one instrument plus a size; a ``Book`` is a list of trade names.
Both reach what they price through the namespace, so a book's ``pv`` is a real
graph aggregate -- setting spot on one underlying dirties exactly the trades that
touch it and the books those trades are in.

See ``docs/adr/0002-book-representation.md`` for why membership is a stored list
of paths and why direction is a signed quantity.
"""

from graph import node
from ns import McObject


class Trade(McObject):
    """One instrument, bought or sold, named ``/trade/<asset>/<year>/<id>``."""

    @node(node.Stored)
    def instrument_path(self):
        """Namespace path of the instrument this trade is on."""
        return "/inst/EQ/Option/UNSET"

    @node(node.Stored)
    def quantity(self):
        """Signed size: positive bought, negative sold.

        One number rather than a size and a direction, which could disagree --
        see ``docs/adr/0002``. A bought/sold label is a derived node if wanted.
        """
        return 1.0

    @node
    def instrument(self):
        """The instrument object this trade references."""
        return self.ns[self.instrument_path()]

    @node
    def pv(self):
        """Present value of the trade: the instrument's unit pv, times size."""
        return self.quantity() * self.instrument().pv()


class Book(McObject):
    """A named collection of trades, named ``/book/<asset>/<desk>/<name>``."""

    @node(node.Stored)
    def trade_paths(self):
        """Namespace paths of the trades in this book.

        Stored rather than derived from the store, so that membership is a graph
        input: adding a trade is a ``set_value`` here, which dirties ``pv``.
        """
        return []

    @node
    def pv(self):
        """Present value of the book: the sum of its trades'.

        One ``MapEdge``: the comprehension is one call site naming one cell per
        member, so every trade is a real dependency of this node.
        """
        return sum(self.ns[path].pv() for path in self.trade_paths())
