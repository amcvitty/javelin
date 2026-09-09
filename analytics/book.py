"""Positions and books: the ``/pos`` and ``/book`` layers.

A ``Position`` is one instrument plus a size; a ``Book`` is a list of position
names. Both reach what they price through the namespace, so a book's ``pv`` is a
real graph aggregate -- setting spot on one underlying dirties exactly the
positions that touch it and the books those positions are in.

A position is a net holding, not a transaction: it has no price, timestamp or
counterparty. The ``/trade`` prefix is reserved for those (GEN-33).

See ``docs/adr/0002-book-representation.md`` for why membership is a stored list
of paths and why direction is a signed quantity.
"""

from graph import node
from ns import McObject


class Position(McObject):
    """One instrument, held long or short, named ``/pos/<asset>/<desk>/<id>``."""

    @node(node.Stored)
    def instrument_path(self):
        """Namespace path of the instrument this position is on."""
        return "/inst/EQ/Option/UNSET"

    @node(node.Stored)
    def quantity(self):
        """Signed size: positive long, negative short.

        One number rather than a size and a direction, which could disagree --
        see ``docs/adr/0002``. A long/short label is a derived node if wanted.
        """
        return 1.0

    @node
    def instrument(self):
        """The instrument object this position references."""
        return self.ns[self.instrument_path()]

    @node
    def pv(self):
        """Present value of the position: the instrument's unit pv, times size."""
        return self.quantity() * self.instrument().pv()


class Book(McObject):
    """A named collection of positions, named ``/book/<asset>/<desk>/<name>``."""

    @node(node.Stored)
    def position_paths(self):
        """Namespace paths of the positions in this book.

        Stored rather than derived from the store, so that membership is a graph
        input: adding a position is a ``set_value`` here, which dirties ``pv``.
        """
        return []

    @node
    def pv(self):
        """Present value of the book: the sum of its positions'.

        One ``MapEdge``: the comprehension is one call site naming one cell per
        member, so every position is a real dependency of this node.
        """
        return sum(self.ns[path].pv() for path in self.position_paths())
