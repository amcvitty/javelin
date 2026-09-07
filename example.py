import graph
from graph import node


class Sheet:
    @node
    def fibonacci(self, n):
        return 1 if n < 2 else self.fibonacci(n - 1) + self.fibonacci(n - 2)

    @node
    def a(self):
        return 1

    @node
    def b(self):
        return 2

    def c(self):
        return 4

    @node
    def sum(self):
        return self.a() + self.b() + self.c() + 1


sheet = Sheet()
print(graph.deps(sheet.sum))  # Output: {(sheet, Sheet.a), (sheet, Sheet.b)}
print(graph.deps(sheet.fibonacci, 5))


class Square:
    @node
    def side(self):
        return 5

    @node
    def area(self):
        return self.side() * self.side()

    @node
    def perimeter(self):
        return 4 * self.side()


square = Square()
print(graph.deps(square.area))  # Output: {(square, Square.side)}
print(square.area())  # Output: 25
