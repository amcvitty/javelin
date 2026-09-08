"""Persisting objects to sqlite.

A row is one object: its name, the class to rebuild it as, and a JSON map of
stored node name to value. The class needs its own column -- a map of values
alone cannot say what to rebuild.
"""

import datetime
import importlib
import json
import sqlite3

SCHEMA = """
CREATE TABLE IF NOT EXISTS objects (
    name TEXT PRIMARY KEY,
    cls  TEXT NOT NULL,
    data TEXT NOT NULL
)
"""

#: How a value that JSON has no type for is written: tagged with its type name.
TYPE_KEY = "__type__"

_ENCODERS = {
    datetime.datetime: ("datetime", datetime.datetime.isoformat),
    datetime.date: ("date", datetime.date.isoformat),
}
_DECODERS = {
    "datetime": datetime.datetime.fromisoformat,
    "date": datetime.date.fromisoformat,
}


def encode(value, where):
    """A JSON-safe form of a stored value. `where` names it in any error."""
    if isinstance(value, bool) or value is None or isinstance(value, (int, float, str)):
        return value
    encoder = _ENCODERS.get(type(value))
    if encoder is None:
        raise TypeError(
            f"cannot store {where}: {type(value).__name__} has no stored form"
        )
    name, to_string = encoder
    return {TYPE_KEY: name, "value": to_string(value)}


def decode(value):
    if isinstance(value, dict) and TYPE_KEY in value:
        return _DECODERS[value[TYPE_KEY]](value["value"])
    return value


def class_path(cls):
    return f"{cls.__module__}:{cls.__qualname__}"


def load_class(path) -> type:
    module, _, qualname = path.partition(":")
    found: object = importlib.import_module(module)
    for part in qualname.split("."):
        found = getattr(found, part)
    if not isinstance(found, type):
        raise TypeError(f"{path} does not name a class")
    return found


class SqliteStore:
    """Objects keyed by name, in a sqlite file (or ":memory:")."""

    def __init__(self, path=":memory:"):
        self.path = path
        self._db = sqlite3.connect(path)
        self._db.execute(SCHEMA)
        self._db.commit()

    def write(self, name, cls, values):
        """Write one object. `values` is {node name: value}."""
        data = {key: encode(value, f"{name}.{key}") for key, value in values.items()}
        self._db.execute(
            "INSERT OR REPLACE INTO objects (name, cls, data) VALUES (?, ?, ?)",
            (name, class_path(cls), json.dumps(data)),
        )
        self._db.commit()

    def read(self, name):
        """(class, {node name: value}) for a stored object, or None."""
        row = self._db.execute(
            "SELECT cls, data FROM objects WHERE name = ?", (name,)
        ).fetchone()
        if row is None:
            return None
        cls, data = row
        return load_class(cls), {
            key: decode(value) for key, value in json.loads(data).items()
        }

    def names(self):
        rows = self._db.execute("SELECT name FROM objects ORDER BY name")
        return tuple(name for (name,) in rows)

    def close(self):
        self._db.close()
