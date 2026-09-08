# Issue tracker: Linear

Issues and specs for this repo live in Linear. Operate on them through the Linear
MCP server (`linear-server`, Linear's hosted MCP at `https://mcp.linear.app/mcp`).
Tool names below are the server's; in this Claude Code setup they are exposed with
the `mcp__linear-server__` prefix (e.g. `mcp__linear-server__create_issue`).

## Repo -> Linear mapping

- **Team**: `GEN`. All issues for this repo are created under this team.
- **Project**: `MacDB`. New issues for this repo are filed under this project.
- Issue identifiers look like `GEN-123`. Skills that mention "ticket #N" mean the
  Linear issue `GEN-N`.

## Conventions

- **Create an issue**: `create_issue` with `team: "GEN"`, `project: "MacDB"`, `title`,
  and `description` (Markdown). Capture the returned identifier.
- **Read an issue**: `get_issue` with `id: "GEN-123"` for the issue itself; `list_comments`
  with `issueId: "GEN-123"` for its thread. Together these give description, labels,
  state, and comments.
- **List issues**: `list_issues` with `team: "GEN"`, `project: "MacDB"`, and `state` /
  `label` / `assignee` / `query` filters as the skill requires. Use `list_my_issues`
  for the current user's queue.
- **Comment on an issue**: `create_comment` with `issueId: "GEN-123"`, `body`.
- **Apply / remove labels**: `update_issue` with `id: "GEN-123"` and the full desired
  `labels` array. Discover valid label names with `list_issue_labels`. Skills should
  not invent label names outside the triage vocabulary.
- **Change workflow state**: `update_issue` with `id: "GEN-123"`, `state: "In Progress"`.
  Discover valid states with `list_issue_statuses` (team `GEN`).
- **Close**: `update_issue` to a Done/Canceled state, then `create_comment` with the
  closing note.

## Triage labels vs. workflow states

Linear separates **workflow state** (Backlog / Todo / In Progress / Done / Canceled)
from **labels**. The five canonical triage roles in `docs/agents/triage-labels.md` are
modelled as **labels**, not states, so an issue can be e.g. `Todo` + `ready-for-agent`.
`wontfix` additionally moves the issue to the `Canceled` state.

## When a skill says "publish to the issue tracker"

`create_issue` under team `GEN`, project `MacDB`.

## When a skill says "fetch the relevant ticket"

`get_issue` + `list_comments` for `GEN-<n>`.

## Pull requests as a triage surface

**PRs as a request surface: no.** GitHub PRs against `amcvitty/beacon-clone` are not
part of the triage queue. Set this to `yes` and describe the GitHub<->Linear linkage
here if that changes.

## Wayfinding operations

Used by `/wayfinder`. The **map** is a single Linear issue labelled `wayfinder:map`
holding the Notes / Decisions-so-far / Fog body; **child tickets** are Linear issues
created with `create_issue` and `parentId` set to the map issue's id.

- **Child labels**: `wayfinder:<type>` (`research` / `prototype` / `grilling` / `task`),
  set via the `labels` array on `create_issue` / `update_issue`.
- **Blocking**: use Linear's native "blocked by" issue relation. A child is unblocked
  when every blocker is in a Done/Canceled state.
- **Frontier query**: `list_issues` scoped to the map's sub-issues (`parentId`), drop
  any with an open blocker or an assignee; first in map order wins.
- **Claim**: `update_issue` to assign the child to the driving dev, the session's
  first write.
- **Resolve**: `create_comment` with the answer, `update_issue` the child to `Done`,
  then append a context pointer to the map's Decisions-so-far.
