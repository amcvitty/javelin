import ast
import functools
import inspect
import textwrap

# Dependencies live here in the "graph" namespace rather than on the functions
# themselves: node function -> frozenset of the node functions it calls.
_deps: dict = {}


def _called_names(func):
    """Return the names of every function called in the body of func."""
    source = textwrap.dedent(inspect.getsource(func))
    tree = ast.parse(source)
    # ast.parse wraps the def in a Module; walk only the body so that the
    # decorators themselves are never mistaken for dependencies.
    func_def = tree.body[0]

    names = set()
    for stmt in func_def.body:
        for child in ast.walk(stmt):
            if isinstance(child, ast.Call) and isinstance(child.func, ast.Name):
                names.add(child.func.id)
    return names


def _resolve(func, name):
    """Look up name the way the body of func would see it.

    Closure cells come first so that nodes defined inside another function
    (a test, a factory) resolve just like module-level ones.
    """
    freevars = func.__code__.co_freevars
    if name in freevars and func.__closure__ is not None:
        cell = func.__closure__[freevars.index(name)]
        try:
            return cell.cell_contents
        except ValueError:
            # Cell not filled yet, e.g. a forward or recursive reference.
            return None
    return func.__globals__.get(name)


def node(func):
    """Decorator marking a function as a node (a "cell") in the dependency graph."""

    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        return func(*args, **kwargs)

    # Only names that resolve to an already-registered node become
    # dependencies, so plain function calls like c() are ignored.
    resolved = (_resolve(func, name) for name in _called_names(func))
    _deps[wrapper] = frozenset(target for target in resolved if target in _deps)
    return wrapper


def all_nodes():
    """Every registered node function."""
    return tuple(_deps)


def clear():
    """Forget every registered node. Mainly for building graphs in isolation."""
    _deps.clear()


def deps(fn):
    """The direct node dependencies of fn. Raises KeyError if fn is not a node."""
    return _deps[fn]
