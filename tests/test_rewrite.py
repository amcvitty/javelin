"""How @node rewrites a body into a pure function of its input values.

def fib(self, node, ivs):
    return ivs[0] if ivs[0] < 2 else ivs[1] + ivs[2]

ivs[0] = n
ivs[1] = self.fib(n - 1) if not n < 2
ivs[2] = self.fib(n - 2) if not n < 2
"""

import pytest

import graph
from graph import node
from tests.helpers import make_calc


def helper():
    """A module-level function that is deliberately not a node."""
    return 0


def helper_taking(obj):
    return obj


class TestRewrite:
    def test_parameters_and_node_calls_become_input_values(self):
        class Calc:
            @node
            def fib(self, n):
                return n if n < 2 else self.fib(n - 1) + self.fib(n - 2)

        assert graph.code(Calc.fib) == (
            "def fib(self, node, ivs):\n"
            "    return ivs[0] if ivs[0] < 2 else ivs[1] + ivs[2]"
        )

    def test_inputs_list_arguments_then_calls_with_their_guards(self):
        class Calc:
            @node
            def fib(self, n):
                return n if n < 2 else self.fib(n - 1) + self.fib(n - 2)

        assert [str(i) for i in graph.inputs(Calc.fib)] == [
            "n",
            "self.fib(n - 1) if not n < 2",
            "self.fib(n - 2) if not n < 2",
        ]

    def test_arguments_are_terminals_and_calls_are_edges(self):
        class Calc:
            @node
            def fib(self, n):
                return n if n < 2 else self.fib(n - 1) + self.fib(n - 2)

        n, left, right = graph.inputs(Calc.fib)
        assert isinstance(n, graph.Value)
        assert isinstance(left, graph.Edge) and left.target == "fib"
        assert isinstance(right, graph.Edge) and right.target == "fib"

    def test_undecorated_calls_stay_in_the_body(self):
        Calc = make_calc()

        assert graph.code(Calc.sum) == (
            "def sum(self, node, ivs):\n    return ivs[0] + ivs[1] + self.c() + 1"
        )
        assert [str(i) for i in graph.inputs(Calc.sum)] == ["self.a()", "self.b()"]

    def test_module_level_calls_stay_in_the_body(self):
        class Calc:
            @node
            def a(self):
                return 1

            @node
            def sum(self):
                return self.a() + helper()

        assert graph.code(Calc.sum) == (
            "def sum(self, node, ivs):\n    return ivs[0] + helper()"
        )
        assert Calc().sum() == 1

    def test_early_return_guards_what_follows(self):
        class Calc:
            @node
            def fib(self, n):
                if n < 2:
                    return n
                return self.fib(n - 1) + self.fib(n - 2)

        assert [str(i) for i in graph.inputs(Calc.fib)] == [
            "n",
            "self.fib(n - 1) if not n < 2",
            "self.fib(n - 2) if not n < 2",
        ]
        assert Calc().fib(6) == 8

    def test_guards_do_not_leak_out_of_a_nested_block(self):
        """An early return inside an if only guards the rest of *that* block.

        The guard for self.b() is `not n > 0` alone: the inner `if n > 5`
        return must not still be in force once its block has been left.
        """

        class Calc:
            @node
            def a(self):
                return 1

            @node
            def b(self):
                return 2

            @node
            def f(self, n):
                if n > 0:
                    if n > 5:
                        return 0
                    return self.a()
                return self.b()

        assert [str(i) for i in graph.inputs(Calc.f)] == [
            "n",
            "self.a() if n > 0 and (not n > 5)",
            "self.b() if not n > 0",
        ]
        c = Calc()
        assert (c.f(-1), c.f(3), c.f(9)) == (2, 1, 0)
        assert graph.deps(c.f, -1) == {(c, Calc.b)}

    def test_short_circuit_guards(self):
        class Calc:
            @node
            def a(self):
                return 0

            @node
            def b(self):
                return 2

            @node
            def either(self):
                return self.a() or self.b()

        assert [str(i) for i in graph.inputs(Calc.either)] == [
            "self.a()",
            "self.b() if not self.a()",
        ]
        assert Calc().either() == 2

    def test_node_calls_nested_in_arguments_are_evaluated_first(self):
        class Calc:
            @node
            def one(self):
                return 1

            @node
            def double(self, n):
                return n * 2

            @node
            def answer(self):
                return self.double(self.one())

        calc = Calc()
        assert [str(i) for i in graph.inputs(Calc.answer)] == [
            "self.one()",
            "self.double(self.one())",
        ]
        assert graph.deps(calc.answer) == {(calc, Calc.one), (calc, Calc.double, 1)}
        assert calc.answer() == 2

    def test_nodes_may_reference_ones_defined_later_in_the_class(self):
        class Parity:
            @node
            def even(self, n):
                return True if n == 0 else self.odd(n - 1)

            @node
            def odd(self, n):
                return False if n == 0 else self.even(n - 1)

        p = Parity()
        assert graph.deps(p.even, 2) == {(p, Parity.odd, 1)}
        assert p.even(4) is True
        assert p.odd(4) is False


class TestUnsupported:
    """Patterns that cannot be turned into a fixed list of inputs, or that
    would let a node see more than functions and constants, fail when the
    class is created rather than silently building the wrong graph."""

    def test_reference_to_a_member_variable(self):
        with pytest.raises(ValueError, match="member variable self.x"):

            class Calc:
                def __init__(self):
                    self.x = 1

                @node
                def total(self):
                    return self.x + 1

    def test_self_used_as_a_value(self):
        with pytest.raises(ValueError, match="'self' may only be used to call"):

            class Calc:
                @node
                def me(self):
                    return helper_taking(self)

    def test_node_call_inside_a_loop(self):
        with pytest.raises(ValueError, match="loop"):

            class Calc:
                @node
                def a(self):
                    return 1

                @node
                def total(self):
                    acc = 0
                    for _ in range(3):
                        acc += self.a()
                    return acc

    def test_node_call_whose_argument_is_a_local(self):
        with pytest.raises(ValueError, match="local 'x'"):

            class Calc:
                @node
                def double(self, n):
                    return n * 2

                @node
                def answer(self):
                    x = 3
                    return self.double(x)

    def test_rebinding_a_parameter(self):
        with pytest.raises(ValueError, match="rebound"):

            class Calc:
                @node
                def bump(self, n):
                    n = n + 1
                    return n

    def test_async_node(self):
        with pytest.raises(ValueError, match="must be a plain def"):

            class Calc:
                @node
                async def a(self):
                    return 1

    def test_node_without_self(self):
        with pytest.raises(ValueError, match="needs a self parameter"):

            class Calc:
                @node
                def a():
                    return 1
