"""Terminal tools for looking at what the engine is doing.

A home for terminal applications rather than one application: `graph_browser`
is the first, and anything else that wants a screen belongs beside it rather
than inside it.

Nothing lives at this level. The terminal library is an optional extra, so
importing `tui` must not pull it in -- each application imports it for itself,
and a `tui` package that imported anything would make installing the engine
acquire it.
"""
