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


class TestHoistedLocals:
    """A plain intermediate assignment whose right-hand side uses only
    parameters, earlier inputs and outside names is lifted above the body, so
    it can fill a node call's argument."""

    def test_a_local_can_feed_a_node_call_argument(self):
        class Calc:
            @node
            def expiry(self):
                return 2.0

            @node
            def rate(self, t):
                return 0.05 * t

            @node
            def disc(self):
                tenor = self.expiry() / 2.0
                return self.rate(tenor)

        calc = Calc()
        kinds = [(type(i).__name__, str(i)) for i in graph.inputs(Calc.disc)]
        assert kinds == [
            ("CallEdge", "self.expiry()"),
            ("Local", "tenor = self.expiry() / 2.0"),
            ("CallEdge", "self.rate(tenor)"),
        ]
        # The assignment is gone from the body; it reads its ivs slot instead.
        assert graph.code(Calc.disc) == "def disc(self, node, ivs):\n    return ivs[2]"
        assert graph.deps(calc.disc) == {(calc, Calc.expiry), (calc, Calc.rate, 1.0)}
        assert calc.disc() == 0.05

    def test_dependencies_through_a_local_need_no_body(self):
        evaluated = []

        class Calc:
            @node
            def a(self):
                evaluated.append("a")
                return 3.0

            @node
            def b(self, x):
                evaluated.append("b")
                return x + 1

            @node
            def c(self):
                k = self.a() + 1.0
                return self.b(k)

        calc = Calc()
        assert graph.deps(calc.c) == {(calc, Calc.a), (calc, Calc.b, 4.0)}
        # `a` is read to name b's cell, so expansion runs it; `b` never runs.
        assert evaluated == ["a"]
        assert calc.c() == 5.0

    def test_locals_may_chain(self):
        class Calc:
            @node
            def base(self):
                return 10.0

            @node
            def at(self, x):
                return x

            @node
            def chained(self):
                half = self.base() / 2.0
                shifted = half + 1.0
                return self.at(shifted)

        calc = Calc()
        assert [str(i) for i in graph.inputs(Calc.chained)] == [
            "self.base()",
            "half = self.base() / 2.0",
            "shifted = half + 1.0",
            "self.at(shifted)",
        ]
        assert graph.deps(calc.chained) == {(calc, Calc.base), (calc, Calc.at, 6.0)}
        assert calc.chained() == 6.0

    def test_a_local_used_only_in_the_body_is_not_expanded_early(self):
        evaluated = []

        class Calc:
            @node
            def rate(self):
                evaluated.append("rate")
                return 0.05

            @node
            def years(self):
                evaluated.append("years")
                return 2.0

            @node
            def factor(self):
                r = self.rate()
                t = self.years()
                return 1.0 + r * t

        calc = Calc()
        # Neither local shapes an edge, so expansion touches no body.
        assert graph.deps(calc.factor) == {(calc, Calc.rate), (calc, Calc.years)}
        assert evaluated == []
        assert graph.code(Calc.factor) == (
            "def factor(self, node, ivs):\n    return 1.0 + ivs[1] * ivs[3]"
        )
        assert calc.factor() == 1.1

    def test_a_local_can_appear_in_a_guard(self):
        class Calc:
            @node
            def threshold(self):
                return 1.0

            @node
            def spot(self):
                return 5.0

            @node
            def item(self, n):
                return n * 10

            @node
            def pick(self):
                limit = self.threshold() * 2.0
                return self.item(1) if self.spot() > limit else 0.0

        calc = Calc()
        assert graph.deps(calc.pick) == {
            (calc, Calc.threshold),
            (calc, Calc.spot),
            (calc, Calc.item, 1),
        }
        assert calc.pick() == 10

    def test_an_unhoistable_local_still_stays_in_the_body(self):
        class Calc:
            @node
            def leaf(self):
                return 2.0

            @node
            def total(self):
                acc = 0.0
                for _ in range(3):
                    acc = acc + 1.0
                return self.leaf() + acc

        calc = Calc()
        assert [str(i) for i in graph.inputs(Calc.total)] == ["self.leaf()"]
        assert "acc" in graph.code(Calc.total)
        assert calc.total() == 5.0


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

    def test_node_call_whose_argument_is_a_local_bound_more_than_once(self):
        # A singly-bound top-level assignment is hoisted (see
        # TestHoistedLocals); one rebound, or bound under a branch, cannot be.
        with pytest.raises(ValueError, match="local 'x'"):

            class Calc:
                @node
                def double(self, n):
                    return n * 2

                @node
                def answer(self):
                    x = 3
                    x = x + 1
                    return self.double(x)

    def test_node_call_whose_argument_is_a_conditionally_bound_local(self):
        # Reached only when the early return did not fire, so it cannot be
        # hoisted above the body unconditionally.
        with pytest.raises(ValueError, match="local 't'"):

            class Calc:
                @node
                def flag(self):
                    return True

                @node
                def base(self):
                    return 10.0

                @node
                def use(self, x):
                    return x

                @node
                def guarded(self):
                    if self.flag():
                        return 0.0
                    t = self.base() + 1.0
                    return self.use(t)

    def test_two_node_calls_in_one_comprehension(self):
        # One comprehension is one input, so it names one cell per element --
        # not two. The fix is a node on the element that combines them.
        with pytest.raises(ValueError, match="one node call, not 2"):

            class Calc:
                @node
                def members(self):
                    return []

                @node
                def total(self):
                    return sum(m.price() * m.size() for m in self.members())

    def test_an_expression_around_the_comprehension_element(self):
        with pytest.raises(ValueError, match="must be the node call itself"):

            class Calc:
                @node
                def members(self):
                    return []

                @node
                def total(self):
                    return sum(m.price() * 2 for m in self.members())

    def test_a_comprehension_with_an_if_filter(self):
        with pytest.raises(ValueError, match="'if' filter"):

            class Calc:
                @node
                def members(self):
                    return []

                @node
                def total(self):
                    return sum(m.price() for m in self.members() if m.live)

    def test_a_comprehension_with_two_for_clauses(self):
        with pytest.raises(ValueError, match="one 'for' clause"):

            class Calc:
                @node
                def books(self):
                    return []

                @node
                def total(self):
                    return sum(p.pv() for b in self.books() for p in b.positions)

    def test_a_set_comprehension_of_cells(self):
        with pytest.raises(ValueError, match="silently drop cells"):

            class Calc:
                @node
                def members(self):
                    return []

                @node
                def prices(self):
                    return {m.price() for m in self.members()}

    def test_a_comprehension_whose_receiver_is_itself_a_node_call(self):
        # `self.leg(m)` would be a different cell per element, so it is a
        # second node call in the element, not part of one input.
        with pytest.raises(ValueError, match="one node call, not 2"):

            class Calc:
                @node
                def members(self):
                    return []

                @node
                def leg(self, m):
                    return m

                @node
                def total(self):
                    return sum(self.leg(m).price() for m in self.members())

    def test_a_comprehension_over_plain_data_is_still_ordinary_code(self):
        # None of the above applies when nothing in the comprehension reaches
        # the graph -- that has always been, and stays, plain Python.
        class Calc:
            @node
            def rates(self):
                return [1.0, 2.0]

            @node
            def total(self):
                return sum({r * 2 for r in self.rates()} | {x for x in (8, 16)})

        assert Calc().total() == 30.0

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
