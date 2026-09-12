"""The browser is a debugging tool, and must not change how the engine installs.

The engine has no runtime dependencies. The terminal library brings several
transitive packages with it, so it is an optional extra, and the two
directions of that promise are checked here: the engine never reaches for the
library, and the rendering logic can be imported and tested without it.

Both tests run in a subprocess. In this one the library is installed, so an
assertion about `sys.modules` in this process would pass for the wrong reason.
"""

import subprocess
import sys
import textwrap


def run(source):
    """Run a snippet in a fresh interpreter, and return it having succeeded."""
    result = subprocess.run(
        [sys.executable, "-c", textwrap.dedent(source)],
        capture_output=True,
        text=True,
        # Checked below instead, so a failure shows the snippet's traceback
        # rather than a CalledProcessError saying only that it exited 1.
        check=False,
    )
    assert result.returncode == 0, result.stderr
    return result


class TestOptionalExtra:
    def test_importing_the_engine_does_not_import_the_terminal_library(self):
        run("""
            import sys

            import graph
            import ns
            from graph import Cell, Slot, node

            assert "textual" not in sys.modules, sorted(
                m for m in sys.modules if m.startswith("textual")
            )
            assert "rich" not in sys.modules
        """)

    def test_the_rendering_logic_imports_without_the_terminal_library(self):
        """With the library made unimportable, `browser.render` still loads --
        so the engine's own tests pass in an install without the extra."""
        run("""
            import sys

            class Blocked:
                def find_spec(self, name, path=None, target=None):
                    if name.split(".")[0] in ("textual", "rich"):
                        raise ImportError(f"{name} is not installed")
                    return None

            sys.meta_path.insert(0, Blocked())

            from browser import render

            assert render.INPUT_COLUMNS[0] == "slot"

            try:
                import textual
            except ImportError:
                pass
            else:
                raise AssertionError("the block did not work")
        """)

    def test_no_module_of_the_graph_package_names_the_terminal_library(self):
        """A grep, in effect: the import that must never be written."""
        import pathlib

        import graph

        for module in pathlib.Path(graph.__file__).parent.glob("*.py"):
            source = module.read_text()
            assert "textual" not in source, module
            assert "browser" not in source, module
