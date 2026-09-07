"""The decorator's surface: what a node looks like from outside the graph."""

import pytest

from graph import node
from tests.helpers import make_calc


class TestDecoratedBehaviour:
    def test_node_preserves_method_metadata(self):
        class Calc:
            @node
            def a(self):
                """Return one."""
                return 1

        assert Calc.a.__name__ == "a"
        assert Calc.a.__doc__ == "Return one."

    def test_nodes_are_still_callable(self):
        calc = make_calc()()
        assert calc.a() == 1
        assert calc.b() == 2
        assert calc.sum() == 1 + 2 + 4 + 1

    def test_node_outside_a_class_is_rejected(self):
        @node
        def a():
            return 1

        with pytest.raises(TypeError, match="inside a class"):
            a()
