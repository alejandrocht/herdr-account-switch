"""Integration tests through the same CLI consumed by the Herdr App mod."""
import json
import os
import signal
import shutil
import queue
import threading
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest


CONTROLLER = Path(__file__).with_name("herdr_accounts.py")
FAKE_CODEX = (Path(__file__).parent / "tests/fixtures/codex.py").read_text()


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
        self.external = self.root / "external-controls"
        for name in ("codex/auth.json", "codex/config.toml", "sqlite/control.db", "store/control.txt"):
            path = self.external / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("EXTERNAL_CONTROL_" + name)
        self.external_snapshot = {str(p.relative_to(self.external)): p.read_bytes()
                                  for p in self.external.rglob("*") if p.is_file()}
        self.env.update(CODEX_HOME=str(self.external / "codex"),
                        CODEX_SQLITE_HOME=str(self.external / "sqlite"),
                        HERDR_PLUGIN_STATE_DIR=str(self.external / "store"),
                        HERDR_PLUGIN_CONFIG_DIR=str(self.external / "store"))
        self.addCleanup(self.assert_external_unchanged)
        for key in list(self.env):
            if key.startswith("HC_"):
                self.env.pop(key)
        self.env.pop("HERDR_ACCOUNT_GROUP", None)
        self.provider_state = self.root / "provider.json"
        self.provider_state.write_text("{}")
        self.env["HERDR_TEST_PROVIDER_STATE"] = str(self.provider_state)

    def command(self, *args):
        return [sys.executable, str(CONTROLLER), "--home", str(self.managed),
                "--codex", str(self.binary), *args]

    def assert_external_unchanged(self):
        actual = {str(p.relative_to(self.external)): p.read_bytes()
                  for p in self.external.rglob("*") if p.is_file()}
        self.assertTrue(actual == self.external_snapshot, "External authentication/configuration controls changed")

    @unittest.skipUnless(shutil.which("node") and Path("/bin/zsh").exists(), "native mod launch harness")
    def test_account_button_never_leaves_a_shell_with_the_external_login(self):
        external = self.root / "external-codex"
        external.mkdir()
        sentinel = external / "auth.json"
        sentinel.write_text("external-login-must-not-change")
        dotdir = self.root / "shell-config"
        dotdir.mkdir()
        env = dict(self.env, CODEX_HOME=str(external), CODEX_SQLITE_HOME=str(external),
                   ZDOTDIR=str(dotdir), HERDR_ACCOUNTS_CODEX_BINARY=str(self.binary),
                   HERDR_TEST_MOD_CONFIG=json.dumps({"python": sys.executable,
                       "controller": str(CONTROLLER), "accounts_home": str(self.managed)}))
        result = subprocess.run(["node", "--experimental-vm-modules",
            str(CONTROLLER.parent / "tests/fixtures/account_button.mjs"),
            str(CONTROLLER.parent / "mod/main.js")], env=env,
            capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)
        launches = json.loads(result.stdout)
        self.assertEqual(len(launches), 1)
        launch = launches[0]
        argv = launch["argv"]
        if launch["route"] == "agent-menu":
            # Exact macOS agent wrapper observed in hc get: the account command
            # returns to an ordinary login shell. Never load the user's profiles.
            argv = ["/bin/zsh", "-lic", '\"$@\"; exec \"$0\" -li', "/bin/zsh", *argv]
        probe = subprocess.run(argv, env=env, cwd=self.root,
            input=str(self.binary) + " login\nexit\n", capture_output=True, text=True, timeout=10)
        self.assertEqual(probe.returncode, 0, probe.stderr)
        self.assertTrue((self.managed / "codex/auth.json").exists())
        self.assertTrue(sentinel.read_text() == "external-login-must-not-change",
                         "The account button returned to a shell that can overwrite the external login")

    def call(self, *args, ok=True):
        result = subprocess.run(self.command(*args), env=self.env,
                                capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0 if ok else 1, result.stderr)
        self.assertNotIn("FIXTURE_SECRET", result.stdout + result.stderr)
        self.assert_external_unchanged()
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

    def interactive_conversation(self):
        worker = subprocess.Popen(self.command("launch"), env=self.env, cwd=self.root,
                                  stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                  text=True, start_new_session=True)
        worker.events = queue.Queue()
        def read():
            for line in worker.stdout:
                worker.events.put(line)
            worker.events.put(None)
        reader = threading.Thread(target=read, daemon=True)
        reader.start()
        def close():
            if worker.poll() is None:
                worker.terminate()
            worker.wait(timeout=10)
            reader.join(timeout=1)
            worker.stdin.close()
            worker.stdout.close()
            worker.stderr.close()
        self.addCleanup(close)
        return worker

    def next_event(self, worker, *, working=False):
        while True:
            line = worker.events.get(timeout=15)
            self.assertTrue(line, "El Agente terminó antes de confirmar la operación")
            self.assertNotIn("FIXTURE_SECRET", line)
            event = json.loads(line)
            if working or event.get("event") != "working":
                return event

    def set_provider(self, **values):
        staged = self.provider_state.with_suffix(".tmp")
        state = json.loads(self.provider_state.read_text())
        state.update(values)
        staged.write_text(json.dumps(state))
        staged.replace(self.provider_state)

    def two_accounts(self):
        first = self.call("enrol")
        self.call("login", first["login_id"])
        self.env["HERDR_TEST_ACCOUNT"] = "second"
        second = self.call("enrol")
        self.call("login", second["login_id"])

    def phase(self, expected):
        deadline = time.monotonic() + 10
        while True:
            state = self.call("status")
            if state["switch"].get("phase") == expected:
                return state
            self.assertLess(time.monotonic(), deadline, state["switch"])
            time.sleep(0.02)

    def test_a_rejected_target_keeps_the_running_thread_and_account(self):
        self.two_accounts()
        worker = self.interactive_conversation()
        ready = self.next_event(worker)
        worker.stdin.write("write-once\n")
        worker.stdin.flush()
        self.next_event(worker)
        self.set_provider(rejected=["second-account"])
        self.call("select", "second")
        failed = self.phase("failed")
        self.assertEqual(failed["active"]["label"], "demo")
        self.assertFalse(failed["switch"]["identity_verified"])
        worker.stdin.write("continue\n")
        worker.stdin.flush()
        result = self.next_event(worker)
        self.assertEqual(result["thread_id"], ready["thread_id"])
        self.assertEqual(result["account"], "demo-account")
        self.assertEqual((self.root / "work.txt").read_text(), "1")

    def test_failed_effective_adoption_restores_the_original_native_thread(self):
        self.two_accounts()
        worker = self.interactive_conversation()
        ready = self.next_event(worker)
        worker.stdin.write("write-once\n")
        worker.stdin.flush()
        original = self.next_event(worker)
        self.set_provider(reject_activation="second-account", live_home=str(self.managed / "codex"))
        self.call("select", "second")
        restored = self.next_event(worker)
        self.assertEqual(restored["thread_id"], ready["thread_id"])
        self.assertEqual(restored["history"], original["history"])
        self.assertEqual(self.phase("failed")["active"]["label"], "demo")
        self.assertEqual((self.root / "work.txt").read_text(), "1")

    def test_switch_waits_for_a_running_tool_to_finish(self):
        self.two_accounts()
        worker = self.interactive_conversation()
        ready = self.next_event(worker)
        self.set_provider(hold_turns=True)
        worker.stdin.write("write-once\n")
        worker.stdin.flush()
        self.assertEqual(self.next_event(worker, working=True)["event"], "working")
        self.call("select", "second")
        pending = self.phase("waiting")
        self.assertEqual(pending["active"]["label"], "demo")
        self.assertFalse((self.root / "work.txt").exists())
        self.set_provider(hold_turns=False)
        while True:
            result = self.next_event(worker)
            if result["event"] == "ready":
                break
        self.assertEqual(result["thread_id"], ready["thread_id"])
        self.assertEqual((self.root / "work.txt").read_text(), "1")
        self.assertEqual(self.phase("adopted")["active"]["label"], "second")

    def test_rollback_parks_credentials_renewed_by_the_target_agent(self):
        self.two_accounts()
        worker = self.interactive_conversation()
        original = self.next_event(worker)
        worker.stdin.write("write-once\n")
        worker.stdin.flush()
        self.next_event(worker)
        self.set_provider(refresh_live="second-account", reject_resume="second-account",
                          live_home=str(self.managed / "codex"))
        self.call("select", "second")
        restored = self.next_event(worker)
        self.assertEqual(restored["thread_id"], original["thread_id"])
        self.assertEqual(self.phase("failed")["active"]["label"], "demo")
        self.set_provider(refresh_live=None, reject_resume=None)
        self.call("select", "second")
        self.assertEqual(self.phase("adopted")["active"]["label"], "second")
        self.assertEqual(self.next_event(worker)["thread_id"], original["thread_id"])
        self.assertEqual((self.root / "work.txt").read_text(), "1")

    def test_interrupting_an_unconfirmed_change_restores_the_previous_account(self):
        self.two_accounts()
        worker = self.interactive_conversation()
        self.next_event(worker)
        worker.stdin.write("write-once\n")
        worker.stdin.flush()
        self.next_event(worker)
        self.set_provider(hold_resume="second-account")
        self.call("select", "second")
        deadline = time.monotonic() + 10
        while not json.loads(self.provider_state.read_text()).get("resume_waiting"):
            self.assertLess(time.monotonic(), deadline)
            time.sleep(0.02)
        worker.terminate()
        worker.wait(timeout=10)
        self.assertEqual(self.call("status")["active"]["label"], "demo")
        self.assertEqual((self.root / "work.txt").read_text(), "1")

    def test_select_cannot_overlap_an_unfinished_registration(self):
        self.two_accounts()
        self.running_login()
        rejected = self.call("select", "second", ok=False)
        self.assertIn("registro", rejected["error"].lower())
        self.assertEqual(self.call("status")["active"]["label"], "demo")

    def test_interrupting_a_cold_selection_restores_the_previous_account(self):
        self.two_accounts()
        self.set_provider(hold_activation="second-account", live_home=str(self.managed / "codex"))
        worker = subprocess.Popen(self.command("select", "second"), env=self.env,
                                  stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        def cleanup():
            if worker.poll() is None:
                worker.terminate()
            worker.communicate(timeout=5)
            state = json.loads(self.provider_state.read_text())
            pid = state.get("activation_pid")
            if pid:
                command = subprocess.run(["/bin/ps", "-p", str(pid), "-o", "command="],
                                         capture_output=True, text=True).stdout
                if str(self.binary) in command:
                    os.kill(pid, signal.SIGTERM)
        self.addCleanup(cleanup)
        deadline = time.monotonic() + 6
        while not json.loads(self.provider_state.read_text()).get("activation_waiting"):
            self.assertLess(time.monotonic(), deadline)
            time.sleep(0.02)
        worker.terminate()
        worker.communicate(timeout=5)
        state = self.call("status")
        self.assertEqual(state["active"]["label"], "demo")
        self.assertEqual(state["switch"]["phase"], "failed")

    def test_switch_cycle_preserves_the_native_thread_and_does_not_repeat_its_tool(self):
        first = self.call("enrol")
        self.call("login", first["login_id"])
        self.env["HERDR_TEST_ACCOUNT"] = "second"
        second = self.call("enrol")
        self.call("login", second["login_id"])
        worker = self.interactive_conversation()
        started = self.next_event(worker)
        self.assertEqual(started["event"], "ready")
        worker.stdin.write("write-once\n")
        worker.stdin.flush()
        original = self.next_event(worker)
        self.assertEqual(original["account"], "demo-account")
        requested = self.call("select", "second")
        self.assertIn(requested["switch"]["phase"], ("requested", "checking", "resuming", "adopted"))
        resumed = self.next_event(worker)
        self.assertEqual(resumed["event"], "ready")
        self.assertEqual(resumed["thread_id"], started["thread_id"])
        self.assertEqual(resumed["history"], original["history"])
        worker.stdin.write("continue\n")
        worker.stdin.flush()
        continued = self.next_event(worker)
        self.assertEqual(continued["account"], "second-account")
        self.assertEqual((self.root / "work.txt").read_text(), "1")
        self.call("select", "demo")
        returned = self.next_event(worker)
        self.assertEqual(returned["thread_id"], started["thread_id"])
        self.assertEqual(returned["history"], continued["history"])
        self.assertEqual((self.root / "work.txt").read_text(), "1")

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

    def test_registering_a_second_account_preserves_the_active_account(self):
        first = self.call("enrol")
        self.call("login", first["login_id"])
        self.env["HERDR_TEST_ACCOUNT"] = "second"
        second = self.call("enrol")
        self.assertNotEqual(second["login_id"], first["login_id"])
        self.call("login", second["login_id"])
        state = self.call("status")
        self.assertEqual({p["label"] for p in state["profiles"]}, {"demo", "second"})
        self.assertEqual(state["active"]["label"], "demo")

    def test_saved_accounts_deduplicate_without_a_three_account_limit(self):
        for name in ("demo", "second", "third", "fourth", "second"):
            self.env["HERDR_TEST_ACCOUNT"] = name
            pending = self.call("enrol")
            self.call("login", pending["login_id"])
        state = self.call("status")
        self.assertEqual(len(state["profiles"]), 4)
        self.assertTrue(state["login"]["duplicate"])
        self.assertEqual(state["active"]["label"], "demo")

    def test_a_failed_additional_login_keeps_the_saved_and_active_account(self):
        pending = self.call("enrol")
        self.call("login", pending["login_id"])
        pending = self.call("enrol")
        self.env["HERDR_TEST_LOGIN"] = "fail"
        self.call("login", pending["login_id"], ok=False)
        state = self.call("status")
        self.assertEqual(len(state["profiles"]), 1)
        self.assertEqual(state["active"]["label"], "demo")

    def test_a_saved_account_can_be_selected_without_another_browser_login(self):
        first = self.call("enrol")
        self.call("login", first["login_id"])
        self.env["HERDR_TEST_ACCOUNT"] = "second"
        second = self.call("enrol")
        self.call("login", second["login_id"])
        result = self.call("select", "second")
        self.assertEqual(result["active"]["label"], "second")
        self.assertEqual(result["switch"]["phase"], "prepared")
        self.assertTrue(result["switch"]["identity_verified"])
        self.assertEqual(self.call("status")["active"]["label"], "second")

    def test_switch_refuses_a_legacy_managed_conversation_without_changing_its_account(self):
        first = self.call("enrol")
        self.call("login", first["login_id"])
        self.env["HERDR_TEST_ACCOUNT"] = "second"
        second = self.call("enrol")
        self.call("login", second["login_id"])
        hc = self.root / "hc"
        hc.write_text("#!/usr/bin/env python3\nimport json, os, sys\n"
            "value = {'terminals': [{'address': 'legacy'}]} if sys.argv[1] == 'ls' else "
            "{'labels': {'herdr.accounts': os.environ['HERDR_ACCOUNT_GROUP']}, "
            "'foreground': {'name': 'Python'}}\nprint(json.dumps(value))\n")
        hc.chmod(0o700)
        self.env.update(HC_SOCKET=str(self.root / "fake-core.sock"),
                        PATH=str(self.root) + os.pathsep + self.env["PATH"])
        rejected = self.call("select", "second", ok=False)
        self.assertIn("reanudar", rejected["error"].lower())
        self.assertEqual(self.call("status")["active"]["label"], "demo")

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
        result = self.call("launch", "--", "exec", "--model", "demo")
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
        result = self.call("shell", "--", "-c", "codex exec --model demo")
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
