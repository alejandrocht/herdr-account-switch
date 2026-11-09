# Ticket #2: validation checkpoint

Recorded 2026-11-09. The initial account validation was postponed; the user
subsequently completed the official login. Real-account results are recorded
below. Final keyboard interaction verification remains pending.

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
The initial pending login was cancelled. A subsequent official login registered
the first account successfully, as recorded below.

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

## Divider follow-up

The user reported that the tab-bar divider stopped at the account button. A live
frame reproduced the gap. The selector now draws the same one-pixel bottom
border and theme color as the shipped tabs mod. Source and installed-mod native
checks passed. A fresh frame confirmed matching border pixels on both sides of
the join. This check covers the reported divider defect only; the outstanding
account and keyboard validation above remains pending.

## Real-account demonstration

- The user completed the official browser login. The public controller reports
  one identifiable active profile and a completed registration.
- A native preview tab launched the public `launch` workflow with a read-only
  Codex request. Its saved final response matched `HERDR_ACCOUNT_OK`.
- Another native preview tab used the public managed `shell` workflow and the
  ordinary `codex` command. Its saved response matched `HERDR_SHELL_OK`, and the
  command exited successfully. No model tools or project changes were requested.
- The connected selector was inspected in a fresh native frame: identity and
  both launch actions were visible. The image remains local and is not published.
- The user independently confirmed the first account's identity and then opened
  interactive Codex through **Abrir Codex**. Public native metadata confirmed the
  selected Codex pane was launched by the account controller and carried the
  private managed-account label. No input was sent to that conversation.
- Native Herdr keeps a normal shell after an explicit command finishes. The live
  check revealed that our account label previously survived that transition.
  The controller now supervises its managed process and releases its own label
  before returning. Nested Codex commands preserve their managed shell's label.
  A public-CLI regression reproduced the stale label before the fix; all ten
  controller tests passed afterward. The real normal-command tab also returned
  to an ordinary zsh with no managed-account label.

This establishes initial registration and authenticated requests for the first
account. It does not establish cross-account conversation continuity or prove
keyboard interactions that have not yet been exercised.

## Standards

The independent review of `1a0014e...2509af6` found no documented-standard
violations or material baseline smells. Process supervision and label ownership
remain together and reuse the existing child cleanup. The reviewer independently
reran all ten temporary-fixture tests successfully without accessing real accounts.

## Spec

The independent review found no new code defects or scope creep in the lifecycle
fix. Managed labels now end with their owning process; nested Codex retains its
managed shell's label. Real registration and both authenticated launch paths are
demonstrated. Final keyboard interaction evidence is still pending and has been
requested from the user, so #2 remains open.

Review totals: Standards zero findings; Spec zero new code findings and one
remaining validation gap (native keyboard interaction).
