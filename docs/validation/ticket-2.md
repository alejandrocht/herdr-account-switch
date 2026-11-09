# Ticket #2: validation checkpoint

Recorded 2026-11-09. This ticket remains open pending native interaction and
real-account evidence. The user postponed account validation until they have
access to their accounts.

## Verified

- Nine public controller integration tests passed with a temporary fake Codex:
  registration, persistence, cancellation, interrupted/orphaned login recovery,
  managed launch and shell, and rejection of credential redirection.
- The original `python3 test_switcher.py` suite passed in the dedicated test core.
- Python compilation passed. Native `herdr-app check` passed for the source mod
  and the installed personal preview mod.
- Standards and Spec reviewers rechecked the authentication, interruption and
  unavailable-agent fixes in commit `33ac0a0` without remaining code findings.
- The original pending popup was visually inspected. The visual reviewer found
  missing keyboard access to Cancel and the secondary terminal action. Native
  focus handles, navigation, activation and focus indicators were then added.

Later screenshot attempts returned stale frames because activating the preview
did not make its process the foreground application. Those captures were removed
and do not count as evidence for the latest UI changes.

## Resume validation

Use the dedicated App home `~/.config/herdr-app/previews/codex-accounts-ticket2`.
The normal App home and external applications have not been reconfigured.
The pending official login was cancelled; no real account was registered.

1. Bring the preview window itself to the foreground. Inspect the empty selector,
   then use Tab/Shift-Tab and Enter/Space to verify navigation and activation.
2. Choose **Conectar cuenta** and complete the official browser login. Confirm
   the selector identity matches that account and survives reopening the selector.
3. Open **Abrir Codex**, then **Abrir terminal** and run `codex` there. Confirm
   each managed session uses the registered identity. Existing unmanaged tabs
   must remain identified as unmanaged.
4. Capture current empty, pending, connected and unavailable/error states without
   authentication URLs or credentials. Recheck keyboard cancellation while login
   is pending and keyboard access to both connected-state actions.
5. Complete the visual review, attach only nonsecret validation evidence, and
   close #2 after all acceptance criteria are demonstrated.

Do not claim multi-account switching or conversation continuity from this ticket.
Those are #3. Persistent installation in the normal Herdr App is deferred to #7.
