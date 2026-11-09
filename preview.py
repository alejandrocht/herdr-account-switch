#!/usr/bin/env python3
"""Open the isolated Herdr preview, including its shell and recovery boundary."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shlex
import subprocess
import sys

from herdr_accounts import Accounts, AccountError


def preview_home(app_home):
    app = Path(app_home).expanduser().resolve()
    if app in (Path.home(), Path("/"), Path.home() / ".config/herdr-app"):
        raise AccountError("Usa un directorio exclusivo para la ventana de prueba de Herdr.")
    return app


def require_closed_window(app):
    result = subprocess.run(["herdr-app", "status"],
        env=dict(os.environ, HERDR_APP_HOME=str(app), LC_ALL="C"),
        capture_output=True, text=True, timeout=5)
    if result.returncode == 0:
        raise AccountError("Ya hay una ventana de prueba abierta. Cierra solo esa ventana y vuelve a abrirla con este lanzador; sus sesiones permanecen en el core.")
    if result.returncode != 2 or not any(reason in result.stderr for reason in (
            "Connection refused", "No such file or directory")):
        raise AccountError("No se pudo comprobar la ventana de prueba. No se ha cambiado su entorno.")


def environment(app_home, binary=None):
    app = preview_home(app_home)
    accounts = Accounts(app / "accounts", binary)
    accounts.private_dir(accounts.root)
    env = accounts.shell_environment()
    for key in list(env):
        if key.startswith("HC_"):
            env.pop(key)
    env.pop("HERDR_ACCOUNT_GROUP", None)
    runtime = app / "runtime"
    if runtime.is_symlink():
        raise AccountError("El entorno de prueba no admite enlaces externos.")
    accounts.private_dir(runtime)
    key = hashlib.sha256(str(app).encode()).hexdigest()[:12]
    env.update(HERDR_APP_HOME=str(app), HC_SESSION="accounts-" + key,
               HC_SOCKET=f"/tmp/herdr-accounts-{os.getuid()}-{key}.sock")
    for kind in ("CONFIG", "STATE", "DATA", "CACHE"):
        folder = runtime / kind.lower()
        accounts.private_dir(folder)
        env[f"XDG_{kind}_HOME"] = str(folder)
    controller = str(Path(__file__).with_name("herdr_accounts.py").resolve())
    command = [sys.executable, controller, "--home", str(accounts.root), "--codex", accounts.binary, "shell"]
    # This config belongs to this preview's core only, and also covers recovery.
    accounts.write(runtime / "config/herdr-core/config.toml",
                   "notes = false\nshell = " + json.dumps(command) + "\n")
    # Herdr's macOS agent wrapper loads zsh profiles. Its fallback must keep the
    # preview boundary even after the requested agent has exited.
    dotdir = runtime / "zsh"
    accounts.private_dir(dotdir)
    keys = ("CODEX_HOME", "CODEX_SQLITE_HOME", "HERDR_PLUGIN_STATE_DIR", "HERDR_PLUGIN_CONFIG_DIR",
            "CLAUDE_CONFIG_DIR", "HERDR_ACCOUNTS_CODEX_BINARY", "PATH")
    accounts.write(dotdir / ".zshenv", "".join(f"export {name}={shlex.quote(env[name])}\n" for name in keys))
    # /etc/zprofile's macOS path_helper reorders PATH after .zshenv. Reapply
    # the boundary after the system's login/interactive startup files too.
    for name in (".zprofile", ".zshrc", ".zlogin"):
        accounts.write(dotdir / name, 'source "$ZDOTDIR/.zshenv"\n')
    env["ZDOTDIR"] = str(dotdir)
    return env


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--app-home", required=True)
    args = parser.parse_args()
    try:
        app = preview_home(args.app_home)
        require_closed_window(app)
        env = environment(app)
        # Always refresh the recorded core context: a previous preview may have
        # used another private core. This never stops or changes its sessions.
        accounts = Accounts(Path(env["CODEX_HOME"]).parent)
        accounts.write(accounts.root / "core.json",
            {k: v for k, v in env.items() if k in ("HC_SOCKET", "HC_SESSION") or k.startswith("XDG_")})
        return subprocess.call(["herdr-app"], env=env)
    except (AccountError, OSError, subprocess.TimeoutExpired) as error:
        print(str(error), file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
