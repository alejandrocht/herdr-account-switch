"""Integration tests through the same CLI consumed by the Herdr App mod."""
import json
import os
import signal
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest


CONTROLLER = Path(__file__).with_name("herdr_accounts.py")
FAKE_CODEX = '''#!/usr/bin/env python3
import base64, json, os, pathlib, sys, time
args = sys.argv[1:]
auth = pathlib.Path(os.environ["CODEX_HOME"]) / "auth.json"
if "login" in args:
    if "status" in args:
        sys.exit(0 if auth.exists() else 1)
    mode = os.environ.get("HERDR_TEST_LOGIN", "success")
    if mode == "wait":
        print("LOGIN_WAITING", flush=True)
        time.sleep(60)
    if mode == "fail":
        print("fake login failed", file=sys.stderr)
        sys.exit(1)
    claims = {"email": "demo@example.invalid", "https://api.openai.com/auth": {
        "chatgpt_account_id": "demo-account", "chatgpt_plan_type": "plus"}}
    token = "fixture." + base64.urlsafe_b64encode(json.dumps(claims).encode()).decode().rstrip("=") + ".fixture"
    auth.parent.mkdir(parents=True, exist_ok=True)
    auth.write_text(json.dumps({"auth_mode": "chatgpt", "tokens": {
        "id_token": token, "account_id": "demo-account", "access_token": "FIXTURE_SECRET"}}))
else:
    print(json.dumps({"args": args, "codex_home": os.environ.get("CODEX_HOME"),
        "sqlite_home": os.environ.get("CODEX_SQLITE_HOME"),
        "api_key": os.environ.get("OPENAI_API_KEY"), "group": os.environ.get("HERDR_ACCOUNT_GROUP")}))
'''


