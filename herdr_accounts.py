#!/usr/bin/env python3
"""Account workflow used by the Herdr App mod; credentials stay local."""
import argparse
from contextlib import contextmanager
import fcntl
import importlib
import json
import os
from pathlib import Path
import shutil
import shlex
import subprocess
import sys
import time
import uuid


class AccountError(Exception):
    pass


class Accounts:
    def __init__(self, root, binary=None):
        self.root = Path(root).expanduser().resolve()
        project = Path(__file__).resolve().parent
        if self.root in (Path.home(), Path("/"), Path.home() / ".codex") or self.root.is_relative_to(project):
            raise AccountError("Elige un directorio privado de cuentas de Herdr.")
        self.codex_home = self.root / "codex"
        self.job_file = self.root / "login.json"
        for name in ("codex", "store", "enrol", "bin", "login.json", "lock"):
            if (self.root / name).is_symlink():
                raise AccountError("El almacenamiento administrado no admite enlaces externos.")
        paths = [p for p in os.get_exec_path() if Path(p).resolve() != self.root / "bin"]
        self.binary = binary or os.environ.get("HERDR_ACCOUNTS_CODEX_BINARY") or shutil.which("codex", path=os.pathsep.join(paths))

    def environment(self, codex_home=None):
        env = dict(os.environ)
        for key in ("OPENAI_API_KEY", "CODEX_API_KEY", "CODEX_ACCESS_TOKEN", "CODEX_AUTH_JSON", "CODEX_ACCESS_TOKEN_ENV_VAR"):
            env.pop(key, None)
        env.update(CODEX_HOME=str(codex_home or self.codex_home),
                   CODEX_SQLITE_HOME=str(codex_home or self.codex_home),
                   HERDR_PLUGIN_STATE_DIR=str(self.root / "store"),
                   HERDR_PLUGIN_CONFIG_DIR=str(self.root / "store"),
                   CLAUDE_CONFIG_DIR=str(self.root / "unused-claude"),
                   ACCOUNT_SWITCH_BADGE="0", ACCOUNT_SWITCH_NOTIFY="0",
                   HERDR_ACCOUNT_GROUP=str(self.root))
        return env

    def store(self):
        os.environ.update(self.environment())
        return importlib.import_module("switcher")

    def private_dir(self, path):
        path.mkdir(parents=True, exist_ok=True, mode=0o700)
        path.chmod(0o700)

    @contextmanager
    def locked(self):
        self.private_dir(self.root)
        fd = os.open(self.root / "lock", os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
        with os.fdopen(fd, "w") as handle:
            fcntl.flock(handle, fcntl.LOCK_EX)
            yield

    def write(self, path, value):
        self.private_dir(path.parent)
        temp = path.with_name(path.name + "." + uuid.uuid4().hex)
        fd = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "w") as handle:
            if isinstance(value, str):
                handle.write(value)
            else:
                json.dump(value, handle)
        os.replace(temp, path)

    def job(self):
        return json.loads(self.job_file.read_text()) if self.job_file.exists() else {}

    def status(self):
        store = self.store()
        profiles = [{"slug": p["slug"], "label": p["label"],
                     "email": p.get("identity", {}).get("email")}
                    for p in store.list_profiles("codex")]
        active = store.active_profile("codex")
        active = next((p for p in profiles if active and p["slug"] == active["slug"]), None)
        job = self.job()
        pending = job.get("state") in ("pending", "running")
        return {"agent": "codex", "available": bool(self.binary and os.access(self.binary, os.X_OK)),
                "state": "enrolling" if pending else "active" if active else "empty",
                "profiles": profiles, "active": active,
                "login": {k: job[k] for k in ("id", "state", "error") if k in job}}

    def enrol(self):
        if not self.binary or not os.access(self.binary, os.X_OK):
            raise AccountError("Codex no está disponible en este equipo.")
        with self.locked():
            if self.status()["active"]:
                return self.status()
            job = self.job()
            if job.get("state") not in ("pending", "running"):
                job = {"id": uuid.uuid4().hex, "state": "pending"}
                self.private_dir(self.root / "enrol" / job["id"])
                self.write(self.job_file, job)
            return {"login_id": job["id"], "command": [sys.executable, str(Path(__file__).resolve()),
                    "--home", str(self.root), "--codex", self.binary, "login", job["id"]]}

    def login(self, login_id):
        with self.locked():
            job = self.job()
            if job.get("id") != login_id or job.get("state") != "pending":
                raise AccountError("Este registro ya terminó o fue cancelado.")
            job["state"] = "running"
            self.write(self.job_file, job)
        stage = self.root / "enrol" / login_id
        env = self.environment(stage)
        process = None
        try:
            options = [self.binary, "-c", 'cli_auth_credentials_store="file"',
                       "-c", 'forced_login_method="chatgpt"']
            process = subprocess.Popen([*options, "login"], env=env)
            while process.poll() is None:
                if self.job().get("id") != login_id or self.job().get("state") == "cancelled":
                    process.terminate()
                    try:
                        process.wait(timeout=3)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.wait()
                    return self.status()
                time.sleep(0.15)
            verified = process.returncode == 0 and subprocess.run(
                [*options, "login", "status"], env=env, capture_output=True, timeout=15).returncode == 0
            with self.locked():
                job = self.job()
                if job.get("id") != login_id or job.get("state") == "cancelled":
                    return self.status()
                if not verified:
                    raise AccountError("El inicio de sesión no se completó. Puedes volver a intentarlo.")
                auth = json.loads((stage / "auth.json").read_text())
                store = self.store()
                if not store.BACKENDS["codex"].identity({"auth": auth}).get("account_id"):
                    raise AccountError("Codex no confirmó la identidad de la Cuenta.")
                self.write(self.codex_home / "auth.json", auth)
                store.save_live("codex")
                self.write(self.job_file, {"id": login_id, "state": "completed"})
            return self.status()
        except (OSError, ValueError, subprocess.SubprocessError, AccountError):
            with self.locked():
                if self.job().get("id") == login_id and self.job().get("state") != "cancelled":
                    self.write(self.job_file, {"id": login_id, "state": "failed",
                               "error": "No se pudo registrar la Cuenta. Vuelve a iniciar sesión."})
            raise AccountError("No se pudo registrar la Cuenta. Vuelve a iniciar sesión.")
        finally:
            if process and process.poll() is None:
                process.terminate()
                process.wait()
            shutil.rmtree(stage, ignore_errors=True)

    def cancel(self, login_id):
        with self.locked():
            job = self.job()
            if job.get("id") == login_id and job.get("state") in ("pending", "running"):
                job["state"] = "cancelled"
                self.write(self.job_file, job)
        return self.status()

    def mark_terminal(self):
        terminal = os.environ.get("HC_TERMINAL_ID")
        if terminal and shutil.which("hc"):
            result = subprocess.run(["hc", "label", terminal, "herdr.accounts=" + str(self.root)],
                                    capture_output=True, timeout=5)
            if result.returncode:
                raise AccountError("No se pudo identificar este terminal como administrado.")

    def launch(self, arguments):
        protected = ("cli_auth_credentials_store", "forced_login_method", "model_provider",
                     "model_providers", "chatgpt_base_url", "openai_base_url")
        if any(a in ("login", "logout") or a.startswith("--remote") or
               a.split("=", 1)[0].startswith(protected) for a in arguments):
            raise AccountError("Gestiona el inicio de sesión desde el selector de Herdr.")
        if not self.status()["active"]:
            raise AccountError("Registra primero tu Cuenta desde el selector de Herdr.")
        self.mark_terminal()
        os.execvpe(self.binary, [self.binary, "--no-daemon", "-c", 'cli_auth_credentials_store="file"',
                   "-c", 'forced_login_method="chatgpt"', *arguments], self.environment())

    def shell(self, arguments):
        if not self.binary:
            raise AccountError("Codex no está disponible en este equipo.")
        wrapper = self.root / "bin" / "codex"
        self.write(wrapper, "#!/bin/sh\nexec " + shlex.join([
            sys.executable, str(Path(__file__).resolve()), "--home", str(self.root),
            "--codex", self.binary, "launch", "--"]) + ' "$@"\n')
        wrapper.chmod(0o700)
        self.mark_terminal()
        env = self.environment()
        env["PATH"] = str(wrapper.parent) + os.pathsep + env.get("PATH", "")
        env["HERDR_ACCOUNTS_CODEX_BINARY"] = self.binary
        os.execvpe("/bin/zsh", ["/bin/zsh", "-f", *arguments], env)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--home", required=True)
    parser.add_argument("--codex")
    parser.add_argument("command", choices=["status", "enrol", "login", "cancel", "launch", "shell"])
    parser.add_argument("arguments", nargs=argparse.REMAINDER)
    args = parser.parse_args()
    try:
        accounts = Accounts(args.home, args.codex)
        arguments = args.arguments[1:] if args.arguments[:1] == ["--"] else args.arguments
        if args.command in ("login", "cancel"):
            if len(arguments) != 1:
                raise AccountError("Falta el identificador del registro.")
            result = getattr(accounts, args.command)(arguments[0])
        elif args.command in ("launch", "shell"):
            result = getattr(accounts, args.command)(arguments)
        else:
            result = getattr(accounts, args.command)()
        print(json.dumps(result))
        return 0
    except AccountError as exc:
        print(json.dumps({"error": str(exc)}))
        return 1
    except (OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError):
        print(json.dumps({"error": "No se pudo leer el estado administrado de Herdr."}))
        return 1


if __name__ == "__main__":
    sys.exit(main())
