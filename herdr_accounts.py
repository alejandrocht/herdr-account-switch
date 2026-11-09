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
import signal
import subprocess
import sys
import time
import uuid
from codex_runtime import AUTH_OPTIONS, NativeError, NativeServer


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
        self.inherited_group = os.environ.get("HERDR_ACCOUNT_GROUP") == str(self.root)
        for name in ("codex", "store", "enrol", "verify", "runtimes", "bin", "login.json", "switch.json", "core.json", "lock"):
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
        job = json.loads(self.job_file.read_text()) if self.job_file.exists() else {}
        if job.get("state") == "running" and job.get("worker_pid") not in (None, os.getpid()):
            if self.process_stamp(job["worker_pid"]) != job.get("worker_stamp"):
                job.update(state="failed", error="El registro se interrumpió. Vuelve a conectar la Cuenta.")
        return job

    @staticmethod
    def process_stamp(pid):
        result = subprocess.run(["/bin/ps", "-p", str(pid), "-o", "lstart="],
                                capture_output=True, text=True, timeout=3,
                                env=dict(os.environ, LC_ALL="C"))
        return result.stdout.strip() if result.returncode == 0 else None

    @staticmethod
    def stop_process(process):
        if process and process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()

    def status(self):
        if os.environ.get("HERDR_APP_HOME") == str(self.root.parent) and not (self.root / "core.json").exists():
            self.remember_core()
        store = self.store()
        profiles = [{"slug": p["slug"], "label": p["label"],
                     "email": p.get("identity", {}).get("email")}
                    for p in store.list_profiles("codex")]
        active = store.active_profile("codex")
        active = next((p for p in profiles if active and p["slug"] == active["slug"]), None)
        job = self.job()
        pending = job.get("state") in ("pending", "running")
        selection_file = self.root / "switch.json"
        selection = json.loads(selection_file.read_text()) if selection_file.exists() else {}
        return {"agent": "codex", "available": bool(self.binary and os.access(self.binary, os.X_OK)),
                "state": "enrolling" if pending else "active" if active else "empty",
                "profiles": profiles, "active": active,
                "switch": selection,
                "login": {k: job[k] for k in ("id", "state", "error", "profile", "duplicate") if k in job}}

    def enrol(self):
        if not self.binary or not os.access(self.binary, os.X_OK):
            raise AccountError("Codex no está disponible en este equipo.")
        with self.locked():
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
            job.update(worker_pid=os.getpid(), worker_stamp=self.process_stamp(os.getpid()))
            self.write(self.job_file, job)
        stage = self.root / "enrol" / login_id
        env = self.environment(stage)
        process = None
        interrupted = False
        def interrupt(_signum, _frame):
            nonlocal interrupted
            interrupted = True
        previous_handlers = {sig: signal.signal(sig, interrupt)
                             for sig in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP)}
        try:
            options = [self.binary, *AUTH_OPTIONS]
            process = subprocess.Popen([*options, "login"], env=env)
            while process.poll() is None:
                if interrupted or self.job().get("id") != login_id or self.job().get("state") == "cancelled":
                    self.cancel(login_id)
                    self.stop_process(process)
                    return self.status()
                time.sleep(0.15)
            if interrupted:
                return self.cancel(login_id)
            verified = process.returncode == 0 and subprocess.run(
                [*options, "login", "status"], env=env, capture_output=True, timeout=15).returncode == 0
            with self.locked():
                job = self.job()
                if interrupted or job.get("id") != login_id or job.get("state") == "cancelled":
                    if interrupted and job.get("id") == login_id:
                        job["state"] = "cancelled"
                        self.write(self.job_file, job)
                    return self.status()
                if not verified:
                    raise AccountError("El inicio de sesión no se completó. Puedes volver a intentarlo.")
                auth = json.loads((stage / "auth.json").read_text())
                store = self.store()
                payload = {"auth": auth}
                backend = store.BACKENDS["codex"]
                identity = backend.identity(payload)
                if not identity.get("account_id"):
                    raise AccountError("Codex no confirmó la identidad de la Cuenta.")
                profile = store.active_profile("codex", payload)
                duplicate = profile is not None
                if not profile:
                    profile = store.make_profile("codex", store.default_label("codex", identity), payload)
                    store.write_profile(profile)
                if backend.read_live() is None:
                    self.write(self.codex_home / "auth.json", profile["payload"]["auth"])
                self.write(self.job_file, {"id": login_id, "state": "completed",
                                          "profile": profile["slug"], "duplicate": duplicate})
            return self.status()
        except (OSError, ValueError, subprocess.SubprocessError, AccountError):
            with self.locked():
                if self.job().get("id") == login_id and self.job().get("state") != "cancelled":
                    self.write(self.job_file, {"id": login_id, "state": "failed",
                               "error": "No se pudo registrar la Cuenta. Vuelve a iniciar sesión."})
            raise AccountError("No se pudo registrar la Cuenta. Vuelve a iniciar sesión.")
        finally:
            self.stop_process(process)
            for sig, handler in previous_handlers.items():
                signal.signal(sig, handler)
            shutil.rmtree(stage, ignore_errors=True)

    def cancel(self, login_id):
        with self.locked():
            job = self.job()
            if job.get("id") == login_id and job.get("state") in ("pending", "running"):
                job["state"] = "cancelled"
                self.write(self.job_file, job)
        return self.status()

    def verified_payload(self, _kind, profile):
        store = self.store()
        stage = self.root / "verify" / uuid.uuid4().hex
        self.write(stage / "auth.json", profile["payload"]["auth"])
        config = self.codex_home / "config.toml"
        if config.exists():
            self.write(stage / "config.toml", config.read_text())
        try:
            with NativeServer(self.binary, self.environment(stage), cwd=stage) as server:
                with server.connect() as rpc:
                    rpc.call("account/rateLimits/read")
                fresh = {"auth": json.loads((stage / "auth.json").read_text())}
                server.verify(fresh)
                return fresh
        finally:
            try:
                fresh = {"auth": json.loads((stage / "auth.json").read_text())}
                match = store.active_profile("codex", fresh)
                if match and match["slug"] == profile["slug"]:
                    profile["payload"] = fresh
                    store.write_profile(profile)
            finally:
                shutil.rmtree(stage, ignore_errors=True)

    def remember_core(self):
        if os.environ.get("HC_SOCKET"):
            keys = ("HC_SOCKET", "HC_SESSION", "XDG_CONFIG_HOME", "XDG_STATE_HOME", "XDG_DATA_HOME", "XDG_CACHE_HOME")
            self.write(self.root / "core.json", {key: os.environ[key] for key in keys if key in os.environ})

    def native_terminals(self):
        path = self.root / "core.json"
        context = json.loads(path.read_text()) if path.exists() else {}
        if not context and os.environ.get("HC_SOCKET"):
            context = {"HC_SOCKET": os.environ["HC_SOCKET"]}
        if not context:
            return []
        env = dict(os.environ, **context)
        def read(*arguments):
            result = subprocess.run(["hc", *arguments], env=env, capture_output=True, text=True, timeout=5)
            if result.returncode:
                raise AccountError("No se pudo comprobar el estado de las conversaciones de Herdr.")
            return json.loads(result.stdout)
        listed = read("ls", "--json")
        terminals = [read("get", entry["address"]) for entry in listed.get("terminals", [])
                     if entry.get("state") == "live" or "state" not in entry]
        return [entry for entry in terminals if entry.get("labels", {}).get("herdr.accounts") == str(self.root)]

    def live_runtimes(self):
        records = []
        for path in (self.root / "runtimes").glob("*.json"):
            record = json.loads(path.read_text())
            if self.process_stamp(record["pid"]) == record.get("stamp"):
                records.append(record)
        return records

    def switch_sessions(self):
        sessions = self.live_runtimes()
        known = {session.get("terminal") for session in sessions}
        for terminal in self.native_terminals():
            name = terminal.get("foreground", {}).get("name", "").lower()
            if terminal.get("address") not in known and name not in ("zsh", "bash", "sh", "fish", "nu"):
                raise AccountError("Esta Conversación usa el lanzador anterior. Debes reanudar el hilo con el nuevo lanzador antes de cambiar de Cuenta.")
        if len(sessions) > 1:
            raise AccountError("Esta entrega cambia una Conversación a la vez. La coordinación entre pestañas se añadirá después.")
        return sessions

    def select(self, key):
        with self.locked():
            store = self.store()
            profile = store.get_profile("codex", key)
            if not profile:
                raise AccountError("No existe esa Cuenta guardada.")
            if self.status()["active"] and self.status()["active"]["slug"] == profile["slug"]:
                return self.status()
            self.switch_sessions()
            job = {"id": uuid.uuid4().hex, "requested": profile["slug"], "phase": "checking",
                   "identity_verified": False}
            self.write(self.root / "switch.json", job)
            previous = store.BACKENDS["codex"].read_live()
            try:
                store.switch("codex", profile["slug"], verifier=self.verified_payload)
                payload = store.BACKENDS["codex"].read_live()
                with NativeServer(self.binary, self.environment(), cwd=self.root) as server:
                    server.verify(payload)
                job.update(phase="prepared", identity_verified=True)
            except (NativeError, OSError, ValueError, subprocess.SubprocessError, store.SwitchError):
                if previous:
                    store.BACKENDS["codex"].write_live(previous)
                job.update(phase="failed", error="No se pudo verificar la Cuenta. La selección anterior se conserva.")
            self.write(self.root / "switch.json", job)
        return self.status()

    def mark_terminal(self, active=True):
        if active:
            self.remember_core()
        terminal = os.environ.get("HC_TERMINAL_ID")
        if terminal and shutil.which("hc"):
            result = subprocess.run(["hc", "label", terminal,
                                     "herdr.accounts=" + (str(self.root) if active else "")],
                                    capture_output=True, timeout=5)
            if result.returncode:
                raise AccountError("No se pudo identificar este terminal como administrado.")

    def managed_process(self, command, env):
        # Herdr starts a normal shell when an explicit command exits. Release
        # our label before that shell appears; nested Codex keeps its shell's label.
        owns_label = not self.inherited_group
        if owns_label:
            self.mark_terminal()
        process = None
        previous = {}
        def terminate(signum, _frame):
            raise SystemExit(128 + signum)
        try:
            process = subprocess.Popen(command, env=env)
            previous = {sig: signal.signal(sig, handler) for sig, handler in (
                (signal.SIGINT, lambda _sig, _frame: None),
                (signal.SIGTERM, terminate), (signal.SIGHUP, terminate))}
            code = process.wait()
        finally:
            self.stop_process(process)
            for sig, handler in previous.items():
                signal.signal(sig, handler)
            if owns_label:
                self.mark_terminal(False)
        sys.exit(code if code >= 0 else 128 - code)

    def launch(self, arguments):
        protected = ("cli_auth_credentials_store", "forced_login_method", "model_provider",
                     "model_providers", "chatgpt_base_url", "openai_base_url")
        for argument in arguments:
            setting = argument
            if setting.startswith("--config="):
                setting = setting[len("--config="):]
            elif setting.startswith("-c"):
                setting = setting[2:].lstrip("=")
            key = setting.split("=", 1)[0].split(".", 1)[0].strip().strip("\"'")
            if argument in ("login", "logout") or argument.startswith("--remote") or key in protected:
                raise AccountError("Gestiona el inicio de sesión desde el selector de Herdr.")
        if not self.status()["active"]:
            raise AccountError("Registra primero tu Cuenta desde el selector de Herdr.")
        self.managed_process([self.binary, "--no-daemon", *AUTH_OPTIONS, *arguments], self.environment())

    def shell(self, arguments):
        if not self.binary:
            raise AccountError("Codex no está disponible en este equipo.")
        wrapper = self.root / "bin" / "codex"
        self.write(wrapper, "#!/bin/sh\nexec " + shlex.join([
            sys.executable, str(Path(__file__).resolve()), "--home", str(self.root),
            "--codex", self.binary, "launch", "--"]) + ' "$@"\n')
        wrapper.chmod(0o700)
        env = self.environment()
        env["PATH"] = str(wrapper.parent) + os.pathsep + env.get("PATH", "")
        env["HERDR_ACCOUNTS_CODEX_BINARY"] = self.binary
        self.managed_process(["/bin/zsh", "-f", *arguments], env)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--home", required=True)
    parser.add_argument("--codex")
    parser.add_argument("command", choices=["status", "enrol", "login", "cancel", "select", "launch", "shell"])
    parser.add_argument("arguments", nargs=argparse.REMAINDER)
    args = parser.parse_args()
    try:
        accounts = Accounts(args.home, args.codex)
        arguments = args.arguments[1:] if args.arguments[:1] == ["--"] else args.arguments
        if args.command in ("login", "cancel", "select"):
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
