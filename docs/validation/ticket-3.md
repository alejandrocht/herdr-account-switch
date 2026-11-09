# Ticket #3: implementation and remaining live proof

Recorded 2026-11-09. The selector supports adding saved accounts and a verified
native-thread switch for one compatible conversation. It remains open until
A → B → A is demonstrated with two distinct real accounts. #2 was reopened
after the user's isolation regression report; see its validation document.

## Automated evidence

- `python3 -m unittest -q test_herdr_accounts test_preview`: 25 tests passed.
  Temporary credentials only; no real browser login or global credential writes.
- `python3 test_switcher.py`: original checks passed, zero failures.
- Python compilation and the source native mod check passed.
- A native preview with three fictitious profiles rendered the saved-account
  list, active marker, add, launch, terminal and native resume actions. A fresh
  native frame was inspected; no render errors remained.

The public tests verify fresh additional registration, deduplication with four
saved accounts, failed/cancelled/interrupted registration, target rejection,
waiting for an active tool, the same native thread/tool results across a cycle,
no tool replay, failure rollback, and preservation of credentials renewed by a
target whose adoption fails. SIGTERM during warm or cold adoption restores the
previous selection. Registration and selection cannot overlap.

The actual mod callback plus the observed macOS native wrapper reproduced the
external-auth escape before the fix. The fixed callback starts the account
process directly through core. A separate real temporary core verified private
CODEX_HOME and Codex command resolution after the macOS fallback and in a normal
new terminal, plus unchanged external fake-auth state. It stopped only its own
core. All of these checks are runnable without real account access.

The exact installed Codex 0.167.0 binary was separately tested with fictitious
credentials and a local Responses fixture: a completed native thread resumed
after a server restart with its original ID and context. This protocol check
does not prove that two actual accounts can use that thread.

## Limits and remaining acceptance

- Start the corrected window with `preview.py` or `open-preview.command`.
  HERDR_APP_HOME alone is insufficient. Earlier cores and their sessions remain
  running separately; no existing user conversation was killed or migrated.
- Only one compatible live conversation can switch in this delivery. Multiple
  simultaneous conversations are explicitly refused pending #4.
- An empty thread needs its first saved turn before native resume is possible.
- SIGKILL/crash recovery and account reauthentication are not claimed here (#5).
- Claude accounts and activation in the user's normal App remain #6 and #7.

Before closing #2/#3, register the second real account using **Añadir cuenta** in
the corrected preview. Verify the external account is unchanged. With a saved
native conversation containing messages and a tool result, select B then A;
confirm effective account identities, the same native thread and results, and
unchanged local work. No second real-account test has been executed by the agent.
