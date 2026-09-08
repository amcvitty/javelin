Before each commit we run

Standardise formatting: `uv run ruff format`
Lint and fix: `uv run ruff check --fix`
Check types: `uv run ty check`
Check types again: `uv run pyright`

Both type checkers, because they disagree. `ty` is fast but still young; pyright
is what Pylance runs in the editor, so its errors are the ones that show up
while editing. Neither is a superset of the other -- a decorator returning a
union once cost 142 pyright errors that `ty` reported as clean.

## Agent skills

### Issue tracker

Issues and specs live in Linear (via the `linear-server` MCP), team `GEN`, project `MacDB`. See `docs/agents/issue-tracker.md`.

### Triage labels

Five canonical roles, label strings unchanged from the defaults. See `docs/agents/triage-labels.md`.

### Domain docs

Single-context: `CONTEXT.md` + `docs/adr/` at the repo root. See `docs/agents/domain.md`.
