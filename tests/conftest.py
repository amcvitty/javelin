import pytest

import graph


@pytest.fixture(autouse=True)
def fresh_graph():
    """Every test builds its own graph, so start from an empty default graph."""
    graph.clear()
