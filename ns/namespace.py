"""The namespace: objects by name, backed by a store.

Looking a name up returns the *same* object every time. A cell key holds the
object itself, so handing out two instances for one name would fork the graph
in a way nothing would notice.
"""

import graph

from .mcobject import CREATION_TOKEN
from .store import SqliteStore


class Namespace:
    """A set of well-known objects, linked to a store."""

    def __init__(self, store=None):
        self._objects = {}
        self._store = store if store is not None else SqliteStore()

    # -- looking up --------------------------------------------------------

    def __getitem__(self, name):
        """The object with this name, loading it from the store if need be."""
        if name in self._objects:
            return self._objects[name]
        loaded = self._load(name)
        if loaded is None:
            raise KeyError(name)
        return loaded

    def __contains__(self, name):
        return name in self._objects or self._store.read(name) is not None

    def get(self, name, default=None):
        try:
            return self[name]
        except KeyError:
            return default

    # -- creating ----------------------------------------------------------

    def new(self, cls, **values):
        """A new object with a generated name."""
        return self._register(cls, None, values)

    def lookup_or_new(self, name, cls, **values):
        """The object called `name`, made if it is not already there.

        `values` are applied either way -- over the class's defaults for a new
        object, or over what was loaded for an existing one.
        """
        obj = self._objects.get(name) or self._load(name)
        if obj is None:
            return self._register(cls, name, values)
        self._apply(obj, values)
        return obj

    def _register(self, cls, name, values):
        obj = cls(CREATION_TOKEN, name=name, ns=self)
        if obj.name in self._objects:
            raise ValueError(f"{obj.name} is already in the namespace")
        self._objects[obj.name] = obj
        self._apply(obj, values)
        return obj

    def _apply(self, obj, values):
        """Set values on an object's cells, as ns.new(cls, Field=...) does."""
        for field, value in values.items():
            if not isinstance(getattr(type(obj), field, None), graph.Node):
                raise TypeError(f"{type(obj).__name__}.{field} is not a node")
            getattr(obj, field).set_value(value)

    # -- storing -----------------------------------------------------------

    def store(self, obj):
        """Persist an object, so that a later lookup of its name finds it."""
        self._store.write(obj.name, type(obj), obj.stored_values())

    def _load(self, name):
        """Rebuild an object from the store, or None if it is not there."""
        found = self._store.read(name)
        if found is None:
            return None
        cls, values = found
        obj = cls(CREATION_TOKEN, name=name, ns=self)
        self._objects[name] = obj
        # Stored cells come back as set values, so the bodies never run.
        self._apply(obj, values)
        return obj

    # -- housekeeping ------------------------------------------------------

    def clear(self):
        """Forget every object held in memory. The store is left alone."""
        self._objects.clear()

    def all_objects(self):
        return tuple(self._objects.values())


DEFAULT = Namespace()
