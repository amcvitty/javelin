import pytest

import graph
import ns


@pytest.fixture(autouse=True)
def fresh_graph():
    """Every test builds its own graph, so start from an empty default graph,
    namespace and store."""
    graph.clear()
    ns.clear()
    ns.clear_store()