class AccountFlow(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="herdr-account-flow-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.managed = self.root / "managed"
        self.binary = self.root / "codex"
        self.binary.write_text(FAKE_CODEX)
        self.binary.chmod(0o700)
        self.env = dict(os.environ, OPENAI_API_KEY="outside-key")
        self.env.pop("HC_TERMINAL_ID", None)
        self.env.pop("HERDR_ACCOUNT_GROUP", None)

    def command(self, *args):
        return [sys.executable, str(CONTROLLER), "--home", str(self.managed),
                "--codex", str(self.binary), *args]

    def call(self, *args, ok=True):
        result = subprocess.run(self.command(*args), env=self.env,
                                capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0 if ok else 1, result.stderr)
        self.assertNotIn("FIXTURE_SECRET", result.stdout + result.stderr)
        return json.loads(result.stdout)

    def running_login(self):
        pending = self.call("enrol")
        env = dict(self.env, HERDR_TEST_LOGIN="wait")
        worker = subprocess.Popen(self.command("login", pending["login_id"]),
                                  env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                  text=True, start_new_session=True)
        def clean_worker():
            try:
                os.killpg(worker.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
            worker.communicate(timeout=5)
        self.addCleanup(clean_worker)
        deadline = time.monotonic() + 5
        while self.call("status")["login"].get("state") != "running":
            self.assertLess(time.monotonic(), deadline)
            time.sleep(0.02)
        return pending, worker

    def test_empty_selector_identifies_codex_without_reading_an_external_login(self):
        outside = self.root / "outside"
        outside.mkdir()
        sentinel = outside / "auth.json"
        sentinel.write_text("external-login")
        self.env["CODEX_HOME"] = str(outside)
        state = self.call("status")
        self.assertEqual(state["state"], "empty")
        self.assertEqual(state["profiles"], [])
        self.assertTrue(state["available"])
        self.assertEqual(sentinel.read_text(), "external-login")

    def test_official_login_registers_a_persistent_private_profile(self):
        pending = self.call("enrol")
        self.assertEqual(self.call("status")["state"], "enrolling")
        self.call("login", pending["login_id"])
        state = self.call("status")
        self.assertEqual(state["state"], "active")
        self.assertEqual(state["active"]["label"], "demo")
        self.assertEqual(len(state["profiles"]), 1)
        self.assertEqual(self.managed.stat().st_mode & 0o777, 0o700)

    def test_cancelled_login_does_not_register_an_account(self):
        pending, worker = self.running_login()
        self.call("cancel", pending["login_id"])
        worker.communicate(timeout=5)
        state = self.call("status")
        self.assertEqual(state["profiles"], [])
        self.assertEqual(state["login"]["state"], "cancelled")

    def test_interrupting_login_allows_a_fresh_attempt(self):
        pending, worker = self.running_login()
        os.killpg(worker.pid, signal.SIGINT)
        worker.communicate(timeout=5)
        self.assertNotEqual(self.call("status")["state"], "enrolling")
        self.assertNotEqual(self.call("enrol")["login_id"], pending["login_id"])

    def test_an_orphaned_login_can_be_retried(self):
        pending, worker = self.running_login()
        os.killpg(worker.pid, signal.SIGKILL)
        worker.communicate(timeout=5)
        self.assertEqual(self.call("status")["login"]["state"], "failed")
        self.assertNotEqual(self.call("enrol")["login_id"], pending["login_id"])

    def test_launch_uses_only_the_registered_herdr_identity(self):
        pending = self.call("enrol")
        self.call("login", pending["login_id"])
        result = self.call("launch", "--", "--model", "demo")
        self.assertEqual(result["codex_home"], str(self.managed / "codex"))
        self.assertEqual(result["sqlite_home"], str(self.managed / "codex"))
        self.assertEqual(result["group"], str(self.managed))
        self.assertIsNone(result["api_key"])
        self.assertIn("--no-daemon", result["args"])
        self.assertEqual(result["args"][-2:], ["--model", "demo"])

    def test_managed_command_cannot_replace_the_login_outside_the_selector(self):
        pending = self.call("enrol")
        self.call("login", pending["login_id"])
        rejected = self.call("launch", "--", "logout", ok=False)
        self.assertIn("selector", rejected["error"])
        self.assertEqual(self.call("status")["active"]["label"], "demo")

    def test_attached_configuration_cannot_override_managed_authentication(self):
        pending = self.call("enrol")
        self.call("login", pending["login_id"])
        for argument in ('--config=cli_auth_credentials_store="keyring"',
                         '-cforced_login_method="api"'):
            with self.subTest(argument=argument):
                self.call("launch", "--", argument, ok=False)

    def test_normal_codex_command_inside_a_managed_terminal_stays_isolated(self):
        pending = self.call("enrol")
        self.call("login", pending["login_id"])
        result = self.call("shell", "--", "-c", "codex --model demo")
        self.assertEqual(result["codex_home"], str(self.managed / "codex"))
        self.assertEqual(result["group"], str(self.managed))
        self.assertIsNone(result["api_key"])

    def test_terminal_label_lasts_only_for_its_managed_process(self):
        pending = self.call("enrol")
        self.call("login", pending["login_id"])
        events = self.root / "labels.jsonl"
        hc = self.root / "hc"
        hc.write_text("#!/usr/bin/env python3\nimport json, os, sys\n"
                      "with open(os.environ['HERDR_TEST_LABELS'], 'a') as out:\n"
                      "    out.write(json.dumps(sys.argv[1:]) + '\\n')\n")
        hc.chmod(0o700)
        self.env.update(HC_TERMINAL_ID="fixture-terminal", HERDR_TEST_LABELS=str(events),
                        PATH=str(self.root) + os.pathsep + self.env["PATH"])
        for arguments in (("launch", "--", "--version"),
                          ("shell", "--", "-c", "exit 0"),
                          ("shell", "--", "-c", "codex --version")):
            with self.subTest(arguments=arguments):
                events.unlink(missing_ok=True)
                result = subprocess.run(self.command(*arguments), env=self.env,
                                        capture_output=True, text=True, timeout=10)
                self.assertEqual(result.returncode, 0, result.stderr)
                labels = [json.loads(line) for line in events.read_text().splitlines()]
                self.assertEqual(labels, [
                    ["label", "fixture-terminal", "herdr.accounts=" + str(self.managed)],
                    ["label", "fixture-terminal", "herdr.accounts="],
                ])


if __name__ == "__main__":
    unittest.main()
