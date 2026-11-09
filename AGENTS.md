# Working in this repo

`switcher.py` is the whole plugin: standard library only, no build step. Run the
checks with `python3 test_switcher.py` — they use a temporary state directory and
a fake credential backend, and never touch a real login.

Solved problems that cost real investigation live in `docs/solutions/`, stamped
with how each was established — relevant when changing anything about renewal,
switching, or the credential stores.

## Agent skills

### Issue tracker

GitHub Issues in `alejandrocht/herdr-account-switch`.
Before working with tickets or specs, read `docs/agents/issue-tracker.md`.

### Triage labels

Use the five default triage labels.
Before classifying issues, read `docs/agents/triage-labels.md`.

### Domain docs

Single-context layout: root `CONTEXT.md` and `docs/adr/`.
Before exploring code or making domain decisions, read `docs/agents/domain.md`.
