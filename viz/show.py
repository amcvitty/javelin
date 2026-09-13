"""`show(cell)`: the one impure entry point.

    viz.show(graph.cell(book.pv.key(True)))

Builds the picture (`build_graph`, `to_html` -- both pure) and delivers it
one of two ways: inline, the way `matplotlib`/`seaborn` plots appear in a
notebook, if a Jupyter kernel is running; otherwise as a browser tab opened
against a throwaway local webserver, with the link printed for a reader
following along in a terminal that cannot open one itself.

The server is started once per call and kept alive for the life of the
process on a daemon thread -- there is no shared server reused across calls
and no shutdown-after-first-request, so `viz.show` can be called repeatedly
without one call's page going dark under a reader still looking at it.
"""

import http.server
import threading
import webbrowser

from .build import build_graph
from .render import to_html


def show(cell):
    """Show `cell`'s transitive dependency graph.

    Returns the `HTTPServer` outside a kernel, so a caller (or a test) that
    needs to shut it down explicitly can; returns `None` inside one, where
    there is no server to hand back.
    """
    html_text = to_html(build_graph(cell))
    if _get_ipython() is not None:
        _display_inline(html_text)
        return None
    return _serve_and_open(html_text)


def _get_ipython():
    """The running IPython kernel, or `None` outside one or without IPython."""
    try:
        from IPython import get_ipython
    except ImportError:
        return None
    return get_ipython()


def _display_inline(html_text):
    from IPython.display import HTML, display

    display(HTML(html_text))


def _serve_and_open(html_text):
    server = http.server.HTTPServer(("127.0.0.1", 0), _handler_for(html_text))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    url = f"http://127.0.0.1:{server.server_address[1]}/"
    print(url)
    webbrowser.open(url)
    return server


def _handler_for(html_text):
    """A request handler that serves `html_text` for any GET -- one page, always."""
    body = html_text.encode("utf-8")

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, format, *args):
            # Silences per-request access logging to stderr: a debugging tool
            # opening one page has nothing worth logging.
            pass

    return Handler
