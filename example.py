from graph import node, inspect
import graph


@node
def fibonacci(n):
    return 1 if n < 2 else fibonacci(n - 1) + fibonacci(n - 2)


@node
def a():
    return 1


@node
def b():
    return 2


def c():
    return 4


@node
def sum():
    return a() + b() + c() + 1


print(graph.deps(sum))  # Output: {<function a at ...>, <function b at ...>}
print(graph.deps(fibonacci, 5))
