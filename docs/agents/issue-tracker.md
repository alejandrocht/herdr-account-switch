# Issue tracker: GitHub

Issues and specs live in `alejandrocht/herdr-account-switch`.
Use the `gh` CLI, prefixed with `rtk`.

## Conventions

- Target `--repo alejandrocht/herdr-account-switch` explicitly.
- Create specs and implementation tickets as GitHub issues.
- Use one issue per implementation ticket.
- Use `--body-file` for multiline descriptions and comments.
- Read the issue body, comments and labels before working.
- Record dependencies between tickets.
- Apply triage labels from `triage-labels.md`.
- Resolve issues with a comment explaining the result and validation.

`origin` is our fork; `upstream` is the original project.

## Pull requests as a triage surface

**PRs as a request surface: no.**

## Wayfinding

- The map is an issue labelled `wayfinder:map`.
- Each child ticket is a separate issue linked as a sub-issue.
- If sub-issues are unavailable, use a task list in the map and
  a `Part of #<map>` reference in each child.
- Ticket types use `wayfinder:research`, `wayfinder:prototype`,
  `wayfinder:grilling` or `wayfinder:task`.
- Use native issue dependencies; otherwise record `Blocked by: #<number>`.
- Select the first open, unassigned ticket without open blockers.
- Claim a ticket by assigning it before starting work.
- On resolution, comment, close the ticket and update the map's decisions.
