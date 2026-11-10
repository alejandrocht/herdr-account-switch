# Herdr App: Codex accounts

The personal native selector registers accounts, keeps them saved, and selects
one for Codex inside the dedicated Herdr preview. The current change coordinates
one compatible conversation; multiple live conversations are rejected until #4.
Real A → B → A validation remains required before closing #3.

## Install and open

Keep the source checkout and its Python interpreter available. Credentials stay
in the preview's private accounts directory, outside the source repository.

```sh
python3 install_app.py --app-home /path/to/preview --base-layout /path/to/herdr-app/layouts/main.json
python3 preview.py --app-home /path/to/preview
```

Use `preview.py` or the generated `open-preview.command` to open the preview.
Setting HERDR_APP_HOME alone does not establish the complete isolation boundary.
If that preview window is already open, the launcher refuses to reuse it:
close only that window and relaunch; its core sessions stay running. Raising an
older window cannot apply a new environment or prove its core context.
The launcher configures a separate core, shell and recovery shell inside the
preview, private Codex command resolution, and private macOS shell startup files.
It never stops the usual Herdr core or changes its settings. Sessions in any
earlier preview core remain running there; they are not silently migrated.

The installer adds the personal `codex-accounts` layout and mod, and overrides
Codex's menu command inside this preview only. Select that layout through Herdr's
layout command. The top-right button opens the account selector.

## Register and select

1. Choose **Conectar cuenta**, then complete the official browser login yourself.
   The mod never receives your credentials. The login terminal closes on exit;
   it does not fall back to an ordinary shell.
2. Choose **Añadir cuenta** for each additional account. Each registration uses
   a fresh temporary home, preserves the active account, and deduplicates an
   already saved identity. Saved accounts do not require login on every switch.
3. Open **Abrir Codex**, or choose **Terminal** and type `codex`. The selector
   confirms a live managed process rather than trusting an old terminal label.
   **Sesión externa** means the focused pane is outside this manager.
4. Select a saved account. The selector distinguishes checking, waiting for an
   active turn/tool, resuming, confirmed adoption and failure. It keeps the
   previous effective account visible until adoption is verified.
5. **Retomar conversación guardada** opens Codex's native resume picker. Use it
   to reopen a conversation from an older managed launcher before switching.

An idle native conversation resumes by its original thread ID with its history
and tool results. The manager never resends the last prompt or replays tools.
A rejected target keeps the original session. A failed adoption restores the
previous account and the same thread, preserving renewed target credentials.
A completely empty conversation cannot resume before its first saved turn;
complete a turn or close that empty session before preparing another account.

The managed command blocks login/logout and auth/provider redirection; register
accounts through the selector. The preview does not import global Codex config
or personal shell startup files. Claude account management remains #6.

## Validate and recover

```sh
python3 -m unittest test_herdr_accounts test_preview test_native_codex
python3 test_switcher.py
python3 -m py_compile herdr_accounts.py codex_runtime.py preview.py install_app.py
herdr-app check /path/to/preview/mods/codex-accounts
```

Controller tests use temporary fictitious accounts. `test_preview` additionally
starts and stops only its own temporary native core, checking macOS fallback
and ordinary new shells against an external auth sentinel. It skips if native
Herdr/zsh are unavailable.

`test_native_codex` checks the production TUI arguments against the installed
Codex CLI in an empty temporary home and PTY. It makes no model request or
login and skips when the local CLI or PTY is unavailable.

The live acceptance check must compare two distinct real identities, keep the
same thread and tool results across A → B → A, and verify external applications
retain their account. Do not infer this from a successful single-account login.
See [the isolation regression](validation/ticket-2.md) and
[native resume design](adr/0002-resume-native-codex-on-account-switch.md).

To roll back, stop using this preview and its personal layout; keep the accounts
directory to preserve saved logins. Normal Herdr and external apps retain their
configuration. Activation in the normal App remains a later delivery (#7).
