"""The base class for objects that live in a namespace."""

import uuid
from typing import TYPE_CHECKING

import graph

if TYPE_CHECKING:  # pragma: no cover -- the runtime import would be a cycle
    from .namespace import Namespace

#: Passed by a Namespace when it constructs an object, so that nothing else can.
CREATION_TOKEN = object()


class McObject:
    """An object with a well-known name, belonging to a namespace.

    `name` and `ns` are plain attributes rather than nodes: they are fixed when
    the object is created, and `ns` is the one member variable a node may read.

    Equality stays identity-based. A cell key holds the object itself, so two
    instances for one name would silently fork the graph -- which is why a
    Namespace is an identity map and why objects can only be made through one.
    """

    name: str
    ns: "Namespace"

    def __init__(
        self,
        token: object = None,
        name: "str | None" = None,
        ns: "Namespace | None" = None,
    ):
        if token is not CREATION_TOKEN or ns is None:
            raise TypeError(
                f"{type(self).__name__} must be created through a namespace, "
                "with ns.new(...) or ns.lookup_or_new(...)"
            )
        self.name = name or self.default_name()
        self.ns = ns

    @classmethod
    def default_name(cls):
        """A unique name for an object nothing refers to by name."""
        return f"/{cls.__name__}/{uuid.uuid4().hex}"

    def stored_values(self):
        """This object's stored cells, as {node name: value}.

        Every stored node is evaluated, so what is written is the whole object
        rather than whichever cells happen to have been asked for.
        """
        return {name: getattr(self, name)() for name in graph.stored_nodes(type(self))}

    def store(self):
        """Persist this object, so a later lookup of its name finds it."""
        self.ns.store(self)

    def reload(self):
        """Reset this object's stored cells to what is currently in the store."""
        return self.ns.reload(self)

    def __str__(self):
        return f"<{type(self).__name__}:{self.name}>"

    def __repr__(self):
        return str(self)
