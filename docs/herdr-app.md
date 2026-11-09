# Herdr App: first Codex account

The native App integration currently registers one Codex account, shows its
identity, and opens an isolated Codex session or terminal. Additional accounts
and conversation-preserving switching are subsequent tickets.

The App home and account home are separate from the source checkout. Credentials
never belong in this repository. The controller requires an explicit account
home and uses the upstream profile store inside that private home.

## Install into a preview

Use a separate App home first. Supply your checkout's location and the existing
Herdr App layout as the base:

```sh
python3 install_app.py --app-home /path/to/preview --base-layout /path/to/herdr-app/layouts/main.json
```

This creates a personal layout named `codex-accounts` and a personal mod with
the same name. It does not select the layout or change existing sessions.
The generated mod configuration points at this checkout and the Python
interpreter used for installation, so keep both available.

Run a preview window with `HERDR_APP_HOME` pointing at that preview. Use a
separate `HC_SESSION`, a short private `HC_SOCKET`, and scratch XDG directories
for its core. macOS Unix socket paths must remain short. Never stop or restart
the normal Herdr core to test this integration.

Select the personal layout through Herdr's layout command. The button appears
at the right of the tab bar. The public mod command `codex-accounts.open` opens
the same selector, useful for a key binding or a runtime check.

## Connect and use the account

1. Choose **Conectar cuenta**. The official Codex login opens in a named tab
   and the browser. Complete it yourself; the mod never receives your tokens.
2. The selector shows the registered account after Codex confirms its login.
3. Choose **Abrir Codex** for a managed conversation, or **Abrir terminal**
   and type `codex` there.
4. A pre-existing terminal remains outside this account group and is identified
   as unadministered. Open a managed terminal instead of changing that session.

Managed terminals use a clean zsh and a local Codex launcher. Personal shell
startup files and the global Codex configuration are not imported. The launcher
uses the private account home, removes inherited API-key authentication, and
disables the shared Codex daemon. Login/logout and remote-account redirection
are handled through the selector rather than the managed Codex command.

When a managed program exits, its account label is released before Herdr returns
to an ordinary shell. Codex commands inside a managed terminal keep that
terminal's label until the managed shell itself exits.

Cancelling the login terminates only the login process started for that
registration. A failed login leaves the account list unchanged. Profiles and
login state persist in the private account home, not in the App layout.

## Validate

The public controller tests run official-CLI-shaped fixtures in temporary
directories; they never use an actual login or keychain:

```sh
python3 -m unittest test_herdr_accounts
python3 test_switcher.py
python3 -m py_compile herdr_accounts.py install_app.py
herdr-app check /path/to/preview/mods/codex-accounts
```

Inspect the empty, login-in-progress, error and connected states in the preview.
Complete a real login, open a managed conversation, and check that its account
identity matches the selector. This ticket does not claim a cross-account
continuity test: that requires another real account and the following ticket.

Rollback removes the personal mod and layout, and stops using their managed
terminals. Keep the account home unless you intentionally want to discard its
saved logins. Other App layouts and external credential stores are unchanged.
