"""`show`: the one impure entry point, tested headless.

Neither branch is exercised for real -- no actual Jupyter kernel, no actual
browser window -- only that `show` dispatches correctly on whether a kernel
is running, in the style of `tests/tui/graph_browser/test_app.py`. What the
picture contains is `test_build.py`/`test_render.py`'s business.
"""

import importlib
import urllib.request

import pytest

import graph
from tests.helpers import make_pricer

# viz/__init__.py re-exports the `show` function under the same name as this
# submodule -- the same shadowing `from graph import node` relies on for the
# decorator -- so the submodule itself is reached through `importlib` rather
# than `viz.show`, which would now be the function.
show_module = importlib.import_module("viz.show")


@pytest.fixture
def cell():
    Pricer = make_pricer()
    return graph.cell(Pricer().pv.key())


class TestJupyterBranch:
    def test_a_running_kernel_displays_inline_and_returns_none(self, monkeypatch, cell):
        pytest.importorskip("IPython", reason="the jupyter extra is not installed")
        import IPython.display

        monkeypatch.setattr(show_module, "_get_ipython", lambda: object())
        shown = []
        monkeypatch.setattr(IPython.display, "display", lambda obj: shown.append(obj))

        result = show_module.show(cell)

        assert result is None
        assert len(shown) == 1
        assert "dagre" in shown[0].data.lower()

    def test_a_running_kernel_never_starts_a_server(self, monkeypatch, cell):
        pytest.importorskip("IPython", reason="the jupyter extra is not installed")
        import IPython.display

        monkeypatch.setattr(show_module, "_get_ipython", lambda: object())
        monkeypatch.setattr(IPython.display, "display", lambda obj: None)
        called = []
        monkeypatch.setattr(
            show_module, "_serve_and_open", lambda html: called.append(html)
        )

        show_module.show(cell)

        assert called == []


class TestTerminalBranch:
    def test_no_kernel_opens_a_browser_tab_and_returns_the_server(
        self, monkeypatch, cell
    ):
        monkeypatch.setattr(show_module, "_get_ipython", lambda: None)
        opened = []
        monkeypatch.setattr(
            show_module.webbrowser, "open", lambda url: opened.append(url)
        )

        server = show_module.show(cell)
        try:
            assert len(opened) == 1
            assert opened[0].startswith("http://127.0.0.1:")
        finally:
            server.shutdown()
            server.server_close()

    def test_the_server_actually_serves_the_picture(self, monkeypatch, cell):
        monkeypatch.setattr(show_module, "_get_ipython", lambda: None)
        monkeypatch.setattr(show_module.webbrowser, "open", lambda url: None)

        server = show_module.show(cell)
        try:
            port = server.server_address[1]
            with urllib.request.urlopen(
                f"http://127.0.0.1:{port}/", timeout=5
            ) as response:
                body = response.read().decode("utf-8")
            assert "dagre" in body.lower()
        finally:
            server.shutdown()
            server.server_close()

    def test_no_kernel_never_displays_inline(self, monkeypatch, cell):
        monkeypatch.setattr(show_module, "_get_ipython", lambda: None)
        monkeypatch.setattr(show_module.webbrowser, "open", lambda url: None)
        called = []
        monkeypatch.setattr(
            show_module,
            "_display_inline",
            lambda html: called.append(html),
        )

        server = show_module.show(cell)
        try:
            assert called == []
        finally:
            server.shutdown()
            server.server_close()


class TestGetIpython:
    def test_returns_none_when_ipython_is_not_installed(self, monkeypatch):
        import builtins

        real_import = builtins.__import__

        def blocked(name, *args, **kwargs):
            if name == "IPython" or name.startswith("IPython."):
                raise ImportError(f"{name} is not installed")
            return real_import(name, *args, **kwargs)

        monkeypatch.setattr(builtins, "__import__", blocked)

        assert show_module._get_ipython() is None
