# Native Codex TUI startup and pane adoption

Established by reproduction on 2026-11-09 with Codex CLI 0.167.0.

The public managed launcher failed with `--no-daemon cannot be used with
--remote`. Its simulated CLI had accepted an argument combination rejected by
the installed binary. Native RPC authentication checks alone had not exercised
the actual TUI executable.

Keep `--no-daemon` on the owned app-server. Connect the TUI using `--remote`
without that flag. The private endpoint selects the owned server directly.
The fixture now rejects the same invalid combination. `test_native_codex.py`
invokes the production TUI launcher with the installed binary in a temporary,
empty home and PTY, checking that it reaches its private connection attempt.
Its socket is deliberately absent; it uses no real login or model request.

The app also rejected `terminal.keep` for the new address while core reported
the Codex process live. Starting with native `herdr.space` and `herdr.tab`
labels enables the documented automatic adoption path. The mod waits for that
operation's pane, then focuses its actual pane ID. The callback fixture checks
delayed adoption and refuses premature focus/keep commands.

Verification: 27 controller/native-core/installed-CLI tests passed, native mod
check passed, and a real authenticated Codex session for the first saved account
was inspected in a visible native pane. RPC account metadata matched the
selector. The second account's private official registration was opened in
another visible tab; the first account remained active. The user deferred that
login, so the pending registration was cancelled. Two-account switching still
requires completing it and the actual A → B → A check.
